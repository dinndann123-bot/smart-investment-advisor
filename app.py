import urllib.request

_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Root fix: discovery may be SIP-wide while enrichment/evaluation uses the configured
# Alpaca feed (normally IEX). Keep broad discovery, but only promote candidates that
# are observable on the configured feed. This preserves the stable UI and scanner
# implementation while making Top-10, premarket and evaluation use one data universe.
try:
    import httpx as _httpx
    _original_day_scanner = day_scanner
    _day_route = next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())), None)

    async def _feed_observable(symbol):
        if not (ALPACA_KEY and ALPACA_SECRET): return False, 'alpaca_not_configured'
        headers={'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
        try:
            async with _httpx.AsyncClient(timeout=12) as c:
                r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',headers=headers,params={'timeframe':'1Min','limit':2,'feed':ALPACA_FEED,'adjustment':'split','sort':'desc'})
            if r.status_code>=400: return False, f'http_{r.status_code}'
            bars=(r.json() or {}).get('bars') or []
            return bool(bars), ('ok' if bars else 'no_bars')
        except Exception as e:
            return False, type(e).__name__

    async def _aligned_day_scanner(top:int=10,candidates:int=40):
        # Ask the stable scanner for a larger ranked pool, then filter by actual feed
        # observability. No UI contract changes: results remains the final Top-N.
        wanted=max(3,min(top,20)); pool_size=max(wanted,min(max(candidates,60),60))
        base=await _original_day_scanner(top=20,candidates=pool_size)
        rows=list((base or {}).get('results') or [])
        observable=[]; rejected=[]
        for row in rows:
            sym=str(row.get('ticker') or '').upper().strip()
            if not sym: continue
            ok,reason=await _feed_observable(sym)
            if ok:
                row=dict(row); row['data_observable']=True; row['data_feed']=ALPACA_FEED; observable.append(row)
            else:
                rejected.append({'ticker':sym,'reason':reason})
            if len(observable)>=wanted: break
        out=dict(base or {}); out['results']=observable[:wanted]; out['feed']=ALPACA_FEED; out['observable_count']=len(observable); out['unobservable_count']=len(rejected); out['unobservable_candidates']=rejected[:20]; out['universe_alignment']='discovery_broad_promotion_configured_feed'; out['requested_top']=wanted
        # If broad discovery does not yield enough observable names, fill only with
        # known liquid names that are themselves verified on the same configured feed.
        if len(out['results'])<wanted:
            existing={x.get('ticker') for x in out['results']}; fillers=['AAPL','NVDA','TSLA','AMD','PLTR','AMZN','META','MSFT','GOOGL','AVGO','NFLX','COIN','HOOD','SOFI','MARA','SMCI','RIVN','IONQ','SOUN','RKLB']
            for sym in fillers:
                if sym in existing: continue
                ok,_=await _feed_observable(sym)
                if not ok: continue
                try:
                    extra=await _original_day_scanner(top=20,candidates=60)
                    match=next((x for x in (extra.get('results') or []) if x.get('ticker')==sym),None)
                    if match:
                        match=dict(match); match['data_observable']=True; match['data_feed']=ALPACA_FEED; out['results'].append(match); existing.add(sym)
                except Exception: pass
                if len(out['results'])>=wanted: break
        out['observable_count']=len(out['results']); return out

    if _day_route:
        _day_route.endpoint=_aligned_day_scanner
        SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'feed':ALPACA_FEED,'mode':'broad_discovery_verified_promotion'}
    else:
        SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':'day_route_missing'}
except Exception as _align_error:
    SCANNER_UNIVERSE_ALIGNMENT={'installed':False,'error':f'{type(_align_error).__name__}: {_align_error}'}

try:
    import sys
    _core = sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    install_signal_journal(app, _core)
    install_missed_movers_learning(app, _core)
    LEARNING_ENGINE_STATUS={'installed':True,'strategy_version':'strategy-learning-v2','stable_base':'1b8068c52a5f7ba5ab6ee455999330b102dbc90a','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}
except Exception as _learning_error:
    LEARNING_ENGINE_STATUS={'installed':False,'strategy_version':'strategy-learning-v2','error':f'{type(_learning_error).__name__}: {_learning_error}','universe_alignment':SCANNER_UNIVERSE_ALIGNMENT}

@app.get('/api/learning/status')
async def learning_status(): return LEARNING_ENGINE_STATUS

@app.on_event('startup')
async def _learning_startup_smoke():
    try:
        paths={getattr(r,'path',None) for r in app.routes}; required={'/api/learning/status','/api/learning/capture-top10','/api/learning/evaluate','/api/learning/journal','/api/learning/summary','/api/learning/missed-movers','/api/learning/missed-movers/summary'}; missing=sorted(required-paths)
        from signal_journal import _db as _journal_db
        from missed_movers_learning import _db as _missed_db
        c1=_journal_db(); c1.execute('SELECT 1 FROM signal_journal LIMIT 1').fetchall(); c1.close(); c2=_missed_db(); c2.execute('SELECT 1 FROM missed_movers LIMIT 1').fetchall(); c2.close()
        print(f'LEARNING_SMOKE installed={LEARNING_ENGINE_STATUS.get("installed")} routes_ok={not missing} missing={missing} db_ok=true alignment={SCANNER_UNIVERSE_ALIGNMENT} version={LEARNING_ENGINE_STATUS.get("strategy_version")}',flush=True)
    except Exception as e: print(f'LEARNING_SMOKE_ERROR {type(e).__name__}: {e}',flush=True)

@app.on_event('startup')
async def _learning_live_cycle_once():
    if not LEARNING_ENGINE_STATUS.get('installed'): return
    try:
        capture=next((r for r in app.routes if getattr(r,'path',None)=='/api/learning/capture-top10'),None); evaluate=next((r for r in app.routes if getattr(r,'path',None)=='/api/learning/evaluate'),None)
        if not capture or not evaluate: print('LEARNING_CYCLE_ERROR route_missing',flush=True); return
        result=await capture.endpoint(force=True)
        print(f'LEARNING_CAPTURE ok={result.get("ok")} saved={result.get("saved")} premarket={result.get("premarket_enriched")} source={result.get("source")} session={result.get("session")} version={result.get("strategy_version")}',flush=True)
        ev=await evaluate.endpoint(limit=100)
        print(f'LEARNING_EVALUATE ok={ev.get("ok")} requested={ev.get("requested")} evaluated={ev.get("evaluated")} complete={ev.get("complete")} partial={ev.get("partial")} version={ev.get("strategy_version")}',flush=True)
        from signal_journal import _db as _journal_db
        con=_journal_db(); audit=con.execute("SELECT COUNT(*) n,COUNT(DISTINCT symbol) symbols,SUM(CASE WHEN premarket_price IS NOT NULL THEN 1 ELSE 0 END) pm,MIN(captured_at) first_capture,MAX(captured_at) last_capture FROM signal_journal WHERE trade_date=date('now') AND strategy_version='strategy-learning-v2'").fetchone(); con.close()
        print(f'LEARNING_JOURNAL_AUDIT rows={audit[0]} symbols={audit[1]} premarket_rows={audit[2] or 0} first={audit[3]} last={audit[4]} alignment={SCANNER_UNIVERSE_ALIGNMENT}',flush=True)
    except Exception as e: print(f'LEARNING_CYCLE_ERROR {type(e).__name__}: {e}',flush=True)
