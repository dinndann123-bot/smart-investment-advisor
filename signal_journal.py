import json, sqlite3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import httpx
from fastapi import HTTPException

NY=ZoneInfo('America/New_York'); DB=Path(__file__).resolve().parent/'signal_journal.sqlite3'; STRATEGY_VERSION='strategy-learning-v2'
OUTCOME_COLS={'evaluated_at':'TEXT','peak_price':'REAL','trough_price':'REAL','close_price':'REAL','mfe_pct':'REAL','mae_pct':'REAL','close_return_pct':'REAL','minutes_to_peak':'REAL','minutes_to_trough':'REAL','exit_price':'REAL','exit_return_pct':'REAL','outcome_status':'TEXT','outcome_bars':'INTEGER','strategy_version':'TEXT','session':'TEXT','feature_snapshot':'TEXT','first_bar_time':'TEXT','peak_time':'TEXT','trough_time':'TEXT','entry_bar_price':'REAL','entry_slippage_pct':'REAL','drawdown_from_peak_pct':'REAL','evaluation_feed':'TEXT'}

def _db():
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;con.execute('''CREATE TABLE IF NOT EXISTS signal_journal(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_date TEXT,captured_at TEXT,rank INTEGER,symbol TEXT,score REAL,price REAL,gap_pct REAL,rvol REAL,momentum_pct REAL,premarket_price REAL,premarket_gap_pct REAL,premarket_volume REAL,premarket_high REAL,premarket_low REAL,source TEXT,payload TEXT,UNIQUE(trade_date,symbol,captured_at))''');existing={r[1] for r in con.execute('PRAGMA table_info(signal_journal)').fetchall()}
    for col,typ in OUTCOME_COLS.items():
        if col not in existing:con.execute(f'ALTER TABLE signal_journal ADD COLUMN {col} {typ}')
    con.execute('CREATE INDEX IF NOT EXISTS idx_signal_trade_version ON signal_journal(trade_date,strategy_version,captured_at)');con.commit();return con

def _f(v):
    try:return float(v)
    except:return None

def _iso(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except:return None

def _session(ny):
    m=ny.hour*60+ny.minute
    return 'premarket' if 240<=m<570 else ('regular' if 570<=m<960 else 'afterhours')

def _features(x,p,g):return {'score':_f(x.get('score')),'price':_f(x.get('price')),'gap_pct':_f(x.get('gap_pct') if x.get('gap_pct') is not None else x.get('change')),'rvol':_f(x.get('rvol')),'momentum_pct':_f(x.get('move_to_1000_pct') if x.get('move_to_1000_pct') is not None else x.get('change')),'premarket_price':p.get('premarket_price'),'premarket_gap_pct':g,'premarket_volume':p.get('premarket_volume'),'premarket_high':p.get('premarket_high'),'premarket_low':p.get('premarket_low')}

async def _bars(core,client,symbol,start,end,feed=None):
    if not(core.ALPACA_KEY and core.ALPACA_SECRET):return [],'no_credentials'
    h={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET};p={'timeframe':'1Min','start':start,'end':end,'limit':10000,'feed':feed or core.ALPACA_FEED,'adjustment':'split','sort':'asc'}
    try:r=await client.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=h,params=p)
    except Exception as e:return [],f'request_{type(e).__name__}'
    if r.status_code>=400:return [],f'http_{r.status_code}'
    return (r.json() or {}).get('bars') or [],None

def _valid_bars_after_signal(bars,captured):
    out=[]
    for b in bars or []:
        if _f(b.get('h')) is None or _f(b.get('l')) is None or _f(b.get('c')) is None:continue
        t=_iso(b.get('t'))
        if t and t>=captured:out.append(b)
    return out

async def _premarket(core,symbols):
    if not(core.ALPACA_KEY and core.ALPACA_SECRET):return {}
    now=datetime.now(timezone.utc).astimezone(NY);day=now.date().isoformat();out={}
    async with httpx.AsyncClient(timeout=25) as c:
        for s in symbols:
            bars,_=await _bars(core,c,s,f'{day}T04:00:00-04:00',f'{day}T09:30:00-04:00')
            if not bars:continue
            lows=[_f(b.get('l')) for b in bars if (_f(b.get('l')) or 0)>0];out[s]={'premarket_price':_f(bars[-1].get('c')),'premarket_volume':sum(_f(b.get('v')) or 0 for b in bars),'premarket_high':max(_f(b.get('h')) or 0 for b in bars) or None,'premarket_low':min(lows) if lows else None}
    return out

