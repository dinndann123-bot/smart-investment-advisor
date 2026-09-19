import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Pre-move discovery overlay. UI/CSS/HTML untouched. This is an experimental
# ranking layer for learning; it does not overwrite validated strategy weights.
try:
 import httpx as _httpx
 from datetime import datetime,timezone
 _original_day_scanner=day_scanner
 _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 def _f(v,d=0.0):
  try:return float(v) if v is not None else d
  except:return d
 async def _snap(s):
  if not(ALPACA_KEY and ALPACA_SECRET):return None,'alpaca_not_configured'
  h={'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
  try:
   async with _httpx.AsyncClient(timeout=12) as c:r=await c.get(f'https://data.alpaca.markets/v2/stocks/{s}/snapshot',headers=h,params={'feed':ALPACA_FEED})
   return (r.json() or {},'ok') if r.status_code<400 else (None,f'http_{r.status_code}')
  except Exception as e:return None,type(e).__name__
 def _enrich(x,s):
  o=dict(x);lt=s.get('latestTrade') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {};p=_f(lt.get('p'),_f(mb.get('c'),_f(db.get('c'))));prev=_f(pb.get('c'));op=_f(db.get('o'))
  if p:o['price']=p
  if p and prev:o['change']=o['change_pct']=round((p-prev)/prev*100,2);o['gap_pct']=round((op-prev)/prev*100,2) if op else o.get('gap_pct')
  o.update({'day_open':op or None,'day_high':_f(db.get('h')) or None,'day_low':_f(db.get('l')) or None,'day_volume':_f(db.get('v')) or None,'market_timestamp':lt.get('t') or mb.get('t') or db.get('t'),'data_source':'Alpaca','data_feed':ALPACA_FEED,'data_verified':bool(p),'stale':not bool(p)})
  return o
 def _rank(x):
  score=_f(x.get('score'));chg=_f(x.get('change_pct'));rv=_f(x.get('rvol'));gap=_f(x.get('premarket_gap_pct'),_f(x.get('gap_pct')));pv=_f(x.get('premarket_volume'));rs=' '.join(map(str,x.get('reasons') or [])).lower();cat=bool(x.get('catalyst') or x.get('news_count') or 'news' in rs or 'חדשות' in rs);ready=bool(x.get('entry_ready') or x.get('entry_signal') or x.get('action') in ('BUY','קנייה','כניסה'))
  # Discovery evidence: reward abnormal participation and a fresh catalyst. Gap is
  # useful only while modest; already-realized move is treated as extension risk.
  participation=min(max(rv-1,0),9)*3.0+min(pv/100000,12)
  gap_signal=min(max(gap,0),8)*0.8
  catalyst=10 if cat else 0;entry=7 if ready else 0
  extension=max(chg-5,0)*1.8+max(gap-10,0)*1.2
  if chg>=12 and not ready:extension+=8
  if chg>=20 and not ready:extension+=12
  forward=score+participation+gap_signal+catalyst+entry-extension
  return forward,{'model_score':score,'change_pct':chg,'rvol':rv,'premarket_gap_pct':gap,'premarket_volume':pv,'catalyst':cat,'entry_ready':ready,'participation_component':round(participation,2),'extension_risk':round(extension,2),'forward_rank':round(forward,2),'experimental':True}
 async def _scanner(top:int=10,candidates:int=40):
  wanted=10 if top==10 else max(3,min(top,20));base=await _original_day_scanner(top=100,candidates=max(200,candidates));rows=list((base or {}).get('results') or []);ranked=[];bad=[];seen=set()
  for r in rows:
   sym=str(r.get('ticker') or '').upper().strip()
   if not sym or sym in seen:continue
   seen.add(sym);s,why=await _snap(sym)
   if not s:bad.append({'ticker':sym,'reason':why});continue
   it=_enrich(r,s);rank,m=_rank(it);it.update({'candidate_type':'prediction','prediction_status':'pre_move_discovery_candidate','forward_rank':round(rank,2),'gate_metrics':m});ranked.append(it)
  ranked.sort(key=lambda z:(z.get('forward_rank',-999),_f(z.get('score'))),reverse=True);sel=ranked[:wanted];out=dict(base or {});out.update({'results':sel,'feed':ALPACA_FEED,'data_source':'Alpaca','server_timestamp':datetime.now(timezone.utc).isoformat(),'observable_count':len(ranked),'unobservable_count':len(bad),'unobservable_candidates':bad[:50],'universe_alignment':'pre_move_discovery_v4','candidate_semantics':'ten_forward_candidates_not_top_movers','requested_top':wanted,'complete_top10':len(sel)>=wanted,'ranking_status':'experimental_learning_overlay','note_he':'10 מועמדות קדימה מתוך סריקה רחבה. תנועה שכבר התרחשה נחשבת סיכון extension; RVOL/נפח פרה-מרקט/catalyst ו-readiness מקדמים מועמדת. שכבת הדירוג ניסיונית ואינה שינוי מאומת במשקלי השיטה.'});return out
 if _day_route:_day_route.endpoint=_scanner;SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'mode':'pre_move_discovery_v4','target_count':10,'ui_untouched':True,'experimental':True}
 else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as e:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(e).__name__}: {e}'}
try:
 import sys
 _core=sys.modules[__name__]
 from signal_journal import install_signal_journal
 from missed_movers_learning import install_missed_movers_learning
 from learning_comparison import install_learning_comparison
 install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
 LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v4-pre-move','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT,'feature_comparison':True}
except Exception as e:LEARNING_ENGINE_STATUS={'installed':False,'error':f'{type(e).__name__}: {e}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
@app.get('/api/learning/status')
async def learning_status():return LEARNING_ENGINE_STATUS
