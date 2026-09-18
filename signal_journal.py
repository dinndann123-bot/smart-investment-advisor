import json, sqlite3
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
import httpx
from fastapi import HTTPException

NY=ZoneInfo('America/New_York')
DB=Path(__file__).resolve().parent/'signal_journal.sqlite3'

def _db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS signal_journal(id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT, captured_at TEXT, rank INTEGER, symbol TEXT, score REAL, price REAL, gap_pct REAL, rvol REAL, momentum_pct REAL, premarket_price REAL, premarket_gap_pct REAL, premarket_volume REAL, premarket_high REAL, premarket_low REAL, source TEXT, payload TEXT, UNIQUE(trade_date,symbol,captured_at))''')
    con.commit(); return con

def _f(v):
    try:return float(v)
    except:return None

async def _premarket(core,symbols):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET): return {}
    now=datetime.now(timezone.utc).astimezone(NY); day=now.date().isoformat()
    headers={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    out={}
    async with httpx.AsyncClient(timeout=25) as client:
        for s in symbols:
            try:
                r=await client.get(f'https://data.alpaca.markets/v2/stocks/{s}/bars',headers=headers,params={'timeframe':'1Min','start':f'{day}T04:00:00-04:00','end':f'{day}T09:30:00-04:00','limit':1000,'feed':core.ALPACA_FEED,'adjustment':'split','sort':'asc'})
                if r.status_code>=400: continue
                bars=(r.json() or {}).get('bars') or []
                if not bars: continue
                vol=sum(_f(b.get('v')) or 0 for b in bars); hi=max(_f(b.get('h')) or 0 for b in bars); lows=[_f(b.get('l')) for b in bars if (_f(b.get('l')) or 0)>0]; lo=min(lows) if lows else None; px=_f(bars[-1].get('c'))
                out[s]={'premarket_price':px,'premarket_volume':vol,'premarket_high':hi or None,'premarket_low':lo}
            except Exception: pass
    return out

def install_signal_journal(app,core):
    @app.post('/api/learning/capture-top10')
    async def capture_top10():
        route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
        if not route: raise HTTPException(503,'scanner unavailable')
        scan=await route.endpoint(top=10,candidates=200); rows=(scan or {}).get('results') or []
        now=datetime.now(timezone.utc); ny=now.astimezone(NY); pm=await _premarket(core,[str(x.get('ticker') or '').upper() for x in rows[:10]])
        con=_db(); saved=0
        for rank,x in enumerate(rows[:10],1):
            s=str(x.get('ticker') or '').upper(); p=pm.get(s,{})
            price=_f(x.get('price')); prev=None; change=_f(x.get('change'))
            if price and change is not None and change>-99: prev=price/(1+change/100)
            pmgap=((p.get('premarket_price')/prev)-1)*100 if p.get('premarket_price') and prev else None
            payload=dict(x); payload['premarket']=p
            con.execute('INSERT OR IGNORE INTO signal_journal(trade_date,captured_at,rank,symbol,score,price,gap_pct,rvol,momentum_pct,premarket_price,premarket_gap_pct,premarket_volume,premarket_high,premarket_low,source,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ny.date().isoformat(),now.isoformat(),rank,s,_f(x.get('score')),price,_f(x.get('gap_pct') if x.get('gap_pct') is not None else x.get('change')),_f(x.get('rvol')),_f(x.get('move_to_1000_pct') if x.get('move_to_1000_pct') is not None else x.get('change')),p.get('premarket_price'),pmgap,p.get('premarket_volume'),p.get('premarket_high'),p.get('premarket_low'),scan.get('source'),json.dumps(payload,ensure_ascii=False)))
            saved+=1
        con.commit(); con.close(); return {'ok':True,'saved':saved,'captured_at':now.isoformat(),'premarket_enriched':sum(1 for s in [str(x.get('ticker') or '').upper() for x in rows[:10]] if s in pm),'source':scan.get('source')}

    @app.get('/api/learning/journal')
    async def journal(limit:int=100):
        con=_db(); rows=[dict(r) for r in con.execute('SELECT * FROM signal_journal ORDER BY captured_at DESC, rank ASC LIMIT ?',(max(1,min(limit,500)),)).fetchall()]; con.close(); return {'ok':True,'rows':rows}
