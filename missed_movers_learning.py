import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx

NY = ZoneInfo('America/New_York')
DB = Path(__file__).resolve().parent / 'signal_journal.sqlite3'
STRATEGY_VERSION = 'strategy-learning-v2'
MOVE_THRESHOLD_PCT = 8.0

def _f(v):
    try:
        return float(v)
    except Exception:
        return None

def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS missed_movers(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_date TEXT,symbol TEXT,observed_at TEXT,move_pct REAL,price REAL,volume REAL,was_top10 INTEGER,top10_best_rank INTEGER,strategy_version TEXT,features TEXT,premarket_gap_pct REAL,premarket_volume REAL,premarket_high REAL,premarket_low REAL,premarket_last REAL,first_seen_top10 TEXT,discovery_source TEXT,verification_feed TEXT,verified INTEGER,asset_name TEXT,instrument_type TEXT,eligible_common_stock INTEGER,asset_status TEXT,tradable INTEGER,asset_attributes TEXT,UNIQUE(trade_date,symbol,strategy_version))''')
    existing = {r[1] for r in con.execute('PRAGMA table_info(missed_movers)').fetchall()}
    cols = {'premarket_gap_pct':'REAL','premarket_volume':'REAL','premarket_high':'REAL','premarket_low':'REAL','premarket_last':'REAL','first_seen_top10':'TEXT','discovery_source':'TEXT','verification_feed':'TEXT','verified':'INTEGER','asset_name':'TEXT','instrument_type':'TEXT','eligible_common_stock':'INTEGER','asset_status':'TEXT','tradable':'INTEGER','asset_attributes':'TEXT'}
    for col, typ in cols.items():
        if col not in existing:
            con.execute(f'ALTER TABLE missed_movers ADD COLUMN {col} {typ}')
    con.commit()
    return con

async def _sip_movers(core, limit=50):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):
        return [], {'status':'no_credentials','count':0}
    headers = {'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    requested_top = max(1, min(int(limit or 50), 50))
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get('https://data.alpaca.markets/v1beta1/screener/stocks/movers', headers=headers, params={'top':requested_top})
    if response.status_code >= 400:
        return [], {'status':f'http_{response.status_code}','count':0,'requested_top':requested_top,'body':(response.text or '')[:200]}
    data = response.json() or {}
    raw = data.get('gainers') or []
    out = []
    for x in raw:
        symbol = str(x.get('symbol') or '').upper()
        pct = _f(x.get('percent_change'))
        if symbol and pct is not None:
            out.append({'symbol':symbol,'move_pct':pct,'price':_f(x.get('price')),'change':_f(x.get('change')),'raw':x})
    out.sort(key=lambda z:z['move_pct'], reverse=True)
    return out, {'status':'ok','count':len(out),'raw_gainers':len(raw),'requested_top':requested_top,'keys':list(data.keys())[:10]}

async def _asset(core, symbol):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):
        return None
    headers = {'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f'https://paper-api.alpaca.markets/v2/assets/{symbol}', headers=headers)
        return (response.json() or {}) if response.status_code < 400 else None
    except Exception:
        return None

def _instrument(asset, symbol):
    name = str((asset or {}).get('name') or '').lower()
    s = str(symbol or '').upper()
    if 'warrant' in name or s.endswith('.WS') or s.endswith('WS') or (len(s) >= 5 and s.endswith('W')):
        return 'warrant'
    if 'right' in name or s.endswith('.RT') or s.endswith('RT') or (len(s) >= 5 and s.endswith('R')):
        return 'right'
    if 'unit' in name or s.endswith('.U'):
        return 'unit'
    if 'preferred' in name or 'depositary share' in name:
        return 'preferred'
    if 'etf' in name or 'exchange traded fund' in name:
        return 'etf'
    if 'common stock' in name or 'common share' in name or 'ordinary share' in name:
        return 'common_stock'
    return 'other_equity'

def _eligible(asset, instrument):
    return bool(asset and asset.get('status') == 'active' and asset.get('tradable') is True and instrument in ('common_stock','other_equity'))

async def _iex_snapshot(core, symbol):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):
        return None
    headers = {'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot', headers=headers, params={'feed':core.ALPACA_FEED})
    if response.status_code >= 400:
        return None
    data = response.json() or {}
    return data if data else None

async def _premarket(core, symbol, day):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):
        return {}
    headers = {'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    params = {'timeframe':'1Min','start':f'{day}T04:00:00-04:00','end':f'{day}T09:30:00-04:00','limit':10000,'feed':core.ALPACA_FEED,'adjustment':'split','sort':'asc'}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars', headers=headers, params=params)
    bars = ((response.json() or {}).get('bars') or []) if response.status_code < 400 else []
    if not bars:
        return {}
    lows = [_f(b.get('l')) for b in bars if _f(b.get('l')) is not None]
    highs = [_f(b.get('h')) for b in bars if _f(b.get('h')) is not None]
    return {'last':_f(bars[-1].get('c')),'volume':sum(_f(b.get('v')) or 0 for b in bars),'high':max(highs) if highs else None,'low':min(lows) if lows else None,'bars':len(bars)}

def install_missed_movers_learning(app, core):
    @app.post('/api/learning/missed-movers')
    async def missed_movers(threshold_pct:float=MOVE_THRESHOLD_PCT, limit:int=100):
        now = datetime.now(timezone.utc)
        day = now.astimezone(NY).date().isoformat()
        discovered, diag = await _sip_movers(core, limit)
        con = _db()
        top = {}
        for row in con.execute('SELECT symbol,MIN(rank) best_rank,MIN(captured_at) first_seen FROM signal_journal WHERE trade_date=? AND strategy_version=? GROUP BY symbol',(day,STRATEGY_VERSION)).fetchall():
            top[row['symbol']] = {'rank':int(row['best_rank']),'first_seen':row['first_seen']}
        movers = [x for x in discovered if x['move_pct'] >= threshold_pct]
        saved = 0
        missed = []
        eligible_movers = 0
        eligible_overlap = 0
        excluded = {}
        verified_count = 0
        sql = '''INSERT OR REPLACE INTO missed_movers(trade_date,symbol,observed_at,move_pct,price,volume,was_top10,top10_best_rank,strategy_version,features,premarket_gap_pct,premarket_volume,premarket_high,premarket_low,premarket_last,first_seen_top10,discovery_source,verification_feed,verified,asset_name,instrument_type,eligible_common_stock,asset_status,tradable,asset_attributes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
        for item in movers[:max(1,min(limit,50))]:
            symbol = item['symbol']
            asset = await _asset(core, symbol)
            itype = _instrument(asset, symbol)
            eligible = _eligible(asset, itype)
            hit = top.get(symbol)
            if eligible:
                eligible_movers += 1
                if hit:
                    eligible_overlap += 1
            else:
                excluded[itype] = excluded.get(itype, 0) + 1
            snap = await _iex_snapshot(core, symbol)
            verified = bool(snap)
            if verified:
                verified_count += 1
            pm = {}
            if verified and eligible:
                pm = await _premarket(core, symbol, day)
            prev = _f((snap or {}).get('prevDailyBar',{}).get('c'))
            pm_last = pm.get('last')
            pmgap = ((pm_last / prev) - 1) * 100 if pm_last and prev else None
            attrs = (asset or {}).get('attributes') or []
            features = {'point_in_time_rule':'SIP discovers outcome movers; asset reference classifies instrument; only active tradable common/ordinary equity counts in stock capture rate','sip_mover':item['raw'],'asset':asset,'iex_snapshot':snap,'premarket':pm}
            values = (day,symbol,now.isoformat(),item['move_pct'],item['price'],_f((snap or {}).get('dailyBar',{}).get('v')),1 if hit else 0,hit['rank'] if hit else None,STRATEGY_VERSION,json.dumps(features,ensure_ascii=False),pmgap,pm.get('volume'),pm.get('high'),pm.get('low'),pm_last,hit['first_seen'] if hit else None,'alpaca_sip_screener',core.ALPACA_FEED,1 if verified else 0,(asset or {}).get('name'),itype,1 if eligible else 0,(asset or {}).get('status'),1 if bool((asset or {}).get('tradable')) else 0,json.dumps(attrs))
            con.execute(sql, values)
            saved += 1
            if eligible and not hit:
                range_pct = None
                if pm.get('high') and pm.get('low'):
                    range_pct = round((pm['high'] / pm['low'] - 1) * 100, 2)
                missed.append({'symbol':symbol,'name':(asset or {}).get('name'),'move_pct':round(item['move_pct'],2),'instrument_type':itype,'verified_iex':verified,'overnight_halted':'overnight_halted' in attrs,'premarket_gap_pct':round(pmgap,2) if pmgap is not None else None,'premarket_volume':pm.get('volume'),'premarket_range_pct':range_pct})
        con.commit()
        con.close()
        eligible_missed = max(0, eligible_movers - eligible_overlap)
        capture_rate = round(eligible_overlap / eligible_movers * 100, 1) if eligible_movers else None
        return {'ok':True,'trade_date':day,'threshold_pct':threshold_pct,'raw_market_movers':len(movers),'eligible_stock_movers':eligible_movers,'eligible_top10_overlap':eligible_overlap,'eligible_false_negatives':eligible_missed,'eligible_capture_rate_pct':capture_rate,'excluded_instruments':excluded,'verified_iex':verified_count,'missed':missed[:25],'saved':saved,'strategy_version':STRATEGY_VERSION,'discovery_source':'alpaca_sip_screener','discovery_diag':diag,'verification_feed':core.ALPACA_FEED,'point_in_time':True}

    @app.get('/api/learning/missed-movers/summary')
    async def missed_summary(days:int=30):
        con = _db()
        rows = con.execute('''SELECT trade_date,COUNT(*) raw_movers,SUM(CASE WHEN eligible_common_stock=1 THEN 1 ELSE 0 END) eligible_movers,SUM(CASE WHEN eligible_common_stock=1 AND was_top10=1 THEN 1 ELSE 0 END) captured,SUM(CASE WHEN eligible_common_stock=1 AND was_top10=0 THEN 1 ELSE 0 END) missed,SUM(CASE WHEN eligible_common_stock=0 THEN 1 ELSE 0 END) excluded,AVG(CASE WHEN eligible_common_stock=1 AND was_top10=0 THEN premarket_gap_pct END) missed_avg_pm_gap,AVG(CASE WHEN eligible_common_stock=1 AND was_top10=0 THEN premarket_volume END) missed_avg_pm_volume FROM missed_movers WHERE strategy_version=? GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?''',(STRATEGY_VERSION,max(1,min(days,365)))).fetchall()
        con.close()
        out = [dict(r) for r in rows]
        eligible = sum(int(x['eligible_movers'] or 0) for x in out)
        captured = sum(int(x['captured'] or 0) for x in out)
        return {'ok':True,'days':len(out),'eligible_movers':eligible,'captured':captured,'missed':eligible-captured,'capture_rate_pct':round(captured/eligible*100,1) if eligible else None,'daily':out,'strategy_version':STRATEGY_VERSION}
