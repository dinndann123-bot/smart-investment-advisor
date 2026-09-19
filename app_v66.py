import urllib.request
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/13fe48cbb4886fe2ad95a37712562c03a17fc035/app_v66.py'
_code=urllib.request.urlopen(_STABLE,timeout=30).read().decode('utf-8')
exec(compile(_code,_STABLE,'exec'),globals(),globals())

# v6.6.7: forward-validation journal. Records every Top-10 signal and measures subsequent live prices.
try:
 import json,time,asyncio
 from datetime import datetime,timezone
 from collections import deque
 from fastapi.responses import JSONResponse
 import learning_store
 STRATEGY_VERSION='strategy-learning-v6.6.7-forward-validation'
 _route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 _base_scanner=scanner_v666
 try:
  _signal_journal=deque(learning_store.load(3000),maxlen=3000)
  print(f'LEARNING_STORE_LOADED backend={learning_store.backend()} signals={len(_signal_journal)}',flush=True)
 except Exception as _store_load_error:
  _signal_journal=deque(maxlen=3000)
  print(f'LEARNING_STORE_LOAD_ERROR {type(_store_load_error).__name__}',flush=True)
 _horizons=(1,3,5,10,15)
 def _selection_profile(x):
  rv=f(x.get('rvol'));burst=f(x.get('minute_volume_burst'));rp=f(x.get('current_range_position'));used=f(x.get('intraday_move_used_pct'));gap=f(x.get('snapshot_gap_pct'));chg=f(x.get('change_pct'));vol=f(x.get('day_volume'));base=f(x.get('historical_baseline_volume'))
  criteria=[
   {'key':'stage','label':'שלב המהלך','value':x.get('breakout_stage'),'display':'לפני פריצה' if x.get('breakout_stage')=='pre_breakout' else 'פריצה מוקדמת','passed':x.get('breakout_stage') in {'pre_breakout','early_breakout'},'why':'המניה טרם סומנה כמהלך שכבר מוצה'},
   {'key':'rvol','label':'מחזור יחסי','value':rv,'display':f'{rv:.2f}×' if rv else '—','passed':bool(x.get('rvol_reliable') and rv>=1.5),'why':'מחזור חריג ביחס לבסיס ההיסטורי'},
   {'key':'volume_burst','label':'האצת מחזור בדקה','value':burst,'display':f'{burst:.2f}×' if burst else '—','passed':burst>=1.5,'why':'נמדדת התעוררות במחזור הקצר'},
   {'key':'range_position','label':'מיקום בטווח היומי','value':rp,'display':f'{rp*100:.1f}%' if rp else '—','passed':0.55<=rp<=0.95,'why':'חוזקה יחסית בלי להיות בקצה מהלך מוצה'},
   {'key':'move_used','label':'ניצול המהלך','value':used,'display':f'{used:.1f}%' if used else '—','passed':used<92,'why':'נותר מרווח לפני סיווג כמניה מורחבת מדי'},
   {'key':'gap','label':'פער פתיחה','value':gap,'display':f'{gap:+.2f}%' if gap else '0.00%','passed':abs(gap)<=8,'why':'פער שאינו קיצוני מדי לרדיפה'},
   {'key':'liquidity','label':'נזילות','value':vol,'display':f'{int(vol):,}' if vol else '—','passed':vol>=1000 and base>=1000,'why':'מחזור ובסיס היסטורי מספיקים למדידה'},
   {'key':'momentum','label':'שינוי יומי','value':chg,'display':f'{chg:+.2f}%' if chg else '0.00%','passed':-3<=chg<=8,'why':'מומנטום מוקדם ללא רדיפה אחרי זינוק חריג'}]
  passed=sum(bool(c['passed']) for c in criteria)
  return {'criteria':criteria,'passed':passed,'total':len(criteria),'selection_reasons':[c['label']+': '+c['why'] for c in criteria if c['passed']],'anti_chase':x.get('breakout_stage')!='already_extended','data_feed':x.get('data_feed'),'market_timestamp':x.get('market_timestamp')}
 async def _future_prices(symbols):
  ss=await snaps(symbols);out={}
  for s in symbols:
   x=ss.get(s) or {};lt=x.get('latestTrade') or {};mb=x.get('minuteBar') or {};db=x.get('dailyBar') or {};p=f(lt.get('p'),f(mb.get('c'),f(db.get('c'))))
   if p>0:out[s]=p
  return out
 async def _evaluate_due():
  now=time.time();due=[]
  for rec in list(_signal_journal):
   for m in _horizons:
    k=f'p{m}m'
    if k not in rec and now-rec['epoch']>=m*60:due.append((rec,m))
  if not due:return
  syms=sorted({r['ticker'] for r,_ in due});px=await _future_prices(syms)
  for rec,m in due:
   p=px.get(rec['ticker'])
   if p:
    rec[f'p{m}m']=round(p,4);rec[f'ret{m}m_pct']=round((p/rec['signal_price']-1)*100,3)
    try:learning_store.upsert(rec)
    except Exception as _store_update_error:print(f'LEARNING_STORE_UPDATE_ERROR {type(_store_update_error).__name__}',flush=True)
 async def scanner_v667(top:int=10,candidates:int=40):
  response=await _base_scanner(top=top,candidates=candidates)
  try:
   p=json.loads(response.body.decode('utf-8'));now=time.time()
   rows=p.get('results') or []
   # The predictive engine's raw rank is intentionally unbounded and the older
   # response clamped it to 100.  That made many unrelated candidates appear as
   # identical "100/100" successes in legacy UI code.  Publish a differentiated
   # 0-100 strategy-fit score while retaining the raw value for audit/ranking.
   raw_values=[f(x.get('forward_rank'),f(x.get('score'))) for x in rows]
   raw_min=min(raw_values) if raw_values else 0;raw_max=max(raw_values) if raw_values else 0
   spread=max(raw_max-raw_min,1.0);den=max(len(rows)-1,1)
   for rank_i,x in enumerate(rows,1):
    raw=f(x.get('forward_rank'),f(x.get('score')))
    relative=(raw-raw_min)/spread if raw_values else 0
    rank_quality=1-(rank_i-1)/den
    fit_score=round(max(55,min(94,58+22*relative+14*rank_quality)))
    x['raw_strategy_score']=round(raw,2)
    x['strategy_fit_score']=fit_score
    x['score']=fit_score
    x['score_display']=f'{fit_score}/100 התאמה'
    x['score_semantics']='strategy_fit_not_success_probability'
    x['success_rate']=None
    x['success_rate_status']='pending_forward_validation'
    profile=_selection_profile(x)
    x['learning_profile']=profile
    x['selection_reasons']=profile['selection_reasons']
    x['criteria']={
     'שלב המהלך':100 if x.get('breakout_stage')=='pre_breakout' else 82,
     'מחזור יחסי':round(min(100,max(0,f(x.get('rvol'))*10)),1),
     'האצת מחזור':round(min(100,max(0,f(x.get('minute_volume_burst'))*20)),1),
     'מיקום בטווח':round(min(100,max(0,f(x.get('current_range_position'))*100)),1),
     'מרווח לפני מיצוי':round(min(100,max(0,100-f(x.get('intraday_move_used_pct')))),1),
     'איכות Gap':round(min(100,max(0,100-abs(f(x.get('snapshot_gap_pct')))*12.5)),1),
     'נזילות':round(min(100,max(0,f(x.get('day_volume'))/1000)),1),
     'מומנטום מוקדם':round(min(100,max(0,100-abs(f(x.get('change_pct'))-2)*12.5)),1)}
    sp=f(x.get('price'))
    if sp<=0:continue
    _signal_journal.append({'scan_id':p.get('scan_id'),'ticker':x.get('ticker'),'rank':rank_i,'stage':x.get('breakout_stage'),'score':x.get('score'),'signal_price':round(sp,4),'signal_time':p.get('generated_at'),'epoch':now,'rvol':x.get('rvol'),'move_used_pct':x.get('intraday_move_used_pct'),'range_position':x.get('current_range_position'),'gap_pct':x.get('snapshot_gap_pct'),'change_pct':x.get('change_pct'),'minute_volume_burst':x.get('minute_volume_burst'),'day_volume':x.get('day_volume'),'criteria':profile['criteria'],'selection_reasons':profile['selection_reasons'],'data_feed':x.get('data_feed'),'market_timestamp':x.get('market_timestamp')})
    try:learning_store.upsert(_signal_journal[-1])
    except Exception as _store_write_error:print(f'LEARNING_STORE_WRITE_ERROR {type(_store_write_error).__name__}',flush=True)
   await _evaluate_due();p['strategy_version']=STRATEGY_VERSION;p['forward_validation']={'enabled':True,'horizons_minutes':list(_horizons),'journal_size':len(_signal_journal)};response.body=json.dumps(p,separators=(',',':')).encode();response.headers['content-length']=str(len(response.body));response.headers['X-Scanner-Version']=STRATEGY_VERSION
   print(f'SCANNER_V667_JOURNAL scan_id={p.get("scan_id")} added={len(p.get("results") or [])} journal={len(_signal_journal)}',flush=True)
  except Exception as e:print(f'SCANNER_V667_JOURNAL_ERROR {type(e).__name__}: {e}',flush=True)
  return response
 if _route:app.router.routes.remove(_route)
 app.add_api_route('/api/scanner/day',scanner_v667,methods=['GET'],name='scanner_day_v667')
 @app.get('/api/learning/forward-validation')
 async def forward_validation(limit:int=100):
  await _evaluate_due();rows=list(_signal_journal)[-max(1,min(limit,500)):];summary={}
  for m in _horizons:
   vals=[r.get(f'ret{m}m_pct') for r in rows if r.get(f'ret{m}m_pct') is not None]
   summary[str(m)]={'n':len(vals),'positive_rate_pct':round(sum(v>0 for v in vals)/len(vals)*100,1) if vals else None,'avg_return_pct':round(sum(vals)/len(vals),3) if vals else None,'median_return_pct':round(sorted(vals)[len(vals)//2],3) if vals else None}
  return {'strategy_version':STRATEGY_VERSION,'journal_size':len(_signal_journal),'horizons_minutes':list(_horizons),'summary':summary,'signals':rows}
 def _latest_return(rec):
  for m in reversed(_horizons):
   v=rec.get(f'ret{m}m_pct')
   if v is not None:return m,float(v)
  return None,None
 def _learning_payload(symbol=None,limit=200):
  rows=[dict(r) for r in _signal_journal if not symbol or r.get('ticker')==symbol.upper()][-limit:]
  evaluated=[]
  for r in rows:
   m,v=_latest_return(r)
   if v is not None:evaluated.append((r,m,v))
  positive=sum(v>0 for _,_,v in evaluated);target1=sum(v>=1 for _,_,v in evaluated);target2=sum(v>=2 for _,_,v in evaluated)
  feature={}
  for r,m,v in evaluated:
   for c in r.get('criteria') or []:
    if not c.get('passed'):continue
    z=feature.setdefault(c.get('key'),{'feature':c.get('key'),'label':c.get('label'),'signals':0,'wins':0,'returns':[]})
    z['signals']+=1;z['wins']+=int(v>0);z['returns'].append(v)
  learned=[]
  for z in feature.values():
   learned.append({'feature':z['feature'],'label':z['label'],'signals':z['signals'],'success_pct':round(100*z['wins']/z['signals'],1) if z['signals'] else None,'avg_return_pct':round(sum(z['returns'])/len(z['returns']),3) if z['returns'] else None,'avg_r':round((sum(z['returns'])/len(z['returns']))/1.0,3) if z['returns'] else None})
  learned.sort(key=lambda z:(z['signals'],z['avg_return_pct'] if z['avg_return_pct'] is not None else -999),reverse=True)
  recent=[]
  for r in reversed(rows[-50:]):
   m,v=_latest_return(r);recent.append({'date':str(r.get('signal_time') or '')[:10],'symbol':r.get('ticker'),'score':r.get('score'),'gap_pct':r.get('gap_pct'),'rvol_open':r.get('rvol'),'hit1':v is not None and v>=1,'hit2':v is not None and v>=2,'stopped':v is not None and v<=-1,'close_return_pct':v,'result_r':v,'horizon_minutes':m,'scan_id':r.get('scan_id'),'selection_reasons':r.get('selection_reasons'),'criteria':r.get('criteria')})
  return {'has_data':bool(rows),'source':'live_forward_journal','storage':learning_store.status(),'strategy_version':STRATEGY_VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'run_id':rows[-1].get('scan_id') if rows else None,'months':0,'signals':len(rows),'evaluated':len(evaluated),'pending':len(rows)-len(evaluated),'correct_target1':target1,'success_rate_pct':round(100*positive/len(evaluated),1) if evaluated else None,'target1_rate_pct':round(100*target1/len(evaluated),1) if evaluated else None,'target2_rate_pct':round(100*target2/len(evaluated),1) if evaluated else None,'expectancy_r':round(sum(v for _,_,v in evaluated)/len(evaluated),3) if evaluated else None,'universe_size':len({r.get('ticker') for r in rows}),'recall_pct':None,'false_negatives':None,'feature_learning':learned,'recent_signals':recent,'horizons_minutes':list(_horizons),'definitions':{'success_rate':'תשואה חיובית באופק האחרון שנמדד','target1':'+1%','target2':'+2%','stop':'-1%','score':'התאמה לשיטה, לא הסתברות הצלחה'}}
 for _path in ('/api/learning/summary','/api/learning/stock/{symbol}'):
  for _r in list(app.routes):
   if getattr(_r,'path',None)==_path:app.router.routes.remove(_r)
 @app.get('/api/learning/summary')
 async def live_learning_summary():return _learning_payload(limit=500)
 @app.get('/api/learning/stock/{symbol}')
 async def live_stock_learning(symbol:str):
  p=_learning_payload(symbol,200);p['rows']=p.pop('recent_signals');return p
 @app.get('/api/learning/storage-status')
 async def learning_storage_status():return learning_store.status()
 print('SCANNER_V667_INSTALLED forward_validation=1,3,5,10,15m',flush=True)
except Exception as e:print(f'SCANNER_V667_INSTALL_ERROR {type(e).__name__}: {e}',flush=True)
