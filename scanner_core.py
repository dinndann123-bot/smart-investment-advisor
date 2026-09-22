"""Local scanner core extracted from the stable v6.6.5/v6.6.6 runtime chain."""
import asyncio, math, os, re, uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi.responses import JSONResponse
NY=ZoneInfo('America/New_York'); STRATEGY_VERSION='strategy-learning-v6.6.8-local-premarket-diagnostics'
def install_local_scanner(app):
 key=(os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip(); secret=(os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip(); feed=(os.getenv('ALPACA_FEED') or 'iex').strip()
 def f(v,d=0.0):
  try:return float(v)
  except:return d
 def hdr():return {'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
 async def assets():
  async with httpx.AsyncClient(timeout=15) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=hdr(),params={'asset_class':'us_equity','status':'active'})
  out=[]
  if r.status_code<400:
   bad=('preferred','depositary share','depositary shares','warrant','rights','unit ',' units','note due','notes due')
   for a in r.json() or []:
    s=str(a.get('symbol') or '').upper(); ex=str(a.get('exchange') or '').upper(); n=str(a.get('name') or '').lower()
    if re.fullmatch(r'[A-Z]{1,5}',s) and not any(x in n for x in bad) and a.get('tradable') and ex in {'NASDAQ','NYSE','AMEX','ARCA','BATS'} and not any(x in n for x in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):out.append({'ticker':s,'name':a.get('name'),'exchange':ex})
  return out
 async def snaps(symbols):
  out={}; sem=asyncio.Semaphore(10)
  async with httpx.AsyncClient(timeout=10) as c:
   async def one(ch):
    async with sem:
     try:
      r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=hdr(),params={'symbols':','.join(ch),'feed':feed})
      if r.status_code<400:out.update(r.json() or {})
     except Exception:pass
   await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)))
  return out
 def basic(m,s):
  lt=s.get('latestTrade') or {}; mb=s.get('minuteBar') or {}; db=s.get('dailyBar') or {}; pb=s.get('prevDailyBar') or {}
  p=f(lt.get('p'),f(mb.get('c'),f(db.get('c')))); prev=f(pb.get('c')); vol=f(db.get('v')); pv=f(pb.get('v')); o=f(db.get('o')); hi=f(db.get('h')); lo=f(db.get('l'))
  if p<.5 or prev<=0:return None
  ch=(p/prev-1)*100; gap=(o/prev-1)*100 if o else ch; rp=(p-lo)/(hi-lo) if hi>lo else .5; vr=vol/pv if pv else 0
  return {**m,'price':round(p,4),'prev_close':prev,'change_pct':round(ch,2),'snapshot_gap_pct':round(gap,2),'day_volume':vol,'prev_day_volume':pv,'snapshot_volume_ratio':round(vr,3) if vr else None,'snapshot_range_position':round(rp,3),'day_open':o,'day_high':hi,'day_low':lo,'minute_volume':f(mb.get('v')),'market_timestamp':lt.get('t') or mb.get('t'),'data_source':'Alpaca','data_feed':feed}
 def qrank(r):
  ch=f(r.get('change_pct')); gap=f(r.get('snapshot_gap_pct')); vr=f(r.get('snapshot_volume_ratio')); rp=f(r.get('snapshot_range_position'),.5); dv=f(r.get('price'))*max(f(r.get('day_volume')),1)
  return min(math.log10(max(dv,1)),10)*3+min(vr,5)*8+rp*8+min(max(ch,0),4)*2-max(ch-6,0)*12-max(gap-9,0)*8
 async def bars(sym,c):
  end=datetime.now(timezone.utc); start=end-timedelta(days=8)
  try:
   r=await c.get(f'https://data.alpaca.markets/v2/stocks/{sym}/bars',headers=hdr(),params={'timeframe':'5Min','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':feed,'adjustment':'split','limit':5000})
   if r.status_code>=400:return [],f'HTTP_{r.status_code}'
   return (r.json() or {}).get('bars') or [],None
  except Exception as e:return [],type(e).__name__
 def enrich(r,bar_result):
  bs,bar_error=bar_result; now=datetime.now(timezone.utc).astimezone(NY); by={}
  for b in bs:
   try:z=datetime.fromisoformat(str(b.get('t')).replace('Z','+00:00')).astimezone(NY); by.setdefault(z.date(),[]).append((z,b))
   except Exception:pass
  todays=by.get(now.date(),[]); cur=now.hour*60+now.minute; session_start=240 if cur<570 else 570
  live=sum(f(b.get('v')) for z,b in todays if session_start<=z.hour*60+z.minute<=cur); hist=[]
  for d,a in sorted(by.items()):
   if d==now.date():continue
   v=sum(f(b.get('v')) for z,b in a if session_start<=z.hour*60+z.minute<=cur)
   if v>0:hist.append(v)
  baseline=sum(hist[-5:])/len(hist[-5:]) if hist else 0; raw=live/baseline if baseline else 0; reliable=bool(baseline>=1000 and live>0); rvol=min(raw,25.0) if raw>0 else 0
  highs=[f(b.get('h')) for z,b in todays if session_start<=z.hour*60+z.minute<=cur]; lows=[f(b.get('l')) for z,b in todays if session_start<=z.hour*60+z.minute<=cur and f(b.get('l'))>0]
  p=f(r.get('price')); lo=min(lows) if lows else f(r.get('day_low'),p); hi=max(highs) if highs else f(r.get('day_high'),p); used=(p-lo)/(hi-lo)*100 if hi>lo else 50; rp=max(0,min(1,(p-lo)/(hi-lo))) if hi>lo else .5
  latest5=f(todays[-1][1].get('v')) if todays else f(r.get('minute_volume')); elapsed=max((cur-session_start)/5,1); avg_min=baseline/elapsed if baseline else 0; burst=latest5/avg_min if avg_min else 0
  r.update({'bars_count':len(bs),'bars_error':bar_error,'today_bars_count':len(todays),'historical_days_with_volume':len(hist),'session_start_minute':session_start,'premarket_mode':cur<570,'session_live_volume':round(live),'rvol_raw':round(raw,3) if raw else None,'rvol':round(rvol,3) if rvol else None,'rvol_reliable':reliable,'rvol_capped':bool(raw>25),'intraday_move_used_pct':round(used,1),'minute_volume_burst':round(burst,2) if burst else None,'historical_baseline_volume':round(baseline) if baseline else None,'current_range_position':round(rp,3),'live_structure_source':'5min-bars-same-session-clock'}); return r
 def stage(r):
  if not r.get('rvol_reliable'):return 'watch'
  ch=f(r.get('change_pct'));rv=f(r.get('rvol'));used=f(r.get('intraday_move_used_pct'),50);rp=f(r.get('current_range_position'),.5);burst=f(r.get('minute_volume_burst'));gap=f(r.get('snapshot_gap_pct'))
  if ch>=10 or gap>=12 or (ch>=6 and used>=94):return 'already_extended'
  if rv>=1.15 and .55<=rp<=.90 and used<90 and ch<7:return 'pre_breakout'
  if .5<=ch<8 and rv>=1.2 and .65<=rp<=.94 and used<92 and (burst>=1.0 or burst==0):return 'early_breakout'
  return 'watch'
 def rank(r):
  st=stage(r);rv=f(r.get('rvol'));ch=f(r.get('change_pct'));rp=f(r.get('current_range_position'),.5);used=f(r.get('intraday_move_used_pct'),50);burst=f(r.get('minute_volume_burst'));score=35+min(max(rv-1,0),8)*6+rp*12+min(burst,5)*2+{'pre_breakout':25,'early_breakout':16,'watch':-20,'already_extended':-100}[st]-max(ch-5,0)*6-max(used-88,0)
  if r.get('rvol_capped'):score-=8
  return score,st
 async def scanner(top:int=10,candidates:int=40):
  ts=datetime.now(timezone.utc);sid=f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";wanted=10;print(f'LOCAL_SCANNER_START scan_id={sid} feed={feed}',flush=True)
  aa=await assets();ss=await snaps([x['ticker'] for x in aa]);pool=[]
  for a in aa:
   if a['ticker'] in ss:
    x=basic(a,ss[a['ticker']]); pool.append(x) if x else None
  pool.sort(key=qrank,reverse=True);pred=[];watch=[];ext=[];en=[];seen=set();sem=asyncio.Semaphore(24)
  async with httpx.AsyncClient(timeout=7,limits=httpx.Limits(max_connections=30,max_keepalive_connections=20)) as c:
   async def one(x):
    async with sem:return enrich(dict(x),await bars(x['ticker'],c))
   for cap in (80,120,180):
    batch=[x for x in pool[:min(cap,len(pool))] if x['ticker'] not in seen];rows=await asyncio.gather(*(one(x) for x in batch)) if batch else []
    for x in rows:
     seen.add(x['ticker']);en.append(x);sc,st=rank(x);x.update({'breakout_stage':st,'score':max(0,min(100,round(sc))),'forward_rank':round(sc,2),'candidate_type':'prediction' if st in {'pre_breakout','early_breakout'} else 'learning_observation','strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat()});({'already_extended':ext,'watch':watch}.get(st,pred)).append(x)
    pred.sort(key=lambda x:({'pre_breakout':2,'early_breakout':1}.get(x['breakout_stage'],0),x['forward_rank']),reverse=True);print(f'LOCAL_SCANNER_EXPAND scan_id={sid} deep={len(en)} predictive={len(pred)} watch={len(watch)} extended={len(ext)} cap={cap}',flush=True)
    if len(pred)>=wanted:break
  diag=sorted(en,key=lambda x:(f(x.get('rvol_raw')),-f(x.get('bars_count'))),reverse=True)[:10]
  for d in diag[:5]:print(f"MARKET_DATA_DIAG {d.get('ticker')} bars={d.get('bars_count')} err={d.get('bars_error')} today={d.get('today_bars_count')} hist={d.get('historical_days_with_volume')} livevol={d.get('session_live_volume')} baseline={d.get('historical_baseline_volume')} rvol={d.get('rvol_raw')} reliable={d.get('rvol_reliable')} px={d.get('price')} ts={d.get('market_timestamp')}",flush=True)
  sel=pred[:wanted];payload={'results':sel,'watch_observations':sorted(watch,key=lambda x:x['forward_rank'],reverse=True)[:30],'extended_observations':ext[:30],'diagnostic_sample':diag,'assets_scanned':len(aa),'snapshots_received':len(ss),'full_market_ranked_count':len(pool),'deep_candidates':len(en),'forward_candidate_count':len(pred),'requested_top':wanted,'complete_top10':len(sel)>=wanted,'strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat(),'data_source':'Alpaca','feed':feed,'ranking_status':'hybrid_live_predictive_only','candidate_semantics':'prebreakout_or_earlybreakout_only','cache_policy':'no-store','quality_guard':{'common_share_symbol_filter':True,'rvol_cap':25,'minimum_baseline_volume':1000,'unreliable_rvol_excluded_from_predictive':True,'premarket_same_clock_baseline':True}}
  print(f'LOCAL_SCANNER_DONE scan_id={sid} assets={len(aa)} snaps={len(ss)} results={len(sel)} predictive={len(pred)} complete={payload["complete_top10"]}',flush=True);return JSONResponse(payload,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION,'X-Scan-Id':sid})
 old=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 if old:app.router.routes.remove(old)
 app.add_api_route('/api/scanner/day',scanner,methods=['GET'],name='scanner_day_local');print('LOCAL_SCANNER_INSTALLED no_runtime_exec=true',flush=True);return scanner
