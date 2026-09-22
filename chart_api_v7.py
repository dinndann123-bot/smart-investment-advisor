"""Canonical chart API for v7. One market-data path, no UI/runtime patches."""
import os,re
from datetime import datetime,timezone,timedelta
import httpx
from fastapi import HTTPException

RANGES={
 '1D':('5Min',timedelta(days=2),600),
 '1W':('15Min',timedelta(days=9),700),
 '1M':('1Hour',timedelta(days=35),900),
 '3M':('1Day',timedelta(days=110),500),
 '1Y':('1Day',timedelta(days=380),700),
 '5Y':('1Week',timedelta(days=365*5+30),400),
}

def install_chart_api(app):
 key=(os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip()
 secret=(os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip()
 headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
 @app.get('/api/market/chart/{symbol}')
 async def chart(symbol:str,range:str='1D'):
  symbol=symbol.upper().strip(); range=range.upper().strip()
  if not re.fullmatch(r'[A-Z]{1,5}',symbol):raise HTTPException(400,'invalid symbol')
  if range not in RANGES:raise HTTPException(400,'invalid range')
  tf,delta,limit=RANGES[range]; now=datetime.now(timezone.utc)
  # SIP history on Basic must end outside the latest 15 minute embargo.
  end=now-timedelta(minutes=16); start=end-delta
  params={'timeframe':tf,'start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'adjustment':'split','feed':'sip','limit':limit,'sort':'asc'}
  url=f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
  async with httpx.AsyncClient(timeout=20) as c:r=await c.get(url,headers=headers,params=params)
  if r.status_code>=400:raise HTTPException(r.status_code,detail={'provider':'Alpaca','message':r.text[:300]})
  bars=(r.json() or {}).get('bars') or []
  points=[{'t':b.get('t'),'o':b.get('o'),'h':b.get('h'),'l':b.get('l'),'c':b.get('c'),'v':b.get('v')} for b in bars]
  return {'symbol':symbol,'range':range,'timeframe':tf,'points':points,'count':len(points),'source':'Alpaca','feed':'sip','delayed_minutes':16,'generated_at':now.isoformat(),'last_bar_at':points[-1]['t'] if points else None,'cache_policy':'no-store'}
 return chart
