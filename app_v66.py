import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# v6.6.5 Hybrid scanner: live Alpaca snapshot is authoritative when current-day 5m bars are unavailable.
try:
 import asyncio,httpx as _httpx,math,uuid,os
 from datetime import datetime,timezone,timedelta
 from zoneinfo import ZoneInfo
 from fastapi.responses import JSONResponse
 _old=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 STRATEGY_VERSION='strategy-learning-v6.6.5-hybrid-live';NY=ZoneInfo('America/New_York')
 AK=(globals().get('ALPACA_KEY') or os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip();AS=(globals().get('ALPACA_SECRET') or os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip();AF=(globals().get('ALPACA_FEED') or os.getenv('ALPACA_FEED') or 'iex').strip()
 def f(v,d=0.0):
  try:return float(v)
  except:return d
 def hdr():return {'APCA-API-KEY-ID':AK,'APCA-API-SECRET-KEY':AS}
 async def assets():
  async with _httpx.AsyncClient(timeout=15) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=hdr(),params={'asset_class':'us_equity','status':'active'})
  out=[]
  if r.status_code<400:
   for a in r.json() or []:
    s=str(a.get('symbol') or '').upper();ex=str(a.get('exchange') or '').upper();n=str(a.get('name') or '').lower()
    if s and a.get('tradable') and ex in {'NASDAQ','NYSE','AMEX','ARCA','BATS'} and not any(x in n for x in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):out.append({'ticker':s,'name':a.get('name'),'exchange':ex})
  return out
 async def snaps(symbols):
  out={};sem=asyncio.Semaphore(10)
  async with _httpx.AsyncClient(timeout=10) as c:
   async def one(ch):
    async with sem:
     try:
      r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=hdr(),params={'symbols':','.join(ch),'feed':AF})
      if r.status_code<400:out.update(r.json() or {})
     except:pass
   await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)))
  return out
 def basic(m,s):
  lt=s.get('latestTrade') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {};p=f(lt.get('p'),f(mb.get('c'),f(db.get('c'))));prev=f(pb.get('c'));vol=f(db.get('v'));pv=f(pb.get('v'));o=f(db.get('o'));hi=f(db.get('h'));lo=f(db.get('l'))
  if p<.5 or prev<=0 or p*vol<250000:return None
  ch=(p/prev-1)*100;gap=(o/prev-1)*100 if o else 0;rp=(p-lo)/(hi-lo) if hi>lo else .5;vr=vol/pv if pv else 0
  return {**m,'price':round(p,4),'prev_close':prev,'change_pct':round(ch,2),'snapshot_gap_pct':round(gap,2),'day_volume':vol,'prev_day_volume':pv,'snapshot_volume_ratio':round(vr,3) if vr else None,'snapshot_range_position':round(rp,3),'day_open':o,'day_high':hi,'day_low':lo,'minute_open':f(mb.get('o')),'minute_high':f(mb.get('h')),'minute_low':f(mb.get('l')),'minute_close':f(mb.get('c')),'minute_volume':f(mb.get('v')),'market_timestamp':lt.get('t') or mb.get('t'),'data_source':'Alpaca','data_feed':AF}
 def qrank(r):
  ch=f(r.get('change_pct'));gap=f(r.get('snapshot_gap_pct'));vr=f(r.get('snapshot_volume_ratio'));rp=f(r.get('snapshot_range_position'),.5);dv=f(r.get('price'))*f(r.get('day_volume'));return min(math.log10(max(dv,1)),10)*3+min(vr,5)*8+rp*8+min(max(ch,0),4)*2-max(ch-6,0)*12-max(gap-9,0)*8
 async def bars(sym,c):
  end=datetime.now(timezone.utc);start=end-timedelta(days=7)
  try:
   r=await c.get(f'https://data.alpaca.markets/v2/stocks/{sym}/bars',headers=hdr(),params={'timeframe':'5Min','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':AF,'adjustment':'split','limit':5000})
   return (r.json() or {}).get('bars') or [] if r.status_code<400 else []
  except:return []
 def enrich(r,bs):
  now=datetime.now(timezone.utc).astimezone(NY);by={}
  for b in bs:
   try:z=datetime.fromisoformat(str(b.get('t')).replace('Z','+00:00')).astimezone(NY);by.setdefault(z.date(),[]).append((z,b))
   except:pass
  todays=by.get(now.date(),[]);cur=now.hour*60+now.minute;hist=[]
  for d,a in by.items():
   if d==now.date():continue
   v=sum(f(b.get('v')) for z,b in a if 570<=z.hour*60+z.minute<=cur)
   if v>0:hist.append(v)
  baseline=sum(hist[-5:])/len(hist[-5:]) if hist else 0
  # Live fallback uses today's cumulative snapshot volume. This keeps RVOL live even if today's 5m bars lag/miss.
  livevol=f(r.get('day_volume'));rvol=livevol/baseline if baseline else f(r.get('snapshot_volume_ratio'))
  p=f(r.get('price'));lo=f(r.get('day_low'),p);hi=f(r.get('day_high'),p);used=(p-lo)/(hi-lo)*100 if hi>lo else 50
  # Snapshot range position + minute acceleration provide current structure without pretending unavailable PM bars exist.
  rp=f(r.get('snapshot_range_position'),.5);mv=f(r.get('minute_volume'));avg_min=(baseline/max((cur-570)/5,1)) if baseline else 0;minute_burst=mv/avg_min if avg_min else 0
  r.update({'bars_count':len(bs),'today_bars_count':len(todays),'rvol':round(rvol,2) if rvol else None,'intraday_move_used_pct':round(used,1),'minute_volume_burst':round(minute_burst,2) if minute_burst else None,'live_structure_source':'snapshot+minuteBar','historical_baseline_volume':round(baseline) if baseline else None,'current_range_position':round(rp,3)});return r
 def stage(r):
  ch=f(r.get('change_pct'));rv=f(r.get('rvol'));used=f(r.get('intraday_move_used_pct'),50);rp=f(r.get('current_range_position'),.5);burst=f(r.get('minute_volume_burst'));gap=f(r.get('snapshot_gap_pct'))
  if ch>=10 or gap>=12 or (ch>=6 and used>=94):return 'already_extended'
  # Pre-breakout: abnormal participation, price in constructive upper-middle range, but not yet at an exhausted high.
  if rv>=1.15 and .55<=rp<=.90 and used<90 and ch<7:return 'pre_breakout'
  # Early breakout: momentum has started and minute volume confirms, while move-used remains controlled.
  if .5<=ch<8 and rv>=1.2 and .65<=rp<=.94 and used<92 and (burst>=1.0 or burst==0):return 'early_breakout'
  return 'watch'
 def rank(r):
  st=stage(r);rv=f(r.get('rvol'));ch=f(r.get('change_pct'));rp=f(r.get('current_range_position'),.5);used=f(r.get('intraday_move_used_pct'),50);burst=f(r.get('minute_volume_burst'));score=35+min(max(rv-1,0),8)*6+rp*12+min(burst,5)*2+{'pre_breakout':25,'early_breakout':16,'watch':-20,'already_extended':-100}[st]-max(ch-5,0)*6-max(used-88,0);return score,st
 async def scanner(top:int=10,candidates:int=40):
  ts=datetime.now(timezone.utc);sid=f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";wanted=10
  print(f'SCANNER_V665_START scan_id={sid} feed={AF}',flush=True)
  aa=await assets();ss=await snaps([x['ticker'] for x in aa]);pool=[]
  for a in aa:
   if a['ticker'] in ss:
    x=basic(a,ss[a['ticker']]);pool.append(x) if x else None
  pool.sort(key=qrank,reverse=True);pred=[];watch=[];ext=[];en=[];seen=set();sem=asyncio.Semaphore(24)
  async with _httpx.AsyncClient(timeout=7,limits=_httpx.Limits(max_connections=30,max_keepalive_connections=20)) as c:
   async def one(x):
    async with sem:return enrich(dict(x),await bars(x['ticker'],c))
   for cap in (80,120,180):
    batch=[x for x in pool[:min(cap,len(pool))] if x['ticker'] not in seen];rows=await asyncio.gather(*(one(x) for x in batch)) if batch else []
    for x in rows:
     seen.add(x['ticker']);en.append(x);sc,st=rank(x);x.update({'breakout_stage':st,'score':max(0,min(100,round(sc))),'forward_rank':round(sc,2),'candidate_type':'prediction' if st in {'pre_breakout','early_breakout'} else 'learning_observation','strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat()});({'already_extended':ext,'watch':watch}.get(st,pred)).append(x)
    pred.sort(key=lambda x:({'pre_breakout':2,'early_breakout':1}.get(x['breakout_stage'],0),x['forward_rank']),reverse=True)
    diag=[{'t':x['ticker'],'rvol':x.get('rvol'),'rp':x.get('current_range_position'),'used':x.get('intraday_move_used_pct'),'burst':x.get('minute_volume_burst'),'todayBars':x.get('today_bars_count'),'stage':x.get('breakout_stage')} for x in en[:5]]
    print(f'SCANNER_V665_EXPAND scan_id={sid} deep={len(en)} predictive={len(pred)} watch={len(watch)} extended={len(ext)} cap={cap} diag={diag}',flush=True)
    if len(pred)>=wanted:break
  sel=pred[:wanted];payload={'results':sel,'watch_observations':sorted(watch,key=lambda x:x['forward_rank'],reverse=True)[:30],'extended_observations':ext[:30],'diagnostic_sample':en[:5],'assets_scanned':len(aa),'full_market_ranked_count':len(pool),'deep_candidates':len(en),'forward_candidate_count':len(pred),'requested_top':wanted,'complete_top10':len(sel)>=wanted,'strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat(),'data_source':'Alpaca','feed':AF,'ranking_status':'hybrid_live_predictive_only','candidate_semantics':'prebreakout_or_earlybreakout_only','cache_policy':'no-store'}
  print(f'SCANNER_V665_DONE scan_id={sid} results={len(sel)} predictive={len(pred)} watch={len(watch)} extended={len(ext)} complete={payload["complete_top10"]}',flush=True);return JSONResponse(payload,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION,'X-Scan-Id':sid})
 if _old:app.router.routes.remove(_old)
 app.add_api_route('/api/scanner/day',scanner,methods=['GET'],name='scanner_day_v665')
 SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'strategy_version':STRATEGY_VERSION,'hybrid_live':True,'watch_excluded_from_top10':True,'deep_candidate_cap':180}
except Exception as e:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(e).__name__}: {e}'}

try:
 import sys
 _core=sys.modules[__name__]
 from signal_journal import install_signal_journal
 from missed_movers_learning import install_missed_movers_learning
 from learning_comparison import install_learning_comparison
 install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
except Exception:pass

@app.get('/api/learning/status')
async def learning_status():return {'installed':True,'strategy_version':STRATEGY_VERSION,'universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
