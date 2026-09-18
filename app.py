import urllib.request

# Keep the approved stable application as the runtime base.
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Add research/learning endpoints only after the stable app has been created.
try:
    import sys
    _core = sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    install_signal_journal(app, _core)
    install_missed_movers_learning(app, _core)
    LEARNING_ENGINE_STATUS = {'installed': True,'strategy_version':'strategy-learning-v2','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a'}
except Exception as _learning_error:
    LEARNING_ENGINE_STATUS = {'installed':False,'strategy_version':'strategy-learning-v2','error':f'{type(_learning_error).__name__}: {_learning_error}'}

@app.get('/api/learning/status')
async def learning_status():
    return LEARNING_ENGINE_STATUS

@app.on_event('startup')
async def _learning_startup_smoke():
    try:
        paths={getattr(r,'path',None) for r in app.routes}
        required={'/api/learning/status','/api/learning/capture-top10','/api/learning/evaluate','/api/learning/journal','/api/learning/summary','/api/learning/missed-movers','/api/learning/missed-movers/summary'}
        missing=sorted(required-paths)
        from signal_journal import _db as _journal_db
        from missed_movers_learning import _db as _missed_db
        c1=_journal_db(); c1.execute('SELECT 1 FROM signal_journal LIMIT 1').fetchall(); c1.close()
        c2=_missed_db(); c2.execute('SELECT 1 FROM missed_movers LIMIT 1').fetchall(); c2.close()
        print(f'LEARNING_SMOKE installed={LEARNING_ENGINE_STATUS.get("installed")} routes_ok={not missing} missing={missing} db_ok=true version={LEARNING_ENGINE_STATUS.get("strategy_version")}', flush=True)
    except Exception as e:
        print(f'LEARNING_SMOKE_ERROR {type(e).__name__}: {e}', flush=True)

# One controlled live capture after startup. It only reads the existing scanner/Alpaca
# and writes to the learning SQLite journal; failures never affect the stable app.
@app.on_event('startup')
async def _learning_live_capture_once():
    if not LEARNING_ENGINE_STATUS.get('installed'):
        return
    try:
        capture_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/learning/capture-top10'),None)
        if not capture_route:
            print('LEARNING_CAPTURE_ERROR route_missing',flush=True); return
        result=await capture_route.endpoint(force=True)
        print(f'LEARNING_CAPTURE ok={result.get("ok")} saved={result.get("saved")} premarket={result.get("premarket_enriched")} source={result.get("source")} session={result.get("session")} version={result.get("strategy_version")}',flush=True)
    except Exception as e:
        print(f'LEARNING_CAPTURE_ERROR {type(e).__name__}: {e}',flush=True)