async def _evaluate_rows(core,rows):
    results=[];failures=[];now=datetime.now(timezone.utc)
    if not(core.ALPACA_KEY and core.ALPACA_SECRET):return results,[{'symbol':r.get('symbol'),'reason':'no_credentials'} for r in rows]
    async with httpx.AsyncClient(timeout=30) as c:
        for row in rows:
            sym=row.get('symbol')
            try:
                captured=_iso(row.get('captured_at'));scanner=_f(row.get('price'))
                if not captured:failures.append({'symbol':sym,'reason':'invalid_capture_time'});continue
                if not scanner or scanner<=0:failures.append({'symbol':sym,'reason':'invalid_scanner_price'});continue
                ny=captured.astimezone(NY);op=ny.replace(hour=9,minute=30,second=0,microsecond=0);cl=ny.replace(hour=16,minute=0,second=0,microsecond=0);start=max(op,ny.replace(second=0,microsecond=0));safe=now-timedelta(seconds=10);startu=start.astimezone(timezone.utc);closeu=cl.astimezone(timezone.utc);end=min(safe,closeu)
                if start>=cl:failures.append({'symbol':sym,'reason':'capture_after_regular_close'});continue
                if end<=startu:failures.append({'symbol':sym,'reason':'no_elapsed_bar_window'});continue
                primary_feed=str(getattr(core,'ALPACA_FEED','iex') or 'iex').lower();raw,err=await _bars(core,c,sym,startu.isoformat(),end.isoformat(),primary_feed);used_feed=primary_feed;bars=_valid_bars_after_signal(raw,captured)
                if err:failures.append({'symbol':sym,'reason':err,'feed':primary_feed});continue
                if not bars and primary_feed!='sip':
                    sip,serr=await _bars(core,c,sym,startu.isoformat(),end.isoformat(),'sip')
                    if not serr:
                        bars=_valid_bars_after_signal(sip,captured)
                        if bars:used_feed='sip'
                if not bars:
                    wide_start=max(op,start-timedelta(minutes=30)).astimezone(timezone.utc);wide_end=min(closeu,end+timedelta(minutes=5));sip,serr=await _bars(core,c,sym,wide_start.isoformat(),wide_end.isoformat(),'sip')
                    if not serr:
                        filtered=[]
                        for b in _valid_bars_after_signal(sip,captured):
                            t=_iso(b.get('t'))
                            if t and t<=end:filtered.append(b)
                        if filtered:bars=filtered;used_feed='sip_retry'
                if not bars:failures.append({'symbol':sym,'reason':'coverage_missing_no_valid_minute_bars','feeds_tried':[primary_feed,'sip','sip_retry'] if primary_feed!='sip' else ['sip','sip_retry']});continue
                first=bars[0];entry=_f(first.get('c')) or scanner;peak=max(bars,key=lambda b:_f(b.get('h')));trough=min(bars,key=lambda b:_f(b.get('l')));last=bars[-1];pp=_f(peak.get('h'));tp=_f(trough.get('l'));cp=_f(last.get('c'));ft=_iso(first.get('t'));pt=_iso(peak.get('t'));tt=_iso(trough.get('t'));complete=now>=closeu
                results.append({'id':row['id'],'symbol':sym,'peak_price':pp,'trough_price':tp,'close_price':cp,'mfe_pct':(pp/entry-1)*100,'mae_pct':(tp/entry-1)*100,'close_return_pct':(cp/entry-1)*100,'minutes_to_peak':(pt-captured).total_seconds()/60 if pt else None,'minutes_to_trough':(tt-captured).total_seconds()/60 if tt else None,'exit_price':cp,'exit_return_pct':(cp/entry-1)*100,'outcome_status':'complete' if complete else 'partial','outcome_bars':len(bars),'evaluated_at':now.isoformat(),'first_bar_time':ft.isoformat() if ft else None,'peak_time':pt.isoformat() if pt else None,'trough_time':tt.isoformat() if tt else None,'entry_bar_price':entry,'entry_slippage_pct':(entry/scanner-1)*100,'drawdown_from_peak_pct':(cp/pp-1)*100 if pp and cp else None,'evaluation_feed':used_feed})
            except Exception as e:failures.append({'symbol':sym,'reason':f'exception_{type(e).__name__}'})
    return results,failures

