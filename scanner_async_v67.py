import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

STRATEGY_VERSION = "strategy-learning-v6.8.5-session-aware"
SCAN_TIMEOUT_SEC = 75
AUTO_SCAN_INTERVAL_SEC = 60
MIN_DEEP_CANDIDATES = 80

NO_TRADE_STATES = {"no_premarket_sip_trades", "insufficient_clock_baseline"}
STALE_STATES = {"previous_session_snapshot", "waiting_for_premarket"}
DATA_FAILURE_STATES = {"market_data_error", "feed_error", "request_failed", "rate_limited"}


def install_async_scanner(app, scanner_engine):
    """Repeatable scanner that preserves the distinction between no trades,
    stale data and actual feed failures across premarket and regular sessions."""
    state = {"status":"idle","job_id":None,"started_at":None,"finished_at":None,"result":None,"error":None,"duration_sec":None,"auto_scan_enabled":True,"auto_scan_interval_sec":AUTO_SCAN_INTERVAL_SEC,"auto_task_started":False}
    lock = asyncio.Lock()

    def classify_market_data(payload):
        sample = payload.get("diagnostic_sample") or []
        statuses = [x.get("data_freshness_status") for x in sample if x.get("data_freshness_status")]
        sessions = [x.get("market_session") for x in sample if x.get("market_session")]
        live_rows = sum(1 for x in sample if (x.get("todayBars") or x.get("today_bars_count") or 0) > 0 or x.get("market_timestamp_current_day") is True)
        failures = sum(1 for s in statuses if s in DATA_FAILURE_STATES)
        no_trades = sum(1 for s in statuses if s in NO_TRADE_STATES)
        stale = sum(1 for s in statuses if s in STALE_STATES)
        if failures:
            quality = "feed_failure"
        elif live_rows:
            quality = "current_market_data"
        elif statuses and no_trades == len(statuses):
            quality = "no_session_trades"
        elif statuses and stale == len(statuses):
            quality = "stale_or_waiting"
        else:
            quality = "mixed_or_unknown"
        return {"quality": quality, "sample_rows": len(sample), "live_rows": live_rows, "no_trade_rows": no_trades, "stale_rows": stale, "failure_rows": failures, "sessions": sorted(set(sessions))}

    def public_state():
        result=state.get("result") or {}
        return {"status":state.get("status"),"job_id":state.get("job_id"),"started_at":state.get("started_at"),"finished_at":state.get("finished_at"),"duration_sec":state.get("duration_sec"),"error":state.get("error"),"has_cached_result":bool(result.get("results")),"cached_count":len(result.get("results") or []),"strategy_version":STRATEGY_VERSION,"timeout_sec":SCAN_TIMEOUT_SEC,"auto_scan_enabled":True,"auto_scan_interval_sec":state.get('effective_auto_scan_interval_sec',AUTO_SCAN_INTERVAL_SEC),"min_deep_candidates":MIN_DEEP_CANDIDATES,"auto_task_started":state.get("auto_task_started",False),"market_data_health":state.get("market_data_health")}

    async def run_scan(job_id,top,candidates):
        async with lock:
            candidates=max(MIN_DEEP_CANDIDATES,int(candidates or 0))
            started=time.monotonic();state.update(status="running",job_id=job_id,started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,error=None,duration_sec=None)
            print(f"SCANNER_AUTO_JOB_START job_id={job_id} top={top} candidates={candidates}",flush=True)
            try:
                response=await asyncio.wait_for(scanner_engine(top=top,candidates=candidates),timeout=SCAN_TIMEOUT_SEC)
                body=getattr(response,"body",b"{}");payload=json.loads(body.decode("utf-8")) if isinstance(body,(bytes,bytearray)) else {}
                health=classify_market_data(payload)
                engine_version=payload.get("strategy_version")
                payload.update(
                    strategy_version=STRATEGY_VERSION,
                    engine_strategy_version=engine_version,
                    async_strategy_version=STRATEGY_VERSION,
                    job_id=job_id,
                    job_status="complete",
                    requested_deep_candidates=candidates,
                    market_data_health=health,
                )
                state.update(status="complete",result=payload,finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2),error=None,market_data_health=health)
                # Slow down only for a true feed failure or a fully stale/waiting
                # sample. A stock simply having no premarket trades is normal and
                # must not be confused with a broken data connection.
                state['effective_auto_scan_interval_sec'] = 300 if health['quality'] in {'feed_failure','stale_or_waiting'} and not payload.get('results') else AUTO_SCAN_INTERVAL_SEC
                print(f"SCANNER_DATA_HEALTH job_id={job_id} quality={health['quality']} live={health['live_rows']} noTrades={health['no_trade_rows']} stale={health['stale_rows']} failures={health['failure_rows']} sessions={health['sessions']}",flush=True)
                print(f"SCANNER_AUTO_JOB_DONE job_id={job_id} results={len(payload.get('results') or [])} deep={payload.get('deep_candidates')} duration={state['duration_sec']}",flush=True)
            except asyncio.TimeoutError:
                state.update(status="error",error=f"TimeoutError: scanner exceeded {SCAN_TIMEOUT_SEC}s",finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2),market_data_health={"quality":"scanner_timeout"})
            except Exception as exc:
                state.update(status="error",error=f"{type(exc).__name__}: {exc}",finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2),market_data_health={"quality":"scanner_error"})

    def new_job(top,candidates):
        job_id=f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        state.update(status="running",job_id=job_id,started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,error=None,duration_sec=None)
        asyncio.create_task(run_scan(job_id,top,candidates));return job_id

    async def auto_scan_loop():
        state["auto_task_started"]=True
        print(f"SCANNER_AUTO_LOOP_STARTED interval={AUTO_SCAN_INTERVAL_SEC}s deep_min={MIN_DEEP_CANDIDATES}",flush=True)
        await asyncio.sleep(2)
        while True:
            try:
                cycle_started=time.monotonic()
                if state.get("status") != "running":new_job(10,MIN_DEEP_CANDIDATES)
                elapsed=time.monotonic()-cycle_started
                interval=state.get('effective_auto_scan_interval_sec',AUTO_SCAN_INTERVAL_SEC)
                await asyncio.sleep(max(1,interval-elapsed))
            except asyncio.CancelledError:raise
            except Exception as exc:
                print(f"SCANNER_AUTO_LOOP_ERROR={type(exc).__name__}: {exc}",flush=True);await asyncio.sleep(10)

    async def start_auto_scanner():
        if not state.get("auto_task_started"):asyncio.create_task(auto_scan_loop())

    app.router.add_event_handler("startup", start_auto_scanner)

    async def day(top:int=10,candidates:int=40,refresh:int=0):
        cached=state.get("result") or {};running=state.get("status")=="running";started_job=None
        if refresh and not running:started_job=new_job(top,max(candidates,MIN_DEEP_CANDIDATES));running=True
        elif not cached and not running:started_job=new_job(top,max(candidates,MIN_DEEP_CANDIDATES));running=True
        if cached:
            payload=dict(cached);payload.update(scanner_job=public_state(),served_from_cache=not bool(started_job),refresh_running=running,refresh_accepted=bool(started_job),requested_job_id=started_job)
            return JSONResponse(payload,status_code=202 if started_job else 200,headers={"Cache-Control":"no-store","X-Scanner-Version":STRATEGY_VERSION})
        return JSONResponse({"results":[],"scanner_job":public_state(),"scan_pending":True,"served_from_cache":False,"refresh_accepted":bool(started_job),"requested_job_id":started_job,"strategy_version":STRATEGY_VERSION},status_code=202,headers={"Cache-Control":"no-store","X-Scanner-Version":STRATEGY_VERSION})

    async def start(top:int=10,candidates:int=40):
        if state.get("status")=="running":return JSONResponse({"accepted":True,"already_running":True,"scanner_job":public_state()},status_code=202)
        job_id=new_job(top,max(candidates,MIN_DEEP_CANDIDATES));return JSONResponse({"accepted":True,"job_id":job_id,"scanner_job":public_state()},status_code=202)

    async def status():
        return JSONResponse({"scanner_job":public_state(),"result":state.get("result") if state.get("status")=="complete" else None},headers={"Cache-Control":"no-store"})

    return {"day":day,"start":start,"status":status,"state":state,"strategy_version":STRATEGY_VERSION}
