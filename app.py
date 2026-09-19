import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Predictive day-scanner alignment: never fill the Top-10 with a static list of
# liquid/mega-cap names merely to reach ten rows. A missing prediction is safer
# than presenting an already-moving stock as a forward candidate.
try:
    import httpx as _httpx
    _original_day_scanner=day_scanner
    _day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)

    async def _feed_observable(symbol):
        if not (ALPACA_KEY and ALPACA_SECRET): return False,'alpaca_not_configured'
        h={'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
        try:
            async with _httpx.AsyncClient(timeout=12) as c:
                r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=h,params={'timeframe':'1Min','limit':2,'feed':ALPACA_FEED,'adjustment':'split','sort':'desc'})
            if r.status_code>=400:return False,f'http_{r.status_code}'
            bars=(r.json() or {}).get('bars') or []
            return bool(bars),('ok' if bars else 'no_bars')
        except Exception as e:return False,type(e).__name__

    def _predictive_gate(row):
        """Conservative anti-chase gate. Does not change strategy weights."""
        try: change=float(row.get('change') if row.get('change') is not None else row.get('change_pct') or 0)
        except Exception: change=0.0
        try: score=float(row.get('score') or 0)
        except Exception: score=0.0
        try: rvol=float(row.get('rvol') or 0)
        except Exception: rvol=0.0
        reasons=' '.join(str(x) for x in (row.get('reasons') or [])).lower()
        catalyst=bool(row.get('catalyst') or row.get('news_count') or ('news' in reasons) or ('חדשות' in reasons))
        # Extremely extended names are discovery/mover observations, not predictions,
        # unless the underlying strategy explicitly marks a fresh entry setup.
        entry_ready=bool(row.get('entry_ready') or row.get('entry_signal') or row.get('action') in ('BUY','קנייה','כניסה'))
        too_extended=change >= 20.0 and not entry_ready
        weak_unconfirmed=(score < 45 and rvol < 1.5 and not catalyst)
        return (not too_extended and not weak_unconfirmed), {'change_pct':change,'score':score,'rvol':rvol,'catalyst':catalyst,'entry_ready':entry_ready,'too_extended':too_extended}

    async def _aligned_day_scanner(top:int=10,candidates:int=40):
        wanted=max(3,min(top,20))
        base=await _original_day_scanner(top=max(20,wanted),candidates=max(wanted,min(max(candidates,60),60)))
        rows=list((base or {}).get('results') or [])
        predictive=[]; rejected=[]
        for row in rows:
            sym=str(row.get('ticker') or '').upper().strip()
            if not sym:continue
            ok,reason=await _feed_observable(sym)
            if not ok:
                rejected.append({'ticker':sym,'reason':reason});continue
            eligible,gate=_predictive_gate(row)
            if not eligible:
                rejected.append({'ticker':sym,'reason':'anti_chase_gate','gate':gate});continue
            item=dict(row)
            item['data_observable']=True;item['data_feed']=ALPACA_FEED
            item['candidate_type']='prediction';item['prediction_status']='pre_move_candidate'
            item['anti_chase_checked']=True;item['gate_metrics']=gate
            predictive.append(item)
            if len(predictive)>=wanted:break
        out=dict(base or {})
        out['results']=predictive[:wanted]
        out['feed']=ALPACA_FEED
        out['observable_count']=len(out['results'])
        out['unobservable_count']=sum(1 for x in rejected if x.get('reason')!='anti_chase_gate')
        out['rejected_candidates']=rejected[:40]
        out['universe_alignment']='predictive_discovery_verified_no_static_fill'
        out['candidate_semantics']='forward_prediction_not_top_movers'
        out['requested_top']=wanted
        out['complete_top10']=len(out['results'])>=wanted
        if len(out['results'])<wanted:
            out['note_he']=f'נמצאו {len(out["results"])} מועמדות מאומתות בלבד; המערכת לא ממלאת מקומות במניות שכבר עלו או ברשימה קבועה.'
        return out

    if _day_route:
        _day_route.endpoint=_aligned_day_scanner
        SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'feed':ALPACA_FEED,'mode':'predictive_discovery_verified_no_static_fill','anti_chase':True}
    else:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as _align_error:SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(_align_error).__name__}: {_align_error}'}

try:
    import sys,asyncio
    _core=sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    from learning_comparison import install_learning_comparison
    install_signal_journal(app,_core);install_missed_movers_learning(app,_core);install_learning_comparison(app,_core)
    LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v3-predictive','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT,'feature_comparison':True}
except Exception as _learning_error:LEARNING_ENGINE_STATUS={'installed':False,'strategy_version':'strategy-learning-v3-predictive','error':f'{type(_learning_error).__name__}: {_learning_error}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}

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
