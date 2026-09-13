"""Temporary runtime audit probe. Remove after collecting point-in-time results."""
import json
import os
import threading
import time
import urllib.request


def _compact(j):
    return {
        "as_of": j.get("as_of"),
        "universe_size": j.get("universe_size"),
        "portfolio_1m": j.get("portfolio_1m"),
        "portfolio_12m": j.get("portfolio_12m"),
        "benchmark_1m": (j.get("benchmark") or {}).get("return_1m_pct"),
        "benchmark_12m": (j.get("benchmark") or {}).get("return_12m_pct"),
        "picks": [
            {
                "symbol": x.get("symbol"), "score": x.get("score"),
                "r1m": x.get("return_1m_pct"), "r12m": x.get("return_12m_pct"),
                "x1m": x.get("excess_1m_vs_spy_pct"), "x12m": x.get("excess_12m_vs_spy_pct"),
                "regime": (x.get("metrics") or {}).get("regime"),
                "overext": (x.get("metrics") or {}).get("overextension_penalty"),
            } for x in (j.get("picks") or [])
        ],
        "missed_1m": [x.get("symbol") for x in (j.get("missed_top_1m") or [])],
        "missed_12m": [x.get("symbol") for x in (j.get("missed_top_12m") or [])],
    }


def _get(port, date):
    url=f"http://127.0.0.1:{port}/api/strategy/long/time-travel?as_of={date}&top=10"
    with urllib.request.urlopen(url, timeout=240) as r:
        return json.loads(r.read().decode("utf-8"))


def _run():
    port=os.getenv("PORT")
    if not port:
        return
    time.sleep(10)
    try:
        nov=_get(port,"2021-11-30")
        c=_compact(nov)
        print("LONG_AUDIT_NOV2021="+json.dumps(c,separators=(",",":"),ensure_ascii=False),flush=True)
        p1=nov.get("portfolio_1m") or {}; p12=nov.get("portfolio_12m") or {}
        improved=((p1.get("success_pct") or 0)>50 or (p1.get("avg_return_pct") or -999)>1.5 or
                  (p12.get("success_pct") or 0)>10 or (p12.get("avg_return_pct") or -999)>-10.3)
        print("LONG_AUDIT_IMPROVED="+str(bool(improved)).lower(),flush=True)
        if improved:
            second=_get(port,"2022-09-30")
            print("LONG_AUDIT_SEP2022="+json.dumps(_compact(second),separators=(",",":"),ensure_ascii=False),flush=True)
    except Exception as e:
        print("LONG_AUDIT_ERROR="+repr(e),flush=True)


if os.getenv("PORT"):
    threading.Thread(target=_run,daemon=True).start()
