import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Live Discovery v5: dynamic Alpaca US-equity universe. Historical research
# universes stay untouched. UI/CSS/HTML untouched. Experimental ranking only.
try:
 import asyncio,httpx as _httpx,math
 from datetime import datetime,timezone
 _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 def _f(v,d=0.0):
  try:
   x=float(v);return x if math.isfinite(x) else d
  except:return d
 def _headers():return {'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
 async def _assets():
  async with _httpx.AsyncClient(timeout=30) as c:r=await c.get('https://paper-api.alpaca.markets/v2/assets',headers=_headers(),params={'asset_class':'us_equity','status':'active'})
  if r.status_code>=400:return []
  out=[]
  for a in r.json() or []:
   s=str(a.get('symbol') or '').upper().strip();ex=str(a.get('exchange') or '').upper()
   if not s or not a.get('tradable') or ex not in {'NASDAQ','NYSE','AMEX','ARCA','BATS'}:continue
   # Exclude obvious non-common instruments from prediction discovery while keeping
   # broad listed-stock coverage. ETFs/funds are not silently used as stock picks.
   name=str(a.get('name') or '').lower()
   if any(k in name for k in (' etf','exchange traded',' fund','ishares','spdr ','vanguard ','invesco ')):continue
   out.append({'ticker':s,'name':a.get('name'),'exchange':ex,'shortable':bool(a.get('shortable')),'easy_to_borrow':bool(a.get('easy_to_borrow'))})
  return out
 async def _snapshots(symbols):
  # Alpaca snapshots endpoint accepts a comma-separated symbol batch. Chunking
  # avoids URL-size/rate problems and makes the universe genuinely dynamic.
  found={};sem=asyncio.Semaphore(5)
  async def one(chunk):
   async with sem:
    try:
     async with _httpx.AsyncClient(timeout=25) as c:r=await c.get('https://data.alpaca.markets/v2/stocks/snapshots',headers=_headers(),params={'symbols':','.join(chunk),'feed':ALPACA_FEED})
     if r.status_code<400:found.update(r.json() or {})
    except:pass
  await asyncio.gather(*(one(symbols[i:i+100]) for i in range(0,len(symbols),100)))
  return found
 def _row(meta,s):
  lt=s.get('latestTrade') or {};mb=s.get('minuteBar') or {};db=s.get('dailyBar') or {};pb=s.get('prevDailyBar') or {}
  p=_f(lt.get('p'),_f(mb.get('c'),_f(db.get('c'))));prev=_f(pb.get('c'));op=_f(db.get('o'));vol=_f(db.get('v'));pvol=_f(pb.get('v'))
  if not(p>0 and prev>0):return None
  change=(p/prev-1)*100;gap=(op/prev-1)*100 if op>0 else change
  # Intraday volume vs prior full day is not true RVOL; retain it as a separate
  # participation proxy and never label it as validated RVOL.
  participation=(vol/pvol) if pvol>0 else 0
  # Broad first-pass: enough liquidity to be actionable, while avoiding penny
  # noise. Do not require the stock to have already exploded.
  dollar_vol=p*vol
  if p<0.5 or dollar_vol<250000:return None
  r=dict(meta);r.update({'price':round(p,4),'change':round(change,2),'change_pct':round(change,2),'gap_pct':round(gap,2),'day_open':op or None,'day_high':_f(db.get('h')) or None,'day_low':_f(db.get('l')) or None,'day_volume':vol or None,'prev_day_volume':pvol or None,'participation_proxy':round(participation,4),'market_timestamp':lt.get('t') or mb.get('t') or db.get('t'),'data_source':'Alpaca','data_feed':ALPACA_FEED,'data_verified':True,'stale':False})
  return r
 def _rank(r):
  ch=_f(r.get('change_pct'));gap=_f(r.get('gap_pct'));part=_f(r.get('participation_proxy'));vol=_f(r.get('day_volume'));p=_f(r.get('price'))
  # Discovery score intentionally favors early abnormal participation and modest
  # positive gap, not realized percentage gain. It is a hypothesis to validate.
  participation=min(part*100,30)+min((p*vol)/1000000,20)*0.35
  early_gap=min(max(gap,0),7)*1.8
  extension=max(ch-6,0)*2.5+max(gap-10,0)*2.0
  if ch>=12:extension+=10
  if ch>=20:extension+=15
  score=50+participation+early_gap-extension
  return score,{'participation_proxy':round(part,4),'gap_pct':round(gap,2),'change_pct':round(ch,2),'extension_risk':round(extension,2),'forward_rank':round(score,2),'experimental':True,'rvol_status':'not_yet_validated'}
 async def _scanner(top:int=10,candidates:int=40):
  wanted=10 if top==10 else max(3,min(top,20))
  if not(ALPACA_KEY and ALPACA_SECRET):return {'results':[],'error':'alpaca_not_configured','requested_top':wanted}
  assets=await _assets();sn=await _snapshots([a['ticker'] for a in assets]);ranked=[]
  for a in assets:
   s=sn.get(a['ticker'])
   if not s:continue
   r=_row(a,s)
   if not r:continue
   rank,m=_rank(r);r.update({'score':max(0,min(100,round(rank))), 'forward_rank':round(rank,2),'gate_metrics':m,'candidate_type':'prediction','prediction_status':'dynamic_pre_move_candidate'});ranked.append(r)
  ranked.sort(key=lambda x:x.get('forward_rank',-999),reverse=True);sel=ranked[:wanted]
  return {'results':sel,'feed':ALPACA_FEED,'data_source':'Alpaca','server_timestamp':datetime.now(timezone.utc).isoformat(),'assets_scanned':len(assets),'observable_count':len(ranked),'universe_alignment':'dynamic_alpaca_us_equities_v5','candidate_semantics':'ten_forward_candidates_not_top_movers','requested_top':wanted,'complete_top10':len(sel)>=wanted,'ranking_status':'experimental_learning_overlay','note_he':'Live Discovery סורק דינמית מניות אמריקאיות פעילות ב-Alpaca. הרשימה אינה נבנית מ-Top Movers או מ-universe קשיח. שכבת הדירוג ניסיונית ותיבדק מול תוצאות סוף היום; RVOL אמיתי ונתוני catalyst/PM יתווספו בשלב האימות הבא.'}
 if _day_route:_day_route.endpoint=_scanner;SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'mode':'dynamic_alpaca_us_equities_v5','target_count':10,'ui_untouched':True,'historical_universe_untouched':True,'experimental':True}
 else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as e:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(e).__name__}: {e}'}
try:
 import sys
 _core=sys.modules[__name__]
 from signal_journal import install_signal_journal
 from missed_movers_learning import install_missed_movers_learning
 from learning_comparison import install_learning_comparison
 install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
 LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v5-dynamic-universe','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT,'feature_comparison':True}
except Exception as e:LEARNING_ENGINE_STATUS={'installed':False,'error':f'{type(e).__name__}: {e}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
@app.get('/api/learning/status')
async def learning_status():return LEARNING_ENGINE_STATUS
