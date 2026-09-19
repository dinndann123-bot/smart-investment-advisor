import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Forward-candidate scanner + verified dashboard data. UI/CSS/HTML are untouched.
try:
    import httpx as _httpx
    from datetime import datetime, timezone
    _original_day_scanner=day_scanner
    _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)

    def _f(v,default=0.0):
        try:return float(v) if v is not None else default
        except Exception:return default

    async def _alpaca_snapshot(symbol):
        if not (ALPACA_KEY and ALPACA_SECRET): return None,'alpaca_not_configured'
        h={'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
        try:
            async with _httpx.AsyncClient(timeout=12) as c:
                r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot',headers=h,params={'feed':ALPACA_FEED})
            if r.status_code>=400:return None,f'http_{r.status_code}'
            j=r.json() or {}
            return j,'ok'
        except Exception as e:return None,type(e).__name__

    def _forward_rank(row):
        change=_f(row.get('change') if row.get('change') is not None else row.get('change_pct'))
        score=_f(row.get('score'));rvol=_f(row.get('rvol'))
        pm_gap=_f(row.get('premarket_gap_pct') if row.get('premarket_gap_pct') is not None else row.get('gap_pct'))
        pm_vol=_f(row.get('premarket_volume'))
        reasons=' '.join(str(x) for x in (row.get('reasons') or [])).lower()
        catalyst=bool(row.get('catalyst') or row.get('news_count') or 'news' in reasons or 'חדשות' in reasons)
        entry_ready=bool(row.get('entry_ready') or row.get('entry_signal') or row.get('action') in ('BUY','קנייה','כניסה'))
        participation=min(max(rvol,0),10)*2.0
        premarket=min(abs(pm_gap),20)*0.35+min(pm_vol/100000.0,10)
        chase_penalty=max(change-8.0,0)*0.9+(10 if change>=20 and not entry_ready else 0)
        forward=score+participation+premarket+(8 if catalyst else 0)+(6 if entry_ready else 0)-chase_penalty
        return forward,{'model_score':score,'change_pct':change,'rvol':rvol,'premarket_gap_pct':pm_gap,'premarket_volume':pm_vol,'catalyst':catalyst,'entry_ready':entry_ready,'chase_penalty':round(chase_penalty,2),'forward_rank':round(forward,2)}

    def _enrich_from_snapshot(item,snap):
        out=dict(item);lt=snap.get('latestTrade') or {};mb=snap.get('minuteBar') or {};db=snap.get('dailyBar') or {};pb=snap.get('prevDailyBar') or {}
        price=_f(lt.get('p'),_f(mb.get('c'),_f(db.get('c'),0)))
        prev=_f(pb.get('c'),0);day_open=_f(db.get('o'),0)
        if price>0:out['price']=price
        if price>0 and prev>0:
            ch=(price-prev)/prev*100;out['change']=round(ch,2);out['change_pct']=round(ch,2)
            out['gap_pct']=round((day_open-prev)/prev*100,2) if day_open>0 else out.get('gap_pct')
        out['day_open']=day_open or None;out['day_high']=_f(db.get('h'),0) or None;out['day_low']=_f(db.get('l'),0) or None;out['day_volume']=_f(db.get('v'),0) or None
        ts=lt.get('t') or mb.get('t') or db.get('t');out['market_timestamp']=ts;out['last_update']=ts
        out['data_observable']=bool(price);out['data_verified']=bool(price);out['data_source']='Alpaca';out['data_feed']=ALPACA_FEED
        out['data_status']='live' if price else 'missing';out['stale']=False if price else True
        # Preserve model score; never substitute price movement for strategy score.
        if out.get('score') is None:out['score_status']='missing_model_score'
        else:out['score_status']='model_score'
        return out

    async def _aligned_day_scanner(top:int=10,candidates:int=40):
        wanted=10 if top==10 else max(3,min(top,20))
        base=await _original_day_scanner(top=60,candidates=max(120,candidates))
        rows=list((base or {}).get('results') or []);ranked=[];unobservable=[];seen=set()
        for row in rows:
            sym=str(row.get('ticker') or '').upper().strip()
            if not sym or sym in seen:continue
            seen.add(sym);snap,reason=await _alpaca_snapshot(sym)
            if not snap:
                unobservable.append({'ticker':sym,'reason':reason});continue
            item=_enrich_from_snapshot(row,snap)
            rank,metrics=_forward_rank(item);item['candidate_type']='prediction';item['prediction_status']='forward_ranked_candidate';item['forward_rank']=round(rank,2);item['gate_metrics']=metrics
            ranked.append(item)
        ranked.sort(key=lambda x:(x.get('forward_rank',-999),_f(x.get('score'))),reverse=True)
        selected=ranked[:wanted]
        out=dict(base or {});out['results']=selected;out['feed']=ALPACA_FEED;out['data_source']='Alpaca';out['server_timestamp']=datetime.now(timezone.utc).isoformat()
        out['observable_count']=len(ranked);out['unobservable_count']=len(unobservable);out['unobservable_candidates']=unobservable[:40]
        out['universe_alignment']='broad_forward_prediction_rank_verified_snapshots';out['candidate_semantics']='ten_best_forward_candidates_for_learning'
        out['requested_top']=wanted;out['complete_top10']=len(selected)>=wanted
        out['note_he']='המועמדות מדורגות קדימה מתוך סריקה רחבה. מחיר, שינוי יומי, OHLC, נפח וזמן עדכון מאומתים מול Alpaca; ציון השיטה נשמר נפרד ואינו נגזר מהעלייה שכבר קרתה.'
        return out

    if _day_route:
        _day_route.endpoint=_aligned_day_scanner
        SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'feed':ALPACA_FEED,'mode':'broad_forward_prediction_rank_verified_snapshots','target_count':10,'dashboard_verified_data':True,'ui_untouched':True}
    else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as _align_error:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(_align_error).__name__}: {_align_error}'}

try:
    import sys,asyncio
    _core=sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    from learning_comparison import install_learning_comparison
    install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
    LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v3-forward-top10-verified-data','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT,'feature_comparison':True}
except Exception as _learning_error:LEARNING_ENGINE_STATUS={'installed':False,'strategy_version':'strategy-learning-v3-forward-top10-verified-data','error':f'{type(_learning_error).__name__}: {_learning_error}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}

@app.get('/api/learning/status')
async def learning_status():return LEARNING_ENGINE_STATUS

@app.on_event('startup')
async def _learning_startup_smoke():
    try:
        paths={getattr(r,'path',None) for r in app.routes};required={'/api/learning/status','/api/learning/capture-top10','/api/learning/evaluate','/api/learning/journal','/api/learning/summary','/api/learning/missed-movers','/api/learning/missed-movers/summary','/api/learning/feature-comparison'};missing=sorted(required-paths)
        from signal_journal import _db as _journal_db
        from missed_movers_learning import _db as _missed_db
        c1=_journal_db();c1.execute('SELECT 1 FROM signal_journal LIMIT 1').fetchall();c1.close();c2=_missed_db();c2.execute('SELECT 1 FROM missed_movers LIMIT 1').fetchall();c2.close()
        print(f'LEARNING_SMOKE installed={LEARNING_ENGINE_STATUS.get("installed")} routes_ok={not missing} missing={missing} db_ok=true alignment={SCANNER_UNIVERSE_ALIGNMENT} version={LEARNING_ENGINE_STATUS.get("strategy_version")}',flush=True)
    except Exception as e:print(f'LEARNING_SMOKE_ERROR {type(e).__name__}: {e}',flush=True)
