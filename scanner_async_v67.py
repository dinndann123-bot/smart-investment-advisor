import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

STRATEGY_VERSION = "strategy-learning-v6.7.1-async-scanner-timeout"
SCAN_TIMEOUT_SEC = 75


def install_async_scanner(app, scanner_engine):
    """Wrap the scanner with a single-flight job, cache and hard backend timeout."""
    state = {
        "status": "idle",
        "job_id": None,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "duration_sec": None,
    }
    lock = asyncio.Lock()

    def public_state():
        result = state.get("result") or {}
        return {
            "status": state.get("status"),
            "job_id": state.get("job_id"),
            "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"),
            "duration_sec": state.get("duration_sec"),
            "error": state.get("error"),
            "has_cached_result": bool(result.get("results")),
            "cached_count": len(result.get("results") or []),
            "strategy_version": STRATEGY_VERSION,
            "timeout_sec": SCAN_TIMEOUT_SEC,
        }

    async def run_scan(job_id, top, candidates):
        async with lock:
            started = time.monotonic()
            state.update(status="running", job_id=job_id,
                         started_at=datetime.now(timezone.utc).isoformat(),
                         finished_at=None, error=None, duration_sec=None)
            print(f"SCANNER_V671_JOB_START job_id={job_id} top={top} candidates={candidates} timeout={SCAN_TIMEOUT_SEC}", flush=True)
            try:
                # Hard ceiling: a stalled provider/symbol can no longer leave the scanner
                # permanently in `running`. wait_for cancels the engine coroutine on expiry.
                response = await asyncio.wait_for(
                    scanner_engine(top=top, candidates=candidates),
                    timeout=SCAN_TIMEOUT_SEC,
                )
                body = getattr(response, "body", b"{}")
                payload = json.loads(body.decode("utf-8")) if isinstance(body, (bytes, bytearray)) else {}
                payload.update(async_strategy_version=STRATEGY_VERSION,
                               job_id=job_id, job_status="complete")
                state.update(status="complete", result=payload,
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             duration_sec=round(time.monotonic() - started, 2), error=None)
                print(f"SCANNER_V671_JOB_DONE job_id={job_id} results={len(payload.get('results') or [])} duration={state['duration_sec']}", flush=True)
            except asyncio.TimeoutError:
                state.update(status="error",
                             error=f"TimeoutError: scanner exceeded {SCAN_TIMEOUT_SEC}s",
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             duration_sec=round(time.monotonic() - started, 2))
                print(f"SCANNER_V671_JOB_TIMEOUT job_id={job_id} duration={state['duration_sec']}", flush=True)
            except asyncio.CancelledError:
                state.update(status="error", error="CancelledError: scanner job cancelled",
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             duration_sec=round(time.monotonic() - started, 2))
                print(f"SCANNER_V671_JOB_CANCELLED job_id={job_id}", flush=True)
                raise
            except Exception as exc:
                state.update(status="error", error=f"{type(exc).__name__}: {exc}",
                             finished_at=datetime.now(timezone.utc).isoformat(),
                             duration_sec=round(time.monotonic() - started, 2))
                print(f"SCANNER_V671_JOB_ERROR job_id={job_id} error={state['error']}", flush=True)

    def new_job(top, candidates):
        job_id = f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        asyncio.create_task(run_scan(job_id, top, candidates))
        return job_id

    async def day(top: int = 10, candidates: int = 40, refresh: int = 0):
        cached = state.get("result") or {}
        running = state.get("status") == "running"
        if (refresh or not cached) and not running:
            new_job(top, candidates)
            running = True
        if cached:
            payload = dict(cached)
            payload.update(scanner_job=public_state(), served_from_cache=True, refresh_running=running)
            return JSONResponse(payload, headers={"Cache-Control": "no-store", "X-Scanner-Version": STRATEGY_VERSION})
        return JSONResponse({"results": [], "scanner_job": public_state(), "scan_pending": True,
                             "served_from_cache": False, "strategy_version": STRATEGY_VERSION},
                            status_code=202,
                            headers={"Cache-Control": "no-store", "X-Scanner-Version": STRATEGY_VERSION})

    async def start(top: int = 10, candidates: int = 40):
        if state.get("status") == "running":
            return JSONResponse({"accepted": True, "already_running": True, "scanner_job": public_state()}, status_code=202)
        job_id = new_job(top, candidates)
        return JSONResponse({"accepted": True, "job_id": job_id, "scanner_job": public_state()}, status_code=202)

    async def status():
        return JSONResponse({"scanner_job": public_state(),
                             "result": state.get("result") if state.get("status") == "complete" else None},
                            headers={"Cache-Control": "no-store"})

    return {"day": day, "start": start, "status": status, "state": state, "strategy_version": STRATEGY_VERSION}
