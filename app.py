import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Live Discovery v6.5: snapshot-first full-market discovery with explicit
# scanner telemetry so production logs prove which route/source actually ran.
try:
 import asyncio,httpx as _httpx,math,uuid,os
 from datetime import datetime,timezone,timedelta
 from fastapi.responses import JSONResponse
 _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 STRATEGY_VERSION='strategy-learning-v6.5-snapshot-first'
 UNIVERSE_MODE='dynamic_alpaca_snapshot_first_v6_5'
 _AK=(globals().get('ALPACA_KEY') or os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip()
 _AS=(globals().get('ALPACA_SECRET') or os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip()
 _AF=(globals().get('ALPACA_FEED') or os.getenv('ALPACA_FEED') or 'iex').strip()
 def _f(v,d=0.0):
  try:
   x=float(v);return x if math.isfinite(x) else d
  except:return d
 def _h():return {'APCA-API-KEY-ID':_AK,'APCA-API-SECRET-KEY':_AS}
 async def _assets():
  async with _httpx.AsyncClient(timeout=15) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=_h(),params={'asset_class':'us_equity','status':'active'})
  if r.status_code>=400:return []
  out=[]
  for a in r.json() or []:
   s=str(a.get('symbol') or '').upper().strip();ex=str(a.get('exchange') or '').upper();name=str(a.get('name') or '').lower()
   if not s or not a.get('tradable') or ex not in {'NASDAQ','NYSE','AMEX','ARCA','BATS'}:continue
   if any(k in name for k in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):continue
   out.append({'ticker':s,'name':a.get('name'),'exchange':ex})
  return out
 async def _snapshots(symbols):
  found={};sem=asyncio.Semaphore(8)
  async def one(chunk):
   async with sem:
    try:
     async with _httpx.AsyncClient(timeout=10) as c:r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=_h(),params={'symbols':','.join(chunk),'feed':_AF})
     if r.status_code<400:found.update(r.json() or {})
    except:pass
  await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)));return found
 def _basic(meta,s):
  lt=s.get('latestTrade') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {};p=_f(lt.get('p'),_f(mb.get('c'),_f(db.get('c'))));prev=_f(pb.get('c'));vol=_f(db.get('v'))
  if not(p>0 and prev>0) or p<0.5 or p*vol<250000:return None
  ch=(p/prev-1)*100
  return {**meta,'price':round(p,4),'prev_close':prev,'change':round(ch,2),'change_pct':round(ch,2),'day_volume':vol,'dollar_volume':round(p*vol,2),'market_timestamp':lt.get('t') or mb.get('t') or db.get('t'),'data_source':'Alpaca','data_feed':_AF,'data_verified':True,'stale':False}
 def _quick_rank(r):
  ch=_f(r.get('change_pct'));dv=_f(r.get('dollar_volume'));extension=max(abs(ch)-8,0)*8
  return min(abs(ch),8)*5+min(math.log10(max(dv,1)),10)*3-extension
 async def _bars(symbol,days=8):
  end=datetime.now(timezone.utc);start=end-timedelta(days=days)
  try:
   async with _httpx.AsyncClient(timeout=8) as c:r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=_h(),params={'timeframe':'5Min','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':_AF,'adjustment':'split','limit':6000})
   return (r.json() or {}).get('bars') or [] if r.status_code<400 else []
  except:return []
 def _features(r,bars):
  now=datetime.now(timezone.utc);today=now.date();byday={}
  for b in bars:
   try:t=datetime.fromisoformat(str(b.get('t')).replace('Z','+00:00'))
   except:continue
   byday.setdefault(t.date(),[]).append((t,b))
  todays=byday.get(today,[]);prev=_f(r.get('prev_close'));pm=[]
  try:
   from zoneinfo import ZoneInfo
   ny=ZoneInfo('America/New_York')
   for t,b in todays:
    z=t.astimezone(ny);m=z.hour*60+z.minute
    if 240<=m<570:pm.append((t,b))
  except:pass
  pmv=sum(_f(b.get('v')) for _,b in pm);pmh=max([_f(b.get('h')) for _,b in pm] or [0]);pml=min([_f(b.get('l'),1e99) for _,b in pm] or [0]);pv=sum(_f(b.get('v'))*_f(b.get('vw'),_f(b.get('c'))) for _,b in pm);pmvwap=pv/pmv if pmv else 0;firstpm=_f(pm[0][1].get('o')) if pm else 0;gap=(firstpm/prev-1)*100 if firstpm and prev else 0;hist=[]
  try:
   from zoneinfo import ZoneInfo
   ny=ZoneInfo('America/New_York');cur=now.astimezone(ny);curmin=cur.hour*60+cur.minute
   for d,arr in byday.items():
    if d==today:continue
    v=sum(_f(b.get('v')) for t,b in arr if 240<=t.astimezone(ny).hour*60+t.astimezone(ny).minute<=curmin)
    if v>0:hist.append(v)
  except:pass
  baseline=(sum(hist[-5:])/len(hist[-5:])) if hist else 0;todaycum=sum(_f(b.get('v')) for _,b in todays);rvol=todaycum/baseline if baseline else 0;price=_f(r.get('price'));distv=(price/pmvwap-1)*100 if pmvwap else 0;disth=(price/pmh-1)*100 if pmh else 0
  r.update({'premarket_volume':round(pmv),'premarket_high':round(pmh,4) if pmh else None,'premarket_low':round(pml,4) if pml else None,'premarket_vwap':round(pmvwap,4) if pmvwap else None,'premarket_gap_pct':round(gap,2) if firstpm else None,'rvol':round(rvol,2) if rvol else None,'distance_from_pm_vwap_pct':round(distv,2) if pmvwap else None,'distance_from_pm_high_pct':round(disth,2) if pmh else None});return r
 def _stage(r):
  ch=_f(r.get('change_pct'));rv=_f(r.get('rvol'));dv=_f(r.get('distance_from_pm_vwap_pct'));dh=_f(r.get('distance_from_pm_high_pct'));pmv=_f(r.get('premarket_volume'))
  if ch>=12 or dv>8 or dh>5:return 'already_extended'
  if ch>=5 or (rv>=2 and dh>=-2):return 'early_breakout'
  if rv>=1.25 and pmv>=50000 and -10<=dh<=0 and -4<=dv<=4:return 'pre_breakout'
  return 'watch'
 def _rank(r):
  ch=_f(r.get('change_pct'));gap=_f(r.get('premarket_gap_pct'));rv=_f(r.get('rvol'));pmv=_f(r.get('premarket_volume'));dv=_f(r.get('distance_from_pm_vwap_pct'));dh=_f(r.get('distance_from_pm_high_pct'));stage=_stage(r)
  participation=min(max(rv-1,0),9)*4+min(pmv/100000,15);structure=(5 if -4<=dv<=4 else 0)+(6 if -10<=dh<=0 else 0);stage_adj={'pre_breakout':14,'early_breakout':5,'watch':0,'already_extended':-28}[stage];extension=max(ch-6,0)*3.2+max(gap-10,0)*2
  return 30+participation+min(max(gap,0),7)*1.5+structure+stage_adj-extension,stage
 async def _scanner(top:int=10,candidates:int=40):
  generated=datetime.now(timezone.utc);scan_id=f"{generated.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";wanted=10 if top==10 else max(3,min(top,20))
  print(f'SCANNER_V65_START scan_id={scan_id} top={wanted} candidates={candidates} feed={_AF}',flush=True)
  if not(_AK and _AS):payload={'results':[],'error':'alpaca_not_configured'}
  else:
   assets=await _assets();sn=await _snapshots([a['ticker'] for a in assets]);pool=[]
   for a in assets:
    if sn.get(a['ticker']):
     r=_basic(a,sn[a['ticker']])
     if r:pool.append(r)
   pool.sort(key=_quick_rank,reverse=True);shortlist=pool[:max(30,min(int(candidates or 40),60))]
   print(f'SCANNER_SCORE source=alpaca_{_AF}_full_market assets={len(assets)} snapshots={len(sn)} rows={len(pool)} deep={len(shortlist)}',flush=True)
   sem=asyncio.Semaphore(20);enriched=[]
   async def one(r):
    async with sem:enriched.append(_features(r,await _bars(r['ticker'])))
   await asyncio.gather(*(one(r) for r in shortlist));extended=[];forward=[]
   for r in enriched:
    rank,stage=_rank(r);r.update({'score':max(0,min(100,round(rank))),'forward_rank':round(rank,2),'breakout_stage':stage,'candidate_type':'prediction' if stage!='already_extended' else 'learning_observation','prediction_status':stage,'strategy_version':STRATEGY_VERSION,'scan_id':scan_id,'generated_at':generated.isoformat(),'universe_mode':UNIVERSE_MODE});(extended if stage=='already_extended' else forward).append(r)
   forward.sort(key=lambda x:x.get('forward_rank',-999),reverse=True);extended.sort(key=lambda x:x.get('forward_rank',-999),reverse=True);sel=forward[:wanted]
   payload={'results':sel,'extended_observations':extended[:20],'feed':_AF,'data_source':'Alpaca','assets_scanned':len(assets),'snapshot_candidates':len(pool),'deep_candidates':len(shortlist),'enriched_candidates':len(enriched),'forward_candidate_count':len(forward),'extended_observation_count':len(extended),'requested_top':wanted,'complete_top10':len(sel)>=wanted,'ranking_status':'snapshot_first_forward_only','full_market':True,'note_he':'v6.5: סריקת snapshot מהירה על השוק, ניתוח bars עמוק ל-shortlist, ו-Top 10 forward בלבד.'}
  payload.update({'strategy_version':STRATEGY_VERSION,'scan_id':scan_id,'generated_at':generated.isoformat(),'server_timestamp':generated.isoformat(),'universe_mode':UNIVERSE_MODE,'candidate_semantics':'snapshot_first_forward_predictions','cache_policy':'no-store'})
  print(f"SCANNER_V65_DONE scan_id={scan_id} results={len(payload.get('results',[]))} error={payload.get('error','none')}",flush=True)
  return JSONResponse(payload,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0','X-Scanner-Version':STRATEGY_VERSION,'X-Scan-Id':scan_id})
 if _day_route:
  app.router.routes.remove(_day_route);app.add_api_route('/api/scanner/day',_scanner,methods=['GET'],name='scanner_day_v65')
  SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'route_rebound':True,'mode':UNIVERSE_MODE,'strategy_version':STRATEGY_VERSION,'target_count':10,'snapshot_first':True,'deep_candidate_cap':60,'extended_backfill':False}
 else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as e:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(e).__name__}: {e}'}
try:
 import sys
 _core=sys.modules[__name__]
 from signal_journal import install_signal_journal
 from missed_movers_learning import install_missed_movers_learning
 from learning_comparison import install_learning_comparison
 install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
 LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':STRATEGY_VERSION,'universe_alignment':SCANNER_UNIVERSE_ALIGNMENT,'feature_comparison':True}
except Exception as e:LEARNING_ENGINE_STATUS={'installed':False,'error':f'{type(e).__name__}: {e}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
@app.get('/api/learning/status')
async def learning_status():return LEARNING_ENGINE_STATUS
