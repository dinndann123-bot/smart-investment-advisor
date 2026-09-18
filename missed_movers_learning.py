import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx

NY=ZoneInfo('America/New_York')
DB=Path(__file__).resolve().parent/'signal_journal.sqlite3'
STRATEGY_VERSION='strategy-learning-v2'
MOVE_THRESHOLD_PCT=8.0

def _f(v):
    try:return float(v)
    except:return None

def _db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS missed_movers(id INTEGER PRIMARY KEY AUTOINCREMENT,trade_date TEXT,symbol TEXT,observed_at TEXT,move_pct REAL,price REAL,volume REAL,was_top10 INTEGER,top10_best_rank INTEGER,strategy_version TEXT,features TEXT,UNIQUE(trade_date,symbol,strategy_version))''')
    con.commit(); return con

async def _snapshots(core):
    if not (core.ALPACA_KEY and core.ALPACA_SECRET):return {}
    headers={'APCA-API-KEY-ID':core.ALPACA_KEY,'APCA-API-SECRET-KEY':core.ALPACA_SECRET}
    params={'feed':core.ALPACA_FEED}
    async with httpx.AsyncClient(timeout=40) as client:
        r=await client.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=headers,params=params)
        if r.status_code>=400:return {}
        return r.json() or {}

def _move(snap):
    daily=snap.get('dailyBar') or {}; prev=snap.get('prevDailyBar') or {}; latest=snap.get('latestTrade') or {}
    price=_f(latest.get('p')) or _f(daily.get('c')); prev_close=_f(prev.get('c')); vol=_f(daily.get('v'))
    pct=((price/prev_close)-1)*100 if price and prev_close else None
    return price,prev_close,vol,pct

def install_missed_movers_learning(app,core):
    @app.post('/api/learning/missed-movers')
    async def missed_movers(threshold_pct:float=MOVE_THRESHOLD_PCT,limit:int=100):
        now=datetime.now(timezone.utc); ny=now.astimezone(NY); day=ny.date().isoformat(); snaps=await _snapshots(core)
        con=_db(); top={}
        for r in con.execute('SELECT symbol,MIN(rank) best_rank FROM signal_journal WHERE trade_date=? AND strategy_version=? GROUP BY symbol',(day,STRATEGY_VERSION)).fetchall(): top[r['symbol']]=int(r['best_rank'])
        movers=[]
        for symbol,snap in snaps.items():
            price,prev,vol,pct=_move(snap)
            if pct is None or pct<threshold_pct:continue
            movers.append((pct,symbol,price,vol,snap))
        movers.sort(reverse=True,key=lambda x:x[0]); saved=0
        for pct,symbol,price,vol,snap in movers[:max(1,min(limit,500))]:
            rank=top.get(symbol); features={'daily_bar':snap.get('dailyBar'),'prev_daily_bar':snap.get('prevDailyBar'),'minute_bar':snap.get('minuteBar'),'latest_trade':snap.get('latestTrade'),'latest_quote':snap.get('latestQuote')}
            before=con.total_changes
            con.execute('INSERT OR REPLACE INTO missed_movers(trade_date,symbol,observed_at,move_pct,price,volume,was_top10,top10_best_rank,strategy_version,features) VALUES(?,?,?,?,?,?,?,?,?,?)',(day,symbol,now.isoformat(),pct,price,vol,1 if rank else 0,rank,STRATEGY_VERSION,json.dumps(features,ensure_ascii=False)))
            if con.total_changes>before:saved+=1
        con.commit(); false_neg=[{'symbol':s,'move_pct':round(p,2),'price':pr,'volume':v} for p,s,pr,v,_ in movers if s not in top]
        con.close(); return {'ok':True,'trade_date':day,'threshold_pct':threshold_pct,'market_movers':len(movers),'top10_overlap':sum(1 for _,s,_,_,_ in movers if s in top),'false_negatives':len(false_neg),'missed':false_neg[:25],'saved':saved,'strategy_version':STRATEGY_VERSION}

    @app.get('/api/learning/missed-movers/summary')
    async def missed_summary(days:int=30):
        con=_db(); rows=con.execute('''SELECT trade_date,COUNT(*) movers,SUM(CASE WHEN was_top10=0 THEN 1 ELSE 0 END) missed,AVG(move_pct) avg_move,MAX(move_pct) max_move FROM missed_movers WHERE strategy_version=? GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?''',(STRATEGY_VERSION,max(1,min(days,365)))).fetchall(); con.close()
        out=[dict(r) for r in rows]
        total=sum(int(x['movers'] or 0) for x in out); missed=sum(int(x['missed'] or 0) for x in out)
        return {'ok':True,'days':len(out),'movers':total,'missed':missed,'capture_rate_pct':round((total-missed)/total*100,1) if total else None,'daily':out,'strategy_version':STRATEGY_VERSION}
