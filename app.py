import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

try:
    import sys
    _core = sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    install_signal_journal(app, _core)
    install_missed_movers_learning(app, _core)
    LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v2','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a'}
except Exception as _learning_error:
    LEARNING_ENGINE_STATUS={'installed':False,'strategy_version':'strategy-learning-v2','error':f'{type(_learning_error).__name__}: {_learning_error}'}

@app.get('/api/learning/status')
async def learning_status(): return LEARNING_ENGINE_STATUS

@app.on_event('startup')
async def _learning_startup_smoke():
    try:
        paths={getattr(r,'path',None) for r in app.routes}; required={'/api/learning/status','/api/learning/capture-top10','/api/learning/evaluate','/api/learning/journal','/api/learning/summary','/api/learning/missed-movers','/api/learning/missed-movers/summary'}; missing=sorted(required-paths)
        from signal_journal import _db as _journal_db
        from missed_movers_learning import _db as _missed_db
        c1=_journal_db(); c1.execute('SELECT 1 FROM signal_journal LIMIT 1').fetchall(); c1.close(); c2=_missed_db(); c2.execute('SELECT 1 FROM missed_movers LIMIT 1').fetchall(); c2.close()
        print(f'LEARNING_SMOKE installed={LEARNING_ENGINE_STATUS.get("installed")} routes_ok={not missing} missing={missing} db_ok=true version={LEARNING_ENGINE_STATUS.get("strategy_version")}',flush=True)
    except Exception as e: print(f'LEARNING_SMOKE_ERROR {type(e).__name__}: {e}',flush=True)

@app.on_event('startup')
async def _learning_live_cycle_once():
    if not LEARNING_ENGINE_STATUS.get('installed'): return
    try:
        capture=next((r for r in app.routes if getattr(r,'path',None)=='/api/learning/capture-top10'),None)
        evaluate=next((r for r in app.routes if getattr(r,'path',None)=='/api/learning/evaluate'),None)
        if not capture or not evaluate: print('LEARNING_CYCLE_ERROR route_missing',flush=True); return
        result=await capture.endpoint(force=True)
        print(f'LEARNING_CAPTURE ok={result.get("ok")} saved={result.get("saved")} premarket={result.get("premarket_enriched")} source={result.get("source")} session={result.get("session")} version={result.get("strategy_version")}',flush=True)
        ev=await evaluate.endpoint(limit=100)
        print(f'LEARNING_EVALUATE ok={ev.get("ok")} requested={ev.get("requested")} evaluated={ev.get("evaluated")} complete={ev.get("complete")} partial={ev.get("partial")} version={ev.get("strategy_version")}',flush=True)
        from signal_journal import _db as _journal_db
        con=_journal_db(); audit=con.execute("SELECT COUNT(*) n,COUNT(DISTINCT symbol) symbols,SUM(CASE WHEN premarket_price IS NOT NULL THEN 1 ELSE 0 END) pm,MIN(captured_at) first_capture,MAX(captured_at) last_capture FROM signal_journal WHERE trade_date=date('now') AND strategy_version='strategy-learning-v2'").fetchone(); missing=[r[0] for r in con.execute("SELECT DISTINCT symbol FROM signal_journal WHERE trade_date=date('now') AND strategy_version='strategy-learning-v2' AND premarket_price IS NULL ORDER BY symbol LIMIT 25").fetchall()]; con.close()
        print(f'LEARNING_JOURNAL_AUDIT rows={audit[0]} symbols={audit[1]} premarket_rows={audit[2] or 0} missing_premarket={missing} first={audit[3]} last={audit[4]}',flush=True)
    except Exception as e: print(f'LEARNING_CYCLE_ERROR {type(e).__name__}: {e}',flush=True)
