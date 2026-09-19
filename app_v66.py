import urllib.request
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/13fe48cbb4886fe2ad95a37712562c03a17fc035/app_v66.py'
_code=urllib.request.urlopen(_STABLE,timeout=30).read().decode('utf-8')
exec(compile(_code,_STABLE,'exec'),globals(),globals())

# v6.6.7: forward-validation journal. Records every Top-10 signal and measures subsequent live prices.
try:
 import json,time,asyncio
 from collections import deque
 from fastapi.responses import JSONResponse
 STRATEGY_VERSION='strategy-learning-v6.6.7-forward-validation'
 _route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 _base_scanner=scanner_v666
 _signal_journal=deque(maxlen=3000)
 _horizons=(1,3,5,10,15)
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
    sp=f(x.get('price'))
    if sp<=0:continue
    _signal_journal.append({'scan_id':p.get('scan_id'),'ticker':x.get('ticker'),'rank':rank_i,'stage':x.get('breakout_stage'),'score':x.get('score'),'signal_price':round(sp,4),'signal_time':p.get('generated_at'),'epoch':now,'rvol':x.get('rvol'),'move_used_pct':x.get('intraday_move_used_pct'),'range_position':x.get('current_range_position')})
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
 print('SCANNER_V667_INSTALLED forward_validation=1,3,5,10,15m',flush=True)
except Exception as e:print(f'SCANNER_V667_INSTALL_ERROR {type(e).__name__}: {e}',flush=True)
