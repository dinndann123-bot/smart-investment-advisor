import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

STRATEGY_VERSION = "strategy-learning-v6.8.4-auto-1m-deep80"
SCAN_TIMEOUT_SEC = 75
AUTO_SCAN_INTERVAL_SEC = 60
MIN_DEEP_CANDIDATES = 80


def install_async_scanner(app, scanner_engine):
    """Repeatable one-minute scanner with at least 80 deep candidates per cycle."""
    state = {"status":"idle","job_id":None,"started_at":None,"finished_at":None,"result":None,"error":None,"duration_sec":None,"auto_scan_enabled":True,"auto_scan_interval_sec":AUTO_SCAN_INTERVAL_SEC,"auto_task_started":False}
    lock = asyncio.Lock()

    def public_state():
        result=state.get("result") or {}
        return {"status":state.get("status"),"job_id":state.get("job_id"),"started_at":state.get("started_at"),"finished_at":state.get("finished_at"),"duration_sec":state.get("duration_sec"),"error":state.get("error"),"has_cached_result":bool(result.get("results")),"cached_count":len(result.get("results") or []),"strategy_version":STRATEGY_VERSION,"timeout_sec":SCAN_TIMEOUT_SEC,"auto_scan_enabled":True,"auto_scan_interval_sec":state.get('effective_auto_scan_interval_sec',AUTO_SCAN_INTERVAL_SEC),"min_deep_candidates":MIN_DEEP_CANDIDATES,"auto_task_started":state.get("auto_task_started",False)}

    async def run_scan(job_id,top,candidates):
        async with lock:
            candidates=max(MIN_DEEP_CANDIDATES,int(candidates or 0))
            started=time.monotonic();state.update(status="running",job_id=job_id,started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,error=None,duration_sec=None)
            print(f"SCANNER_AUTO_JOB_START job_id={job_id} top={top} candidates={candidates}",flush=True)
            try:
                response=await asyncio.wait_for(scanner_engine(top=top,candidates=candidates),timeout=SCAN_TIMEOUT_SEC)
                body=getattr(response,"body",b"{}");payload=json.loads(body.decode("utf-8")) if isinstance(body,(bytes,bytearray)) else {}
                payload.update(async_strategy_version=STRATEGY_VERSION,job_id=job_id,job_status="complete",requested_deep_candidates=candidates)
                state.update(status="complete",result=payload,finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2),error=None)
                sample=payload.get('diagnostic_sample') or []
                if sample and not payload.get('results') and all(x.get('data_freshness_status')=='previous_session_snapshot' for x in sample):
                    state['effective_auto_scan_interval_sec']=300
                else:
                    state['effective_auto_scan_interval_sec']=AUTO_SCAN_INTERVAL_SEC
                print(f"SCANNER_AUTO_JOB_DONE job_id={job_id} results={len(payload.get('results') or [])} deep={payload.get('deep_candidates')} duration={state['duration_sec']}",flush=True)
            except asyncio.TimeoutError:
                state.update(status="error",error=f"TimeoutError: scanner exceeded {SCAN_TIMEOUT_SEC}s",finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2))
            except Exception as exc:
                state.update(status="error",error=f"{type(exc).__name__}: {exc}",finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-started,2))

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
                result=state.get('result') or {}
                sample=result.get('diagnostic_sample') or []
                # The free IEX feed can return yesterday's snapshots throughout
                # premarket. Avoid exhausting its quota on identical empty scans.
                stale_only=bool(sample) and not result.get('results') and all(
                    x.get('data_freshness_status')=='previous_session_snapshot' for x in sample)
                interval=300 if stale_only else AUTO_SCAN_INTERVAL_SEC
                state['effective_auto_scan_interval_sec']=interval
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
