"""Canonical v8 market overview. Uses Alpaca stock proxies from the same market-data account.
No hard-coded prices and no UI fallback values. SPY/QQQ/DIA are explicitly labeled proxies;
VIX is unavailable unless a verified VIX-capable source is connected.
"""
import os, asyncio
from datetime import datetime, timezone, timedelta
import httpx

PROXIES=(('sp500','S&P 500','SPY'),('nasdaq','NASDAQ 100','QQQ'),('dow','DOW JONES','DIA'))

def install_market_indices(app):
 key=(os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip()
 secret=(os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip()
 headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
 async def one(client,ident,label,symbol):
  # Basic SIP history: deliberately outside latest 15-minute embargo.
  end=datetime.now(timezone.utc)-timedelta(minutes=16); start=end-timedelta(days=7)
  params={'timeframe':'1Day','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':'sip','adjustment':'split','limit':10,'sort':'asc'}
  r=await client.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=headers,params=params)
  if r.status_code>=400:return {'id':ident,'label':label,'symbol':symbol,'available':False,'error':f'provider_http_{r.status_code}'}
  bars=(r.json() or {}).get('bars') or []
  if not bars:return {'id':ident,'label':label,'symbol':symbol,'available':False,'error':'no_bars'}
  last=bars[-1]; prev=bars[-2] if len(bars)>1 else None; price=last.get('c'); change=((price-prev.get('c'))/prev.get('c')*100) if prev and prev.get('c') else None
  return {'id':ident,'label':label,'symbol':symbol,'available':True,'value':price,'change_pct':change,'timestamp':last.get('t'),'source':'Alpaca','feed':'sip','representation':'ETF proxy','delayed_minutes':16}
 @app.get('/api/market/overview')
 async def market_overview():
  async with httpx.AsyncClient(timeout=20) as c:items=await asyncio.gather(*(one(c,*p) for p in PROXIES))
  items.append({'id':'vix','label':'VIX','symbol':None,'available':False,'source':None,'representation':'index','reason':'No verified VIX-capable provider connected; no proxy is shown as VIX.'})
  return {'generated_at':datetime.now(timezone.utc).isoformat(),'items':items,'contract':'market-overview-v8','note':'Equity index cards use clearly labeled liquid ETF proxies; values are not presented as official index levels.'}
 return market_overview
