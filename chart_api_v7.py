"""Canonical chart API for v7. One market-data path, no UI/runtime patches."""
import asyncio,math,os,re
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException

NY=ZoneInfo('America/New_York')

def _number(value):
 try:
  number=float(value)
  return number if math.isfinite(number) else None
 except (TypeError,ValueError):return None

def _market_session(ny):
 minute=ny.hour*60+ny.minute
 if minute<240 or minute>=1200:return 'closed'
 if minute<570:return 'premarket'
 if minute<960:return 'regular'
 return 'afterhours'

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
  tf,delta,limit=RANGES[range]; now=datetime.now(timezone.utc);ny=now.astimezone(NY);minute=ny.hour*60+ny.minute
  regular=570<=minute<960
  configured=(os.getenv('ALPACA_FEED') or 'iex').strip().lower()
  live_feed='sip' if configured=='sip' else 'iex'
  feed=live_feed if regular and range=='1D' else 'sip'
  delayed_minutes=0 if regular and range=='1D' else 16
  end=now-timedelta(minutes=delayed_minutes); start=end-delta
  params={'timeframe':tf,'start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'adjustment':'split','feed':feed,'limit':limit,'sort':'asc'}
  url=f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
  async with httpx.AsyncClient(timeout=20) as c:r=await c.get(url,headers=headers,params=params)
  if r.status_code>=400:raise HTTPException(r.status_code,detail={'provider':'Alpaca','message':r.text[:300]})
  bars=(r.json() or {}).get('bars') or []
  points=[{'t':b.get('t'),'o':b.get('o'),'h':b.get('h'),'l':b.get('l'),'c':b.get('c'),'v':b.get('v')} for b in bars]
  return {'symbol':symbol,'range':range,'timeframe':tf,'points':points,'count':len(points),'source':'Alpaca','feed':feed,'session':_market_session(ny),'delayed_minutes':delayed_minutes,'generated_at':now.isoformat(),'last_bar_at':points[-1]['t'] if points else None,'cache_policy':'no-store'}

 @app.get('/api/market/quote/{symbol}')
 async def market_quote(symbol:str):
  """Return a timestamped quote and never label a prior-session price as live."""
  symbol=symbol.upper().strip()
  if not re.fullmatch(r'[A-Z]{1,5}',symbol):raise HTTPException(400,'invalid symbol')
  now=datetime.now(timezone.utc);ny=now.astimezone(NY);session=_market_session(ny)
  configured=(os.getenv('ALPACA_FEED') or 'iex').strip().lower()
  feed='delayed_sip' if session in {'premarket','afterhours'} else ('sip' if configured=='sip' else 'iex')
  delay=15 if feed=='delayed_sip' else 0
  url=f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot'
  async with httpx.AsyncClient(timeout=15) as client:
   response=await client.get(url,headers=headers,params={'feed':feed})
  if response.status_code>=400:
   raise HTTPException(response.status_code,detail={'provider':'Alpaca','feed':feed,'message':response.text[:240]})
  snapshot=response.json() or {};trade=snapshot.get('latestTrade') or {};quote=snapshot.get('latestQuote') or {};minute=snapshot.get('minuteBar') or {};daily=snapshot.get('dailyBar') or {};previous=snapshot.get('prevDailyBar') or {}

  def parse_time(value):
   try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)
   except Exception:return None
  trade_time=parse_time(trade.get('t'));quote_time=parse_time(quote.get('t'));minute_time=parse_time(minute.get('t'))
  trade_price=_number(trade.get('p'));bid=_number(quote.get('bp'));ask=_number(quote.get('ap'))
  quote_mid=(bid+ask)/2 if bid is not None and bid>0 and ask is not None and ask>=bid else None
  quote_only=bool(quote_time and (not trade_time or quote_time>trade_time))
  timestamp=quote_time if quote_only else trade_time
  price=quote_mid if quote_only else trade_price
  price_source='latest_quote_midpoint' if quote_only else 'latest_trade'
  if (not timestamp or not price or price<=0) and minute_time:
   timestamp=minute_time;price=_number(minute.get('c'));price_source='minute_bar_close'
  age=(now-timestamp).total_seconds() if timestamp else None
  max_age=20*60 if delay else 180
  today=timestamp.astimezone(NY).date()==ny.date() if timestamp else False
  if session=='closed':state='market_closed' if price else 'unavailable'
  elif session=='premarket' and ny.hour*60+ny.minute<240+delay+1 and not today:state='waiting_for_delayed_feed'
  elif not price or not timestamp:state='no_current_trade'
  elif not today:state='previous_session'
  elif age is not None and -60<=age<=max_age:state='current_delayed' if delay else 'current'
  elif age is not None and age < -60:state='clock_skew'
  else:state='stale'
  valid=state in {'current','current_delayed','market_closed'}
  previous_close=_number(previous.get('c'))
  change=((price/previous_close-1)*100) if valid and price and previous_close else None
  return {'symbol':symbol,'price':round(price,4) if valid and price else None,'last_observed_price':round(price,4) if price else None,
          'previous_close':round(previous_close,4) if previous_close else None,'change_percent':round(change,3) if change is not None else None,
          'price_timestamp':timestamp.isoformat() if timestamp else None,'trade_timestamp':trade_time.isoformat() if trade_time else None,
          'quote_timestamp':quote_time.isoformat() if quote_time else None,'price_source':price_source if price else None,
          'source':'Alpaca','feed':feed,'session':session,'data_delay_minutes':delay,
          'freshness':{'state':state,'age_seconds':round(age,1) if age is not None else None,'max_age_seconds':max_age,
                       'timestamp_is_today':today,'usable_as_current_price':valid},'generated_at':now.isoformat(),'cache_policy':'no-store'}
 @app.get('/api/premarket/bars/{symbol}')
 async def premarket_bars(symbol:str):
  symbol=symbol.upper().strip()
  if not re.fullmatch(r'[A-Z]{1,5}',symbol):raise HTTPException(400,'invalid symbol')
  now=datetime.now(timezone.utc);market_now=now-timedelta(minutes=16);ny=market_now.astimezone(NY)
  start_ny=ny.replace(hour=4,minute=0,second=0,microsecond=0)
  if ny<start_ny:
   return {'symbol':symbol,'status':'waiting','bars':[],'provider':'Alpaca SIP delayed','feed':'sip','delayed_minutes':16,'generated_at':now.isoformat()}
  params={'timeframe':'5Min','start':start_ny.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),'end':market_now.isoformat().replace('+00:00','Z'),'adjustment':'split','feed':'sip','limit':1000,'sort':'asc'}
  bars_url=f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
  snap_url=f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot'
  async with httpx.AsyncClient(timeout=20) as c:
   bars_response,snapshot_response=await asyncio.gather(c.get(bars_url,headers=headers,params=params),c.get(snap_url,headers=headers,params={'feed':'delayed_sip'}))
  if bars_response.status_code>=400:raise HTTPException(bars_response.status_code,detail={'provider':'Alpaca','message':bars_response.text[:300]})
  raw=(bars_response.json() or {}).get('bars') or []
  bars=[{'t':b.get('t'),'o':b.get('o'),'h':b.get('h'),'l':b.get('l'),'c':b.get('c'),'v':b.get('v')} for b in raw]
  snapshot=snapshot_response.json() if snapshot_response.status_code<400 else {}
  previous_close=(snapshot.get('prevDailyBar') or {}).get('c')
  price=bars[-1]['c'] if bars else None
  change=(price/previous_close-1)*100 if price and previous_close else None
  last_at=bars[-1]['t'] if bars else None
  return {'symbol':symbol,'status':'delayed' if bars else 'no_trades','bars':bars,'quote':{'price':price,'previous_close':previous_close,'change_percent':change},'provider':'Alpaca SIP delayed','feed':'sip','delayed_minutes':16,'generated_at':now.isoformat(),'freshness':{'state':'delayed','last_bar_at':last_at},'last_bar_at':last_at,'cache_policy':'no-store'}
 return {'chart':chart,'quote':market_quote,'premarket_bars':premarket_bars}
