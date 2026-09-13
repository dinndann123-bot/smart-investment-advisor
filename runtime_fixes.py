import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
from fastapi.responses import Response


RUNTIME_FIX_VERSION = "2026.09.13-r3-audit"


def install_runtime_fixes(app):
    """Patch live-tracking bugs and add lightweight runtime health checks."""
    import sys

    if getattr(app.state, "runtime_fixes_installed", False):
        return
    app.state.runtime_fixes_installed = True

    mod = sys.modules.get(app.__module__) or sys.modules.get("app")
    if mod is None:
        return

    @app.head("/")
    async def root_head():
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/runtime-health")
    async def runtime_health():
        db_ok = False
        db_error = None
        try:
            con = mod._db()
            con.execute("SELECT 1").fetchone()
            con.close()
            db_ok = True
        except Exception as exc:
            db_error = str(exc)
        return {
            "ok": db_ok,
            "runtime_fix_version": RUNTIME_FIX_VERSION,
            "db_writable": db_ok,
            "db_error": db_error,
            "alpaca_configured": bool(mod.ALPACA_KEY and mod.ALPACA_SECRET),
            "alpha_vantage_configured": bool(mod.ALPHA_KEY),
            "feed": mod.ALPACA_FEED,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # Temporary audit probe: run after startup against the app's own point-in-time
    # endpoint, print compact results, then this block will be removed.
    async def _run_long_audit_probe():
        await asyncio.sleep(4)
        port = os.getenv("PORT", "10000")
        base = f"http://127.0.0.1:{port}"
        try:
            async with httpx.AsyncClient(timeout=240) as client:
                async def one(date):
                    r = await client.get(f"{base}/api/strategy/long/time-travel", params={"as_of": date, "top": 10})
                    r.raise_for_status()
                    j = r.json()
                    return {
                        "as_of": j.get("as_of"),
                        "universe_size": j.get("universe_size"),
                        "portfolio_1m": j.get("portfolio_1m"),
                        "portfolio_12m": j.get("portfolio_12m"),
                        "benchmark_1m": (j.get("benchmark") or {}).get("return_1m_pct"),
                        "benchmark_12m": (j.get("benchmark") or {}).get("return_12m_pct"),
                        "picks": [[x.get("symbol"), x.get("score"), x.get("return_1m_pct"), x.get("return_12m_pct"), (x.get("metrics") or {}).get("overextension_penalty")] for x in (j.get("picks") or [])],
                        "missed_1m": [x.get("symbol") for x in (j.get("missed_top_1m") or [])],
                        "missed_12m": [x.get("symbol") for x in (j.get("missed_top_12m") or [])],
                    }
                nov = await one("2021-11-30")
                print("LONG_AUDIT_NOV2021=" + json.dumps(nov, separators=(",", ":")), flush=True)
                p1 = nov.get("portfolio_1m") or {}
                p12 = nov.get("portfolio_12m") or {}
                improved = ((p1.get("success_pct") or 0) > 50 or (p1.get("avg_return_pct") or -999) > 1.5 or (p12.get("success_pct") or 0) > 10 or (p12.get("avg_return_pct") or -999) > -10.3)
                print("LONG_AUDIT_IMPROVED=" + str(bool(improved)).lower(), flush=True)
                if improved:
                    sep = await one("2022-09-30")
                    print("LONG_AUDIT_SEP2022=" + json.dumps(sep, separators=(",", ":")), flush=True)
        except Exception as exc:
            print("LONG_AUDIT_ERROR=" + repr(exc), flush=True)

    @app.on_event("startup")
    async def _start_long_audit_probe():
        asyncio.create_task(_run_long_audit_probe())

    def _persist_scanner_signals_fixed(items, generated_at, source):
        """Persist qualified scanner signals and count only rows actually inserted."""
        con = mod._db()
        created = generated_at or datetime.now(timezone.utc).isoformat()
        d = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(mod.NY).date().isoformat()
        saved = 0
        for x in items:
            score = float(x.get("score") or 0)
            rvol = x.get("rvol")
            news = int(x.get("news_count") or 0)
            qualifies = score >= 85 and ((rvol is not None and float(rvol) >= 1.5) or news > 0)
            if not qualifies:
                continue
            plan = mod._derive_live_signal_plan(x)
            if not plan:
                continue
            try:
                cur = con.execute(
                    """INSERT OR IGNORE INTO live_signals(
                        created_at,signal_date,symbol,signal_type,score,entry,stop,target1,target2,
                        source,catalyst,rvol,gap_pct,status
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        created, d, x.get("ticker"), "scanner", score,
                        plan["entry"], plan["stop"], plan["target1"], plan["target2"],
                        source, x.get("catalyst"),
                        float(rvol) if rvol is not None else None,
                        float(x.get("change")) if x.get("change") is not None else None,
                        "open",
                    ),
                )
                if cur.rowcount == 1:
                    saved += 1
            except Exception:
                pass
        con.commit()
        con.close()
        return saved

    async def _refresh_live_signal_rows_fixed(rows):
        """Refresh signals without using pre-entry prices from the signal day."""
        if not rows:
            return []

        sem = asyncio.Semaphore(6)

        async with httpx.AsyncClient(timeout=25) as client:
            async def one(row):
                async with sem:
                    r = dict(row)
                    symbol = r["symbol"]
                    signal_date = r["signal_date"]
                    entry = float(r["entry"] or 0)
                    stop = float(r["stop"] or 0) if r["stop"] else None
                    t1 = float(r["target1"] or 0) if r["target1"] else None
                    t2 = float(r["target2"] or 0) if r["target2"] else None
                    hit1 = bool(r["hit1"])
                    hit2 = bool(r["hit2"])
                    stopped = bool(r["stopped"])

                    price_task = asyncio.create_task(mod._latest_price_for_signal(client, symbol))
                    signal_day_task = asyncio.create_task(mod._fetch_minute_window(client, symbol, signal_date, mod.ALPACA_FEED)) if (mod.ALPACA_KEY and mod.ALPACA_SECRET) else None
                    daily_task = asyncio.create_task(mod._bars_since_signal(client, symbol, signal_date))

                    price = await price_task
                    minute_bars = await signal_day_task if signal_day_task else []
                    daily_bars = await daily_task

                    try:
                        created_local = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00")).astimezone(mod.NY)
                    except Exception:
                        created_local = None

                    ordered = []
                    for b in minute_bars:
                        dt = mod._bar_dt(b)
                        if not dt or dt.date().isoformat() != signal_date:
                            continue
                        if created_local and dt < created_local:
                            continue
                        ordered.append((dt, b, "minute"))

                    for b in daily_bars:
                        dt = mod._bar_dt(b)
                        if not dt or dt.date().isoformat() <= signal_date:
                            continue
                        ordered.append((dt, b, "daily"))

                    ordered.sort(key=lambda z: z[0])
                    highs = []
                    lows = []
                    terminal = hit2 or stopped
                    for _, b, _granularity in ordered:
                        hi = float(b.get("h") or 0)
                        lo = float(b.get("l") or 0)
                        if hi > 0:
                            highs.append(hi)
                        if lo > 0:
                            lows.append(lo)
                        if terminal:
                            continue
                        if stop and lo > 0 and lo <= stop and not hit1:
                            stopped = True
                            terminal = True
                            continue
                        if t1 and hi >= t1:
                            hit1 = True
                        if t2 and hi >= t2:
                            hit2 = True
                            terminal = True

                    if hit2:
                        status = "target2"
                    elif stopped:
                        status = "stopped"
                    elif hit1:
                        status = "target1"
                    else:
                        status = "open"

                    maxret = ((max(highs) / entry - 1) * 100) if highs and entry else None
                    minret = ((min(lows) / entry - 1) * 100) if lows and entry else None
                    curret = ((price / entry - 1) * 100) if price and entry else None
                    if hit2:
                        rr = 2.5
                    elif stopped:
                        rr = -1.0
                    else:
                        rr = None

                    r.update({
                        "last_price": price,
                        "hit1": int(hit1),
                        "hit2": int(hit2),
                        "stopped": int(stopped),
                        "status": status,
                        "max_return_pct": maxret,
                        "min_return_pct": minret,
                        "current_return_pct": curret,
                        "result_r": rr,
                        "last_checked_at": datetime.now(timezone.utc).isoformat(),
                    })
                    return r

            return await asyncio.gather(*[one(row) for row in rows])

    mod._persist_scanner_signals = _persist_scanner_signals_fixed
    mod._refresh_live_signal_rows = _refresh_live_signal_rows_fixed
