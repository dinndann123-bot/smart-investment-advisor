import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# v6.6.4 diagnostic fix: NY trading-date alignment for bars + explicit feature telemetry.
try:
 import asyncio,httpx as _httpx,math,uuid,os
 from datetime import datetime,timezone,timedelta
 from zoneinfo import ZoneInfo
 from fastapi.responses import JSONResponse
 _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 STRATEGY_VERSION='strategy-learning-v6.6.4-ny-date-feature-fix';UNIVERSE_MODE='dynamic_alpaca_full_market_predictive_shortlist_v6_6_4';NY=ZoneInfo('America/New_York')
 _AK=(globals().get('ALPACA_KEY') or os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip();_AS=(globals().get('ALPACA_SECRET') or os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip();_AF=(globals().get('ALPACA_FEED') or os.getenv('ALPACA_FEED') or 'iex').strip()
 def _f(v,d=0.0):
  try:x=float(v);return x if math.isfinite(x) else d
  except:return d
 def _h():return {'APCA-API-KEY-ID':_AK,'APCA-API-SECRET-KEY':_AS}
 async def _assets():
  async with _httpx.AsyncClient(timeout=15) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=_h(),params={'asset_class':'us_equity','status':'active'})
  if r.status_code>=400:return []
  out=[]
  for a in r.json() or []:
   s=str(a.get('symbol') or '').upper().strip();ex=str(a.get('exchange') or '').upper();name=str(a.get('name') or '').lower()
   if s and a.get('tradable') and ex in {'NASDAQ','NYSE','AMEX','ARCA','BATS'} and not any(k in name for k in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):out.append({'ticker':s,'name':a.get('name'),'exchange':ex})
  return out
 async def _snapshots(symbols):
  found={};sem=asyncio.Semaphore(10)
  async with _httpx.AsyncClient(timeout=10) as c:
   async def one(chunk):
    async with sem:
     try:
      r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=_h(),params={'symbols':','.join(chunk),'feed':_AF})
      if r.status_code<400:found.update(r.json() or {})
     except:pass
   await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)))
  return found
 def _basic(meta,s):
  lt=s.get('latestTrade') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {};p=_f(lt.get('p'),_f(mb.get('c'),_f(db.get('c'))));prev=_f(pb.get('c'));vol=_f(db.get('v'));o=_f(db.get('o'));hi=_f(db.get('h'));lo=_f(db.get('l'));pv=_f(pb.get('v'))
  if not(p>0 and prev>0) or p<.5 or p*vol<250000:return None
  ch=(p/prev-1)*100;gap=(o/prev-1)*100 if o else 0;rp=(p-lo)/(hi-lo) if hi>lo else .5;vr=vol/pv if pv else 0
  return {**meta,'price':round(p,4),'prev_close':prev,'change':round(ch,2),'change_pct':round(ch,2),'day_volume':vol,'prev_day_volume':pv,'snapshot_volume_ratio':round(vr,2) if vr else None,'snapshot_gap_pct':round(gap,2),'snapshot_range_position':round(rp,3),'dollar_volume':round(p*vol,2),'market_timestamp':lt.get('t') or mb.get('t') or db.get('t'),'data_source':'Alpaca','data_feed':_AF,'data_verified':True,'stale':False}
 def _quick_rank(r):
  ch=_f(r.get('change_pct'));gap=_f(r.get('snapshot_gap_pct'));vr=_f(r.get('snapshot_volume_ratio'));rp=_f(r.get('snapshot_range_position'),.5);dv=_f(r.get('dollar_volume'));return min(math.log10(max(dv,1)),10)*3+min(vr,6)*5+max(0,min(rp,1))*8+max(0,min(ch,4))*2+max(0,min(gap,4))*1.2-max(ch-5,0)*14-max(gap-7,0)*9
 async def _bars(symbol,client,days=6):
  end=datetime.now(timezone.utc);start=end-timedelta(days=days)
  try:
   r=await client.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=_h(),params={'timeframe':'5Min','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':_AF,'adjustment':'split','limit':4500})
   return (r.json() or {}).get('bars') or [] if r.status_code<400 else []
  except:return []
 def _features(r,bars):
  now=datetime.now(timezone.utc);ny_now=now.astimezone(NY);today_ny=ny_now.date();byday={}
  for b in bars:
   try:t=datetime.fromisoformat(str(b.get('t')).replace('Z','+00:00'));z=t.astimezone(NY)
   except:continue
   byday.setdefault(z.date(),[]).append((z,b))
  todays=byday.get(today_ny,[]);prev=_f(r.get('prev_close'));pm=[(z,b) for z,b in todays if 240<=z.hour*60+z.minute<570]
  pmv=sum(_f(b.get('v')) for _,b in pm);pmh=max([_f(b.get('h')) for _,b in pm] or [0]);pml=min([_f(b.get('l'),1e99) for _,b in pm] or [0]);pv=sum(_f(b.get('v'))*_f(b.get('vw'),_f(b.get('c'))) for _,b in pm);pmvwap=pv/pmv if pmv else 0;firstpm=_f(pm[0][1].get('o')) if pm else 0;gap=(firstpm/prev-1)*100 if firstpm and prev else 0;curmin=ny_now.hour*60+ny_now.minute;hist=[]
  for d,arr in byday.items():
   if d==today_ny:continue
   v=sum(_f(b.get('v')) for z,b in arr if 240<=z.hour*60+z.minute<=curmin)
   if v>0:hist.append(v)
  baseline=sum(hist[-5:])/len(hist[-5:]) if hist else 0;todaycum=sum(_f(b.get('v')) for _,b in todays);rvol=todaycum/baseline if baseline else 0;price=_f(r.get('price'));distv=(price/pmvwap-1)*100 if pmvwap else 0;disth=(price/pmh-1)*100 if pmh else 0;day_low=min([_f(b.get('l'),price) for _,b in todays] or [price]);day_high=max([_f(b.get('h'),price) for _,b in todays] or [price]);used=(price-day_low)/(day_high-day_low)*100 if day_high>day_low else 50
  r.update({'bars_count':len(bars),'today_bars_count':len(todays),'premarket_bars_count':len(pm),'premarket_volume':round(pmv),'premarket_high':round(pmh,4) if pmh else None,'premarket_low':round(pml,4) if pmh else None,'premarket_vwap':round(pmvwap,4) if pmvwap else None,'premarket_gap_pct':round(gap,2) if firstpm else None,'rvol':round(rvol,2) if rvol else None,'distance_from_pm_vwap_pct':round(distv,2) if pmvwap else None,'distance_from_pm_high_pct':round(disth,2) if pmh else None,'intraday_move_used_pct':round(used,1),'intraday_low':round(day_low,4),'intraday_high':round(day_high,4)});return r
 def _stage(r):
  ch=_f(r.get('change_pct'));gap=_f(r.get('premarket_gap_pct'),_f(r.get('snapshot_gap_pct')));rv=_f(r.get('rvol'));dv=_f(r.get('distance_from_pm_vwap_pct'));dh=_f(r.get('distance_from_pm_high_pct'));pmv=_f(r.get('premarket_volume'));used=_f(r.get('intraday_move_used_pct'),50)
  if ch>=9 or gap>=11 or dv>6 or dh>3.5 or (ch>=5 and used>=92):return 'already_extended'
  if rv>=1.2 and pmv>=30000 and -10<=dh<=.8 and -4<=dv<=4 and ch<7 and used<92:return 'pre_breakout'
  if .5<=ch<7 and rv>=1.3 and -2<=dh<=1.5 and dv<=4.5 and used<90:return 'early_breakout'
  return 'watch'
 def _rank(r):
  ch=_f(r.get('change_pct'));gap=_f(r.get('premarket_gap_pct'));rv=_f(r.get('rvol'));pmv=_f(r.get('premarket_volume'));dv=_f(r.get('distance_from_pm_vwap_pct'));dh=_f(r.get('distance_from_pm_high_pct'));used=_f(r.get('intraday_move_used_pct'),50);stage=_stage(r);score=30+min(max(rv-1,0),9)*4+min(pmv/100000,15)+(7 if -4<=dv<=4 else 0)+(8 if -10<=dh<=.8 else 0)+{'pre_breakout':28,'early_breakout':14,'watch':-25,'already_extended':-100}[stage]-max(ch-4,0)*7-max(gap-7,0)*5-max(used-85,0)*.8;return score,stage
 async def _scanner(top:int=10,candidates:int=40):
  generated=datetime.now(timezone.utc);scan_id=f"{generated.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";wanted=10 if top==10 else max(3,min(top,20));print(f'SCANNER_V664_START scan_id={scan_id} top={wanted} feed={_AF}',flush=True)
  if not(_AK and _AS):payload={'results':[],'error':'alpaca_not_configured'}
  else:
   assets=await _assets();sn=await _snapshots([a['ticker'] for a in assets]);pool=[]
   for a in assets:
    if sn.get(a['ticker']):
     r=_basic(a,sn[a['ticker']]);pool.append(r) if r else None
   pool.sort(key=_quick_rank,reverse=True);caps=[]
   for cap in (80,120,180):
    cap=min(cap,len(pool));caps.append(cap) if cap and cap not in caps else None
   enriched=[];seen=set();forward=[];watch=[];extended=[];sem=asyncio.Semaphore(24)
   async with _httpx.AsyncClient(timeout=7,limits=_httpx.Limits(max_connections=30,max_keepalive_connections=20)) as bc:
    async def one(r):
     async with sem:return _features(dict(r),await _bars(r['ticker'],bc))
    for cap in caps:
     batch=[r for r in pool[:cap] if r['ticker'] not in seen]
     rows=await asyncio.gather(*(one(r) for r in batch)) if batch else []
     for r in rows:
      seen.add(r['ticker']);enriched.append(r);rank,stage=_rank(r);r.update({'score':max(0,min(100,round(rank))),'forward_rank':round(rank,2),'breakout_stage':stage,'candidate_type':'prediction' if stage in {'pre_breakout','early_breakout'} else 'learning_observation','strategy_version':STRATEGY_VERSION,'scan_id':scan_id,'generated_at':generated.isoformat()});({'already_extended':extended,'watch':watch}.get(stage,forward)).append(r)
     forward.sort(key=lambda x:({'pre_breakout':2,'early_breakout':1}.get(x.get('breakout_stage'),0),x.get('forward_rank',-999)),reverse=True)
     sample=enriched[:3];diag=[{'t':x.get('ticker'),'bars':x.get('bars_count'),'today':x.get('today_bars_count'),'pmBars':x.get('premarket_bars_count'),'pmVol':x.get('premarket_volume'),'rvol':x.get('rvol'),'dh':x.get('distance_from_pm_high_pct'),'dv':x.get('distance_from_pm_vwap_pct'),'used':x.get('intraday_move_used_pct'),'stage':x.get('breakout_stage')} for x in sample]
     print(f'SCANNER_V664_EXPAND scan_id={scan_id} full_market={len(pool)} deep={len(enriched)} predictive={len(forward)} watch={len(watch)} extended={len(extended)} cap={cap} diag={diag}',flush=True)
     if len(forward)>=wanted:break
   watch.sort(key=lambda x:x.get('forward_rank',-999),reverse=True);extended.sort(key=lambda x:x.get('forward_rank',-999),reverse=True);sel=forward[:wanted]
   payload={'results':sel,'watch_observations':watch[:30],'extended_observations':extended[:30],'diagnostic_sample':enriched[:5],'feed':_AF,'data_source':'Alpaca','assets_scanned':len(assets),'full_market_ranked_count':len(pool),'deep_candidates':len(enriched),'forward_candidate_count':len(forward),'watch_observation_count':len(watch),'extended_observation_count':len(extended),'requested_top':wanted,'complete_top10':len(sel)>=wanted,'ranking_status':'predictive_only_ny_date_fixed','progressive_caps':caps}
  payload.update({'strategy_version':STRATEGY_VERSION,'scan_id':scan_id,'generated_at':generated.isoformat(),'universe_mode':UNIVERSE_MODE,'candidate_semantics':'predictive_prebreakout_or_earlybreakout_only','cache_policy':'no-store'});print(f"SCANNER_V664_DONE scan_id={scan_id} results={len(payload.get('results',[]))} predictive={payload.get('forward_candidate_count',0)} watch={payload.get('watch_observation_count',0)} extended={payload.get('extended_observation_count',0)} complete={payload.get('complete_top10')}",flush=True);return JSONResponse(payload,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION,'X-Scan-Id':scan_id})
 if _day_route:
  app.router.routes.remove(_day_route);app.add_api_route('/api/scanner/day',_scanner,methods=['GET'],name='scanner_day_v664');SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'strategy_version':STRATEGY_VERSION,'ny_trading_date_fix':True,'feature_diagnostics':True,'watch_excluded_from_top10':True,'deep_candidate_cap':180}
 else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as e:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(e).__name__}: {e}'}
try:
 import sys
 _core=sys.modules[__name__]
 from signal_journal import install_signal_journal
 from missed_movers_learning import install_missed_movers_learning
 from learning_comparison import install_learning_comparison
 install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core);LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':STRATEGY_VERSION,'universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
except Exception as e:LEARNING_ENGINE_STATUS={'installed':False,'error':f'{type(e).__name__}: {e}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
@app.get('/api/learning/status')
async def learning_status():return LEARNING_ENGINE_STATUS
