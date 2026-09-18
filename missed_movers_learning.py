import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx

NY=ZoneInfo('America/New_York'); DB=Path(__file__).resolve().parent/'signal_journal.sqlite3'; STRATEGY_VERSION='strategy-learning-v2'; MOVE_THRESHOLD_PCT=8.0

def _f(v):
    try:return float(v)
    except:return None

def _db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS missed_movers(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_date TEXT,symbol TEXT,observed_at TEXT,move_pct REAL,price REAL,volume REAL,was_top10 INTEGER,top10_best_rank INTEGER,strategy_version TEXT,features TEXT,premarket_gap_pct REAL,premarket_volume REAL,premarket_high REAL,premarket_low REAL,premarket_last REAL,first_seen_top10 TEXT,discovery_source TEXT,verification_feed TEXT,verified INTEGER,UNIQUE(trade_date,symbol,strategy_version))''')
    existing={r[1] for r in con.execute('PRAGMA table_info(missed_movers)').fetchall()}
    for col,typ in {'premarket_gap_pct':'REAL','premarket_volume':'REAL','premarket_high':'REAL','premarket_low':'REAL','premarket_last':'REAL','first_seen_top10':'TEXT','discovery_source':'TEXT','verification_feed':'TEXT','verified':'INTEGER'}.items():
        if col not in existing:con.execute(f'ALTER TABLE missed_movers ADD COLUMN {col} {typ}')
    con.commit(); return con

async def _sip_movers(core,limit=100):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):return []
    h={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    out=[]
    async with httpx.AsyncClient(timeout=30) as c:
        for kind in ('gainers',):
            r=await c.get(f'https://data.alpaca.markets/v1beta1/screener/stocks/movers',headers=h,params={'top':max(20,min(limit,100))})
            if r.status_code>=400:continue
            data=r.json() or {}
            for x in data.get(kind) or []:
                sym=str(x.get('symbol') or '').upper(); pct=_f(x.get('percent_change')); price=_f(x.get('price')); change=_f(x.get('change'))
                if sym and pct is not None:out.append({'symbol':sym,'move_pct':pct,'price':price,'change':change,'raw':x})
    seen=set(); uniq=[]
    for x in sorted(out,key=lambda z:z['move_pct'],reverse=True):
        if x['symbol'] not in seen:seen.add(x['symbol']);uniq.append(x)
    return uniq

async def _iex_snapshot(core,symbol):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):return None
    h={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    async with httpx.AsyncClient(timeout=15) as c:r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot',headers=h,params={'feed':core.ALPACA_FEED})
    if r.status_code>=400:return None
    data=r.json() or {}; return data if data else None

async def _premarket(core,symbol,day):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):return {}
    h={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET};p={'timeframe':'1Min','start':f'{day}T04:00:00-04:00','end':f'{day}T09:30:00-04:00','limit':10000,'feed':core.ALPACA_FEED,'adjustment':'split','sort':'asc'}
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=h,params=p)
    bars=((r.json() or {}).get('bars') or []) if r.status_code<400 else []
    if not bars:return {}
    lows=[_f(b.get('l')) for b in bars if _f(b.get('l')) is not None]; highs=[_f(b.get('h')) for b in bars if _f(b.get('h')) is not None]
    return {'last':_f(bars[-1].get('c')),'volume':sum(_f(b.get('v')) or 0 for b in bars),'high':max(highs) if highs else None,'low':min(lows) if lows else None,'bars':len(bars)}

def install_missed_movers_learning(app,core):
    @app.post('/api/learning/missed-movers')
    async def missed_movers(threshold_pct:float=MOVE_THRESHOLD_PCT,limit:int=100):
        now=datetime.now(timezone.utc);day=now.astimezone(NY).date().isoformat();discovered=await _sip_movers(core,limit);con=_db();top={}
        for r in con.execute('SELECT symbol,MIN(rank) best_rank,MIN(captured_at) first_seen FROM signal_journal WHERE trade_date=? AND strategy_version=? GROUP BY symbol',(day,STRATEGY_VERSION)).fetchall():top[r['symbol']]={'rank':int(r['best_rank']),'first_seen':r['first_seen']}
        movers=[x for x in discovered if x['move_pct']>=threshold_pct];saved=0;missed=[];verified_count=0;overlap=0
        for x in movers[:max(1,min(limit,100))]:
            symbol=x['symbol']; snap=await _iex_snapshot(core,symbol); verified=bool(snap); verified_count+=1 if verified else 0;hit=top.get(symbol);overlap+=1 if hit else 0;pm=await _premarket(core,symbol,day) if verified else {}; prev=_f((snap or {}).get('prevDailyBar',{}).get('c')); pmgap=((pm.get('last')/prev)-1)*100 if pm.get('last') and prev else None
            features={'point_in_time_rule':'SIP screener discovers broad-market outcome movers; IEX only verifies observability and supplies premarket features','sip_mover':x['raw'],'iex_snapshot':snap,'premarket':pm}
            con.execute('INSERT OR REPLACE INTO missed_movers(trade_date,symbol,observed_at,move_pct,price,volume,was_top10,top10_best_rank,strategy_version,features,premarket_gap_pct,premarket_volume,premarket_high,premarket_low,premarket_last,first_seen_top10,discovery_source,verification_feed,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(day,symbol,now.isoformat(),x['move_pct'],x['price'],_f((snap or {}).get('dailyBar',{}).get('v')),1 if hit else 0,hit['rank'] if hit else None,STRATEGY_VERSION,json.dumps(features,ensure_ascii=False),pmgap,pm.get('volume'),pm.get('high'),pm.get('low'),pm.get('last'),hit['first_seen'] if hit else None,'alpaca_sip_screener',core.ALPACA_FEED,1 if verified else 0));saved+=1
            if not hit:missed.append({'symbol':symbol,'move_pct':round(x['move_pct'],2),'verified_iex':verified,'premarket_gap_pct':round(pmgap,2) if pmgap is not None else None,'premarket_volume':pm.get('volume'),'premarket_range_pct':round((pm['high']/pm['low']-1)*100,2) if pm.get('high') and pm.get('low') else None})
        con.commit();con.close();return {'ok':True,'trade_date':day,'threshold_pct':threshold_pct,'market_movers':len(movers),'top10_overlap':overlap,'false_negatives':len(missed),'verified_iex':verified_count,'missed':missed[:25],'saved':saved,'strategy_version':STRATEGY_VERSION,'discovery_source':'alpaca_sip_screener','verification_feed':core.ALPACA_FEED,'point_in_time':True}

    @app.get('/api/learning/missed-movers/summary')
    async def missed_summary(days:int=30):
        con=_db();rows=con.execute('''SELECT trade_date,COUNT(*) movers,SUM(CASE WHEN was_top10=0 THEN 1 ELSE 0 END) missed,SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) verified,AVG(move_pct) avg_move,MAX(move_pct) max_move,AVG(CASE WHEN was_top10=0 THEN premarket_gap_pct END) missed_avg_pm_gap,AVG(CASE WHEN was_top10=0 THEN premarket_volume END) missed_avg_pm_volume FROM missed_movers WHERE strategy_version=? GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?''',(STRATEGY_VERSION,max(1,min(days,365)))).fetchall();con.close();out=[dict(r) for r in rows];total=sum(int(x['movers'] or 0) for x in out);missed=sum(int(x['missed'] or 0) for x in out)
        return {'ok':True,'days':len(out),'movers':total,'missed':missed,'capture_rate_pct':round((total-missed)/total*100,1) if total else None,'daily':out,'strategy_version':STRATEGY_VERSION}