def install_signal_journal(app,core):
    @app.post('/api/learning/capture-top10')
    async def capture_top10(force:bool=False):
        route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
        if not route:raise HTTPException(503,'scanner unavailable')
        now=datetime.now(timezone.utc);ny=now.astimezone(NY);session=_session(ny);con=_db();last=con.execute('SELECT captured_at FROM signal_journal WHERE trade_date=? AND strategy_version=? ORDER BY captured_at DESC LIMIT 1',(ny.date().isoformat(),STRATEGY_VERSION)).fetchone()
        if last and not force:
            prev=_iso(last['captured_at'])
            if prev and(now-prev).total_seconds()<300:con.close();return {'ok':True,'saved':0,'skipped':'capture_interval','strategy_version':STRATEGY_VERSION,'session':session,'next_in_seconds':int(300-(now-prev).total_seconds())}
        scan=await route.endpoint(top=10,candidates=200);rows=(scan or {}).get('results') or [];syms=[str(x.get('ticker') or '').upper() for x in rows[:10]];pm=await _premarket(core,syms);saved=0
        for rank,x in enumerate(rows[:10],1):
            s=str(x.get('ticker') or '').upper();p=pm.get(s,{});price=_f(x.get('price'));change=_f(x.get('change'));prev=price/(1+change/100) if price and change is not None and change>-99 else None;g=((p.get('premarket_price')/prev)-1)*100 if p.get('premarket_price') and prev else None;f=_features(x,p,g);payload=dict(x);payload['premarket']=p;payload['strategy_version']=STRATEGY_VERSION;payload['session']=session;before=con.total_changes
            con.execute('INSERT OR IGNORE INTO signal_journal(trade_date,captured_at,rank,symbol,score,price,gap_pct,rvol,momentum_pct,premarket_price,premarket_gap_pct,premarket_volume,premarket_high,premarket_low,source,payload,strategy_version,session,feature_snapshot) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ny.date().isoformat(),now.isoformat(),rank,s,f['score'],price,f['gap_pct'],f['rvol'],f['momentum_pct'],p.get('premarket_price'),g,p.get('premarket_volume'),p.get('premarket_high'),p.get('premarket_low'),scan.get('source'),json.dumps(payload,ensure_ascii=False),STRATEGY_VERSION,session,json.dumps(f,ensure_ascii=False)))
            if con.total_changes>before:saved+=1
        con.commit();con.close();return {'ok':True,'saved':saved,'captured_at':now.isoformat(),'premarket_enriched':sum(1 for s in syms if s in pm),'source':scan.get('source'),'strategy_version':STRATEGY_VERSION,'session':session}

    @app.post('/api/learning/evaluate')
    async def evaluate(limit:int=100):
        con=_db();raw=con.execute("SELECT * FROM signal_journal WHERE outcome_status IS NULL OR outcome_status!='complete' ORDER BY captured_at ASC LIMIT ?",(max(1,min(limit,300)),)).fetchall();rows=[dict(r) for r in raw];results,failures=await _evaluate_rows(core,rows)
        for x in results:con.execute('UPDATE signal_journal SET evaluated_at=?,peak_price=?,trough_price=?,close_price=?,mfe_pct=?,mae_pct=?,close_return_pct=?,minutes_to_peak=?,minutes_to_trough=?,exit_price=?,exit_return_pct=?,outcome_status=?,outcome_bars=?,first_bar_time=?,peak_time=?,trough_time=?,entry_bar_price=?,entry_slippage_pct=?,drawdown_from_peak_pct=?,evaluation_feed=? WHERE id=?',(x['evaluated_at'],x['peak_price'],x['trough_price'],x['close_price'],x['mfe_pct'],x['mae_pct'],x['close_return_pct'],x['minutes_to_peak'],x['minutes_to_trough'],x['exit_price'],x['exit_return_pct'],x['outcome_status'],x['outcome_bars'],x['first_bar_time'],x['peak_time'],x['trough_time'],x['entry_bar_price'],x['entry_slippage_pct'],x['drawdown_from_peak_pct'],x['evaluation_feed'],x['id']))
        con.commit();con.close();return {'ok':True,'requested':len(rows),'evaluated':len(results),'complete':sum(x['outcome_status']=='complete' for x in results),'partial':sum(x['outcome_status']=='partial' for x in results),'feeds':{'iex':sum(x.get('evaluation_feed')=='iex' for x in results),'sip':sum(x.get('evaluation_feed')=='sip' for x in results),'sip_retry':sum(x.get('evaluation_feed')=='sip_retry' for x in results)},'failures':failures,'strategy_version':STRATEGY_VERSION}

    @app.get('/api/learning/journal')
    async def journal(limit:int=100):
        con=_db();rows=[dict(r) for r in con.execute('SELECT * FROM signal_journal ORDER BY captured_at DESC,rank ASC LIMIT ?',(max(1,min(limit,500)),)).fetchall()];con.close();return {'ok':True,'rows':rows,'strategy_version':STRATEGY_VERSION}

    @app.get('/api/learning/summary')
    async def summary():
        con=_db();r=con.execute("SELECT COUNT(*) n,SUM(CASE WHEN outcome_status='complete' THEN 1 ELSE 0 END) complete,AVG(CASE WHEN outcome_status IS NOT NULL THEN mfe_pct END) avg_mfe,AVG(CASE WHEN outcome_status IS NOT NULL THEN mae_pct END) avg_mae,AVG(CASE WHEN outcome_status IS NOT NULL THEN close_return_pct END) avg_close,AVG(CASE WHEN outcome_status IS NOT NULL THEN premarket_gap_pct END) avg_pm_gap,AVG(CASE WHEN outcome_status IS NOT NULL THEN minutes_to_peak END) avg_minutes_to_peak,AVG(CASE WHEN outcome_status IS NOT NULL THEN entry_slippage_pct END) avg_entry_slippage,AVG(CASE WHEN outcome_status IS NOT NULL THEN drawdown_from_peak_pct END) avg_drawdown_from_peak,SUM(CASE WHEN evaluation_feed='iex' THEN 1 ELSE 0 END) eval_iex,SUM(CASE WHEN evaluation_feed='sip' THEN 1 ELSE 0 END) eval_sip,SUM(CASE WHEN evaluation_feed='sip_retry' THEN 1 ELSE 0 END) eval_sip_retry FROM signal_journal WHERE strategy_version=?",(STRATEGY_VERSION,)).fetchone();con.close();return {'ok':True,**dict(r),'strategy_version':STRATEGY_VERSION}
