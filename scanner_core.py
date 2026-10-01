"""Local scanner core: session-aware snapshots + historical SIP bars."""
import asyncio, math, os, re, uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi.responses import JSONResponse
NY=ZoneInfo('America/New_York'); STRATEGY_VERSION='strategy-learning-v6.9-balanced-forward-catalyst'
def install_local_scanner(app):
 key=(os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY') or '').strip(); secret=(os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_SECRET') or '').strip(); regular_feed=(os.getenv('ALPACA_FEED') or 'iex').strip()
 def f(v,d=0.0):
  try:return float(v)
  except:return d
 def hdr():return {'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
 def parse_ts(v):
  try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(NY)
  except:return None
 def session(now):
  m=now.hour*60+now.minute
  if 240<=m<570:return 'premarket'
  if 570<=m<960:return 'regular'
  if 960<=m<1200:return 'afterhours'
  return 'closed'
 def scan_feed(now):
  # Extended hours use consolidated delayed SIP on the Basic plan. At the
  # regular-session boundary switch deterministically to a live-capable feed.
  if session(now) in {'premarket','afterhours'}:return 'delayed_sip'
  return 'sip' if regular_feed=='sip' else 'iex'
 def bars_feed(snapshot_feed):return 'sip' if snapshot_feed=='delayed_sip' else snapshot_feed
 def fresh(ts,now,feed):
  z=parse_ts(ts)
  if not z or z.date()!=now.date():return False
  age=(now-z).total_seconds()
  # Delayed SIP events reach us about 15 minutes after the trade; allow five
  # minutes of transport/quiet-market tolerance, but never accept an old
  # same-day snapshot as current. IEX/SIP regular-session quotes must be fresh.
  max_age=20*60 if feed=='delayed_sip' else 180
  return -60<=age<=max_age
 async def assets():
  async with httpx.AsyncClient(timeout=15) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=hdr(),params={'asset_class':'us_equity','status':'active'})
  out=[]
  if r.status_code<400:
   bad=('preferred','depositary share','depositary shares','warrant','rights','unit ',' units','note due','notes due')
   for a in r.json() or []:
    s=str(a.get('symbol') or '').upper();ex=str(a.get('exchange') or '').upper();n=str(a.get('name') or '').lower()
    if re.fullmatch(r'[A-Z]{1,5}',s) and not any(x in n for x in bad) and a.get('tradable') and ex in {'NASDAQ','NYSE','AMEX','ARCA','BATS'} and not any(x in n for x in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):out.append({'ticker':s,'name':a.get('name'),'exchange':ex})
  return out
 async def snaps(symbols,feed):
  out={};sem=asyncio.Semaphore(8)
  async with httpx.AsyncClient(timeout=12) as c:
   async def one(ch):
    async with sem:
     try:
      r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=hdr(),params={'symbols':','.join(ch),'feed':feed})
      if r.status_code<400:out.update(r.json() or {})
     except Exception:pass
   await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)))
  return out
 def basic(m,s,now,feed):
  lt=s.get('latestTrade') or {};lq=s.get('latestQuote') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {};mts=lt.get('t') or mb.get('t')
  if not fresh(mts,now,feed):return None
  p=f(lt.get('p'),f(mb.get('c'),f(db.get('c'))));prev=f(pb.get('c'));vol=f(db.get('v'));pv=f(pb.get('v'));o=f(db.get('o'));hi=f(db.get('h'));lo=f(db.get('l'))
  if p<.5 or prev<=0:return None
  ch=(p/prev-1)*100;gap=(o/prev-1)*100 if o else ch;rp=(p-lo)/(hi-lo) if hi>lo else .5;vr=vol/pv if pv else 0
  bid=f(lq.get('bp'));ask=f(lq.get('ap'));mid=(bid+ask)/2 if bid>0 and ask>=bid else 0;spread_bps=(ask-bid)/mid*10000 if mid else None
  return {**m,'price':round(p,4),'prev_close':prev,'change_pct':round(ch,2),'snapshot_gap_pct':round(gap,2),'day_volume':vol,'dollar_volume':round(p*vol,2),'prev_day_volume':pv,'snapshot_volume_ratio':round(vr,3) if vr else None,'snapshot_range_position':round(rp,3),'day_open':o,'day_high':hi,'day_low':lo,'minute_volume':f(mb.get('v')),'bid':bid or None,'ask':ask or None,'spread_bps':round(spread_bps,1) if spread_bps is not None else None,'market_timestamp':mts,'data_source':'Alpaca','data_feed':feed,'bars_feed':bars_feed(feed),'data_delay_minutes':15 if feed=='delayed_sip' else 0}
 def qrank(r):
  ch=f(r.get('change_pct'));gap=f(r.get('snapshot_gap_pct'));vr=f(r.get('snapshot_volume_ratio'));rp=f(r.get('snapshot_range_position'),.5);dv=f(r.get('price'))*max(f(r.get('day_volume')),1)
  # Discovery must not become a "top gainers" list. Reward early movement,
  # but keep enough gappers in the deep pool to audit them instead of silently
  # losing them before the strategy stage can classify them as extended.
  early_move=min(max(ch,0),6)*2.5
  extension_penalty=max(ch-8,0)*3.0+max(abs(gap)-10,0)*2.0
  return min(math.log10(max(dv,1)),10)*3+min(vr,5)*8+rp*8+early_move-extension_penalty
 async def batch_bars(symbols,c,snapshot_feed):
  out={s:([],None) for s in symbols};end=datetime.now(timezone.utc);start=end-timedelta(days=8);bf=bars_feed(snapshot_feed)
  # Free/basic accounts may query consolidated SIP historical data when end is outside
  # the restricted recent window. Keep a small safety margin beyond 15 minutes.
  if bf=='sip':end=end-timedelta(minutes=16)
  for i in range(0,len(symbols),50):
   ch=symbols[i:i+50];token=None;pages=0
   while pages<6:
    params={'symbols':','.join(ch),'timeframe':'5Min','start':start.isoformat().replace('+00:00','Z'),'end':end.isoformat().replace('+00:00','Z'),'feed':bf,'adjustment':'split','limit':10000,'sort':'asc'}
    if token:params['page_token']=token
    try:r=await c.get('https://data.alpaca.markets/v2/stocks/bars',headers=hdr(),params=params)
    except Exception as e:
     for s in ch:out[s]=(out[s][0],type(e).__name__)
     break
    if r.status_code>=400:
     msg=''
     try:msg=str((r.json() or {}).get('message') or '')[:120]
     except:pass
     for s in ch:out[s]=(out[s][0],f'HTTP_{r.status_code}:{msg}')
     break
    body=r.json() or {};bm=body.get('bars') or {}
    for s in ch:
     if bm.get(s):out[s]=(out[s][0]+bm.get(s,[]),None)
    token=body.get('next_page_token');pages+=1
    if not token:break
  return out
 async def recent_news(symbols,now,names=None):
  if not symbols:return {}
  start=now.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
  params={'symbols':','.join(symbols),'start':start.isoformat().replace('+00:00','Z'),'limit':50,'sort':'desc','include_content':'false'}
  try:
   async with httpx.AsyncClient(timeout=12) as c:r=await c.get('https://data.alpaca.markets/v1beta1/news',headers=hdr(),params=params)
   if r.status_code>=400:return {}
   items=(r.json() or {}).get('news') or []
  except Exception:return {}
  out={};names=names or {}
  def relevant(symbol,item):
   headline=str(item.get('headline') or '').upper()
   if symbol in headline:return True
   # Alpaca can tag broad roundup articles with every mentioned ticker.  Only
   # promote one as a catalyst when the headline actually names the company.
   words=[w for w in re.findall(r'[A-Z0-9]+',str(names.get(symbol) or '').upper()) if len(w)>=4 and w not in {'INC','CORP','CORPORATION','CLASS','COMMON','STOCK','HOLDINGS','GROUP'}]
   return any(w in headline for w in words[:3])
  for item in items:
   published=parse_ts(item.get('created_at') or item.get('updated_at'))
   age=max(0,(now-published).total_seconds()/60) if published else None
   for symbol in item.get('symbols') or []:
    symbol=str(symbol).upper()
    if symbol not in symbols or symbol in out or not relevant(symbol,item):continue
    out[symbol]={'catalyst_present':True,'catalyst_age_minutes':round(age,1) if age is not None else None,'catalyst_headline':item.get('headline'),'catalyst_source':item.get('source')}
  return out
 def enrich(r,bar_result):
  bs,bar_error=bar_result;now=datetime.now(timezone.utc).astimezone(NY);by={}
  for b in bs:
   z=parse_ts(b.get('t'))
   if z:by.setdefault(z.date(),[]).append((z,b))
  todays=by.get(now.date(),[]);cur=now.hour*60+now.minute;sess=session(now);session_start=240 if sess=='premarket' else 570;effective_cur=max(session_start,cur-(16 if r.get('bars_feed')=='sip' and r.get('data_feed')=='delayed_sip' else 0))
  live=sum(f(b.get('v')) for z,b in todays if session_start<=z.hour*60+z.minute<=effective_cur);hist=[]
  for d,a in sorted(by.items()):
   if d==now.date():continue
   v=sum(f(b.get('v')) for z,b in a if session_start<=z.hour*60+z.minute<=effective_cur)
   if v>0:hist.append(v)
  baseline=sum(hist[-5:])/len(hist[-5:]) if hist else 0;raw=live/baseline if baseline else 0;reliable=bool(baseline>=1000 and live>0);rvol=min(raw,25.0) if raw>0 else 0
  window=[(z,b) for z,b in todays if session_start<=z.hour*60+z.minute<=effective_cur]
  highs=[f(b.get('h')) for z,b in window if f(b.get('h'))>0];lows=[f(b.get('l')) for z,b in window if f(b.get('l'))>0]
  # One canonical delayed-SIP clock drives every premarket field.  The old
  # code mixed the snapshot trade with an older chart bar, so the list and
  # detail screen could legitimately disagree even though both were Alpaca.
  if sess=='premarket' and window:
   last_bar=window[-1][1];p=f(last_bar.get('c'));prev=f(r.get('prev_close'))
   if p>0:r['price']=round(p,4)
   if prev>0 and p>0:
    r['change_pct']=round((p/prev-1)*100,2);r['snapshot_gap_pct']=r['change_pct']
   r['market_timestamp']=last_bar.get('t') or r.get('market_timestamp')
   r['day_volume']=round(live);r['dollar_volume']=round(p*live,2)
  else:p=f(r.get('price'))
  lo=min(lows) if lows else f(r.get('day_low'),p);hi=max(highs) if highs else f(r.get('day_high'),p);used=(p-lo)/(hi-lo)*100 if hi>lo else 50;rp=max(0,min(1,(p-lo)/(hi-lo))) if hi>lo else .5;latest5=f(window[-1][1].get('v')) if window else f(r.get('minute_volume'));elapsed=max((effective_cur-session_start)/5,1);avg_min=baseline/elapsed if baseline else 0;burst=latest5/avg_min if avg_min else 0
  pm_vwap=(sum(((f(b.get('h'))+f(b.get('l'))+f(b.get('c')))/3)*f(b.get('v')) for _,b in window)/live) if live>0 else None
  freshness='current_delayed_premarket' if sess=='premarket' and window else ('no_premarket_trades' if sess=='premarket' else 'current_session')
  r.update({'bars_count':len(bs),'bars_error':bar_error,'today_bars_count':len(todays),'historical_days_with_volume':len(hist),'session':sess,'market_session':sess,'session_start_minute':session_start,'effective_market_minute':effective_cur,'premarket_mode':sess=='premarket','session_live_volume':round(live),'premarket_volume':round(live) if sess=='premarket' and window else None,'premarket_high':round(hi,4) if sess=='premarket' and window else None,'premarket_low':round(lo,4) if sess=='premarket' and window else None,'premarket_price':round(p,4) if sess=='premarket' and window else None,'premarket_vwap':round(pm_vwap,4) if pm_vwap else None,'rvol_raw':round(raw,3) if raw else None,'rvol':round(rvol,3) if rvol else None,'rvol_reliable':reliable,'rvol_capped':bool(raw>25),'intraday_move_used_pct':round(used,1),'minute_volume_burst':round(burst,2) if burst else None,'historical_baseline_volume':round(baseline) if baseline else None,'current_range_position':round(rp,3),'data_freshness_status':freshness,'market_timestamp_current_day':bool(window),'live_structure_source':'canonical-delayed-sip-bars'});return r
 def stage(r):
  if not r.get('rvol_reliable'):return 'watch'
  ch=f(r.get('change_pct'));rv=f(r.get('rvol'));used=f(r.get('intraday_move_used_pct'),50);rp=f(r.get('current_range_position'),.5);burst=f(r.get('minute_volume_burst'));gap=f(r.get('snapshot_gap_pct'))
  # A large pre-market move is evidence of attention, not evidence of future
  # upside. Once too much of the move is already consumed, keep it for learning
  # and diagnostics but never promote it as a forward trade candidate.
  if ch>=10 or gap>=10 or (ch>=6 and used>=90):return 'already_extended'
  if rv>=1.15 and .55<=rp<=.90 and used<90 and -3<=ch<7:return 'pre_breakout'
  if .5<=ch<8 and rv>=1.2 and .65<=rp<=.94 and used<92 and (burst>=1.0 or burst==0):return 'early_breakout'
  return 'watch'
 def rank(r):
  st=stage(r);rv=f(r.get('rvol'));ch=f(r.get('change_pct'));gap=f(r.get('snapshot_gap_pct'));rp=f(r.get('current_range_position'),.5);used=f(r.get('intraday_move_used_pct'),50);burst=f(r.get('minute_volume_burst'))
  # Balanced forward score: favor abnormal participation BEFORE extension.
  # 2-6% gaps get a modest setup bonus; large gaps and consumed intraday range
  # are penalized progressively so a stock cannot score highly merely because
  # it already exploded in pre-market.
  gap_bonus=6 if 2<=gap<=6 else (2 if 0<gap<8 else 0)
  extension_penalty=max(ch-5,0)*7+max(gap-7,0)*8+max(used-82,0)*1.4
  score=35+min(max(rv-1,0),8)*6+rp*10+min(burst,5)*2+gap_bonus+{'pre_breakout':25,'early_breakout':16,'watch':-20,'already_extended':-100}[st]-extension_penalty
  if r.get('rvol_capped'):score-=8
  return score,st
 async def scanner(top:int=10,candidates:int=40):
  ts=datetime.now(timezone.utc);now=ts.astimezone(NY);sess=session(now);feed=scan_feed(now);bf=bars_feed(feed);sid=f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";wanted=10;print(f'LOCAL_SCANNER_START scan_id={sid} session={sess} snapshot_feed={feed} bars_feed={bf}',flush=True)
  aa=await assets();ss=await snaps([x['ticker'] for x in aa],feed);pool=[];stale=0
  for a in aa:
   if a['ticker'] in ss:
    x=basic(a,ss[a['ticker']],now,feed)
    if x:pool.append(x)
    else:stale+=1
  pool.sort(key=qrank,reverse=True);pred=[];watch=[];ext=[];en=[];seen=set()
  async with httpx.AsyncClient(timeout=25,limits=httpx.Limits(max_connections=6,max_keepalive_connections=6)) as c:
   for cap in (80,120,180):
    batch=[x for x in pool[:min(cap,len(pool))] if x['ticker'] not in seen];bm=await batch_bars([x['ticker'] for x in batch],c,feed) if batch else {};rows=[enrich(dict(x),bm.get(x['ticker'],([],None))) for x in batch]
    for x in rows:
     seen.add(x['ticker']);en.append(x);sc,st=rank(x);x.update({'breakout_stage':st,'score':max(0,min(100,round(sc))),'forward_rank':round(sc,2),'candidate_type':'prediction' if st in {'pre_breakout','early_breakout'} else 'learning_observation','strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat()});({'already_extended':ext,'watch':watch}.get(st,pred)).append(x)
    pred.sort(key=lambda x:({'pre_breakout':2,'early_breakout':1}.get(x['breakout_stage'],0),x['forward_rank']),reverse=True);print(f'LOCAL_SCANNER_EXPAND scan_id={sid} session={sess} snapshot_feed={feed} bars_feed={bf} fresh_pool={len(pool)} stale_filtered={stale} deep={len(en)} predictive={len(pred)} watch={len(watch)} extended={len(ext)} cap={cap}',flush=True)
    if len(pred)>=wanted:break
  diag=sorted(en,key=lambda x:(f(x.get('rvol_raw')),-f(x.get('bars_count'))),reverse=True)[:10]
  for d in diag[:5]:print(f"MARKET_DATA_DIAG {d.get('ticker')} snapshot_feed={d.get('data_feed')} bars_feed={d.get('bars_feed')} bars={d.get('bars_count')} err={d.get('bars_error')} today={d.get('today_bars_count')} hist={d.get('historical_days_with_volume')} livevol={d.get('session_live_volume')} baseline={d.get('historical_baseline_volume')} rvol={d.get('rvol_raw')} reliable={d.get('rvol_reliable')} px={d.get('price')} ts={d.get('market_timestamp')}",flush=True)
  # The product contract is always ten auditable rows.  Strong predictive
  # candidates remain first; when fewer than ten pass the strict gate, fill
  # the remaining ranks with the best non-extended watch candidates.  Those
  # rows are explicitly marked as lower-confidence observations so the UI and
  # learning journal never present them as equally strong signals.
  predictive=pred[:wanted]
  fallback=sorted(watch,key=lambda x:x['forward_rank'],reverse=True)[:max(0,wanted-len(predictive))]
  for x in predictive:
   x['quality_tier']='predictive';x['is_predictive_signal']=True
  for x in fallback:
   x['candidate_type']='watch_candidate';x['quality_tier']='watch_fallback';x['is_predictive_signal']=False
  sel=predictive+fallback
  news=await recent_news([x['ticker'] for x in sel],now,{x['ticker']:x.get('name') for x in sel})
  for x in sel:
   x.update(news.get(x['ticker']) or {'catalyst_present':False,'catalyst_age_minutes':None,'catalyst_headline':None,'catalyst_source':None})
   # Catalyst is a confirmation factor, not a substitute for an early setup.
   # A missing verified headline prevents a very high confidence score; a fresh
   # ticker-specific headline adds only a bounded bonus.
   if x.get('catalyst_present') and x.get('quality_tier')=='predictive':
    age=f(x.get('catalyst_age_minutes'),9999)
    x['score']=min(94,int(round(f(x.get('score'))+(8 if age<=180 else 4))))
   elif not x.get('catalyst_present'):
    x['score']=min(int(round(f(x.get('score')))),82)
   if f(x.get('change_pct'))>=8 or f(x.get('snapshot_gap_pct'))>=8:
    x['score']=min(int(round(f(x.get('score')))),76)
  # Re-rank after bounded catalyst/extension adjustments so the displayed Top
  # 10 and the learning journal use exactly the same canonical ordering.
  sel.sort(key=lambda x:(x.get('quality_tier')=='predictive',f(x.get('score')),f(x.get('forward_rank'))),reverse=True)
  for x in sel:
    # Stable compatibility aliases consumed by the existing UI.  These do not
    # change layout; they make the already-present columns show canonical data.
    x['change']=x.get('change_pct');x['gap_pct']=x.get('snapshot_gap_pct')
    x['volume']=x.get('day_volume');x['catalyst']=x.get('catalyst_headline') or 'לא נמצא קטליזטור חדשותי עדכני'
    # Risk must reflect liquidity/spread/price, not merely a high scanner rank.
    price=f(x.get('price'));volume=f(x.get('day_volume'));spread=f(x.get('spread_bps'))
    if price<2 or volume<20000 or spread>100:x['risk']=5
    elif price<5 or volume<50000 or spread>60:x['risk']=4
    elif x.get('quality_tier')!='predictive' or not x.get('rvol_reliable') or volume<100000:x['risk']=3
    else:x['risk']=2
    x['score']=min(94,max(0,int(round(f(x.get('score'))))))
    if x.get('quality_tier')!='predictive':x['score']=min(x['score'],72)
   x['strategy_fit_score']=x['score'];x['score_semantics']='strategy_fit_not_success_probability'
  for position,x in enumerate(sel,1):x['rank']=position
  timing_events=[]
  try:
   import learning_store
   from timing_signals import annotate_and_record,monitor_active_positions
   timing_events=annotate_and_record(sel,learning_store,sid,ts)
   timing_events+=monitor_active_positions(pool,learning_store,sid,ts)
  except Exception as e:print(f'TIMING_SIGNAL_ERROR {type(e).__name__}',flush=True)
  payload={'results':sel,'timing_events_recorded':len(timing_events),'timing_version':'timing-signals-v1','watch_observations':sorted(watch,key=lambda x:x['forward_rank'],reverse=True)[:30],'extended_observations':ext[:30],'diagnostic_sample':diag,'assets_scanned':len(aa),'snapshots_received':len(ss),'stale_snapshots_filtered':stale,'fresh_market_pool':len(pool),'deep_candidates':len(en),'forward_candidate_count':len(pred),'predictive_top10_count':len(predictive),'watch_fallback_count':len(fallback),'requested_top':wanted,'complete_top10':len(sel)>=wanted,'strategy_version':STRATEGY_VERSION,'scan_id':sid,'generated_at':ts.isoformat(),'session':sess,'data_source':'Alpaca','feed':feed,'bars_feed':bf,'data_delay_minutes':15 if feed=='delayed_sip' else 0,'ranking_status':'session-aware-quality-tiered-top10','candidate_semantics':'forward-first;verified-catalyst-bounded;large-gap-penalized;predictive-first-then-explicit-watch-fallback;already-extended-excluded','cache_policy':'no-store','quality_guard':{'fresh_snapshot_required':True,'batched_bars':True,'delayed_sip_snapshots':feed=='delayed_sip','historical_sip_bars':bf=='sip','historical_sip_safety_minutes':16,'rvol_cap':25,'minimum_baseline_volume':1000,'unreliable_rvol_excluded_from_predictive':True,'watch_fallbacks_explicitly_labeled':True,'same_effective_clock_baseline':True}}
  print(f'LOCAL_SCANNER_DONE scan_id={sid} session={sess} snapshot_feed={feed} bars_feed={bf} assets={len(aa)} snaps={len(ss)} fresh={len(pool)} stale_filtered={stale} results={len(sel)} predictive={len(pred)} complete={payload["complete_top10"]}',flush=True);return JSONResponse(payload,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION,'X-Scan-Id':sid,'X-Market-Feed':feed,'X-Bars-Feed':bf})
 old=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 if old:app.router.routes.remove(old)
 app.add_api_route('/api/scanner/day',scanner,methods=['GET'],name='scanner_day_local');print('LOCAL_SCANNER_INSTALLED no_runtime_exec=true delayed_snapshots=true historical_sip_bars=true batched_bars=true',flush=True);return scanner
