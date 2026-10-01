"""End-of-day audit of strong movers the live Top-10 scanner did not capture.

Outcome observations are stored in the same durable learning store as scanner
signals so the audit survives a Render restart and can be compared by day.
"""

import asyncio
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
MOVE_THRESHOLD_PCT = 8.0
AUDIT_AFTER = time(16, 10)
AUDIT_LIMIT = 50
AUDIT_STORE_LIMIT = 30000


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_time(row):
    epoch = _f(row.get("epoch"))
    if epoch is not None and epoch > 0:
        return datetime.fromtimestamp(epoch, timezone.utc)
    raw = row.get("signal_time") or row.get("captured_at")
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (TypeError, ValueError):
        return None


def _top10_for_day(rows, trade_date, strategy_version):
    """Collapse repeated scan rows to each ticker's best rank for the day."""
    top = {}
    for row in rows:
        if row.get("record_type") not in (None, "scanner_signal", "scheduled_checkpoint"):
            continue
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        rank = _f(row.get("rank"))
        if not symbol or rank is None or not 1 <= rank <= 10:
            continue
        stamp = _row_time(row)
        if stamp is None or stamp.astimezone(NY).date().isoformat() != trade_date:
            continue
        # Older live scanner rows do not carry a strategy_version field. Their
        # timestamps identify today's currently deployed scanner. When a row
        # does carry a version, reject records from unrelated strategies.
        row_version = row.get("strategy_version")
        if row_version and row_version != strategy_version:
            continue
        old = top.get(symbol)
        if old is None:
            top[symbol] = {"rank": int(rank), "first_seen": stamp.isoformat()}
        else:
            old["rank"] = min(old["rank"], int(rank))
            old["first_seen"] = min(old["first_seen"], stamp.isoformat())
    return top


def _instrument(asset, symbol):
    name = str((asset or {}).get("name") or "").lower()
    sym = str(symbol or "").upper()
    if "warrant" in name or sym.endswith((".WS", "WS")) or (len(sym) >= 5 and sym.endswith("W")):
        return "warrant"
    if "right" in name or sym.endswith((".RT", "RT")) or (len(sym) >= 5 and sym.endswith("R")):
        return "right"
    if "unit" in name or sym.endswith(".U"):
        return "unit"
    if "preferred" in name or "depositary share" in name:
        return "preferred"
    if "etf" in name or "exchange traded fund" in name:
        return "etf"
    if "common stock" in name or "common share" in name or "ordinary share" in name:
        return "common_stock"
    return "other_equity"


def _eligible(asset, instrument):
    return bool(
        asset
        and asset.get("status") == "active"
        and asset.get("tradable") is True
        and instrument in ("common_stock", "other_equity")
    )


async def _request(core, url, *, params=None, timeout=20):
    import httpx
    headers = {
        "APCA-API-KEY-ID": core.ALPACA_KEY,
        "APCA-API-SECRET-KEY": core.ALPACA_SECRET,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(url, headers=headers, params=params)


async def _is_market_day(core, day):
    """Fail closed when Alpaca's calendar cannot verify this date."""
    try:
        response = await _request(
            core,
            "https://paper-api.alpaca.markets/v2/calendar",
            params={"start": day, "end": day},
        )
        if response.status_code >= 400:
            return None
        calendar = response.json() or []
        return any(str(item.get("date")) == day for item in calendar)
    except Exception:
        return None


async def _sip_movers(core, limit=AUDIT_LIMIT):
    requested = max(1, min(int(limit or AUDIT_LIMIT), AUDIT_LIMIT))
    try:
        response = await _request(
            core,
            "https://data.alpaca.markets/v1beta1/screener/stocks/movers",
            params={"top": requested},
            timeout=30,
        )
    except Exception as exc:
        return [], {"status": f"request_{type(exc).__name__}", "count": 0}
    if response.status_code >= 400:
        return [], {
            "status": f"http_{response.status_code}",
            "count": 0,
            "requested_top": requested,
            "body": (response.text or "")[:200],
        }
    data = response.json() or {}
    raw = data.get("gainers") or []
    out = []
    for item in raw:
        symbol = str(item.get("symbol") or "").upper().strip()
        move = _f(item.get("percent_change"))
        if symbol and move is not None:
            out.append({
                "symbol": symbol,
                "move_pct": move,
                "price": _f(item.get("price")),
                "change": _f(item.get("change")),
                "raw": item,
            })
    out.sort(key=lambda item: item["move_pct"], reverse=True)
    return out, {"status": "ok", "count": len(out), "raw_gainers": len(raw), "requested_top": requested}


async def _asset(core, symbol):
    try:
        response = await _request(
            core,
            f"https://paper-api.alpaca.markets/v2/assets/{symbol}",
            timeout=12,
        )
        return (response.json() or {}) if response.status_code < 400 else None
    except Exception:
        return None


async def _iex_snapshot(core, symbol):
    try:
        response = await _request(
            core,
            f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot",
            params={"feed": core.ALPACA_FEED},
            timeout=15,
        )
        return (response.json() or {}) if response.status_code < 400 else None
    except Exception:
        return None


def _snapshot_is_for_day(snapshot, day):
    for key in ("dailyBar", "latestTrade"):
        item = (snapshot or {}).get(key) or {}
        stamp = item.get("t")
        if not stamp:
            continue
        try:
            parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if parsed.astimezone(NY).date().isoformat() == day:
                return True
        except ValueError:
            continue
    return False


async def _premarket(core, symbol, day):
    params = {
        "timeframe": "1Min",
        "start": f"{day}T04:00:00-04:00",
        "end": f"{day}T09:30:00-04:00",
        "limit": 10000,
        "feed": core.ALPACA_FEED,
        "adjustment": "split",
        "sort": "asc",
    }
    try:
        response = await _request(
            core,
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            params=params,
            timeout=20,
        )
        bars = ((response.json() or {}).get("bars") or []) if response.status_code < 400 else []
    except Exception:
        bars = []
    if not bars:
        return {}
    lows = [_f(bar.get("l")) for bar in bars if _f(bar.get("l")) is not None]
    highs = [_f(bar.get("h")) for bar in bars if _f(bar.get("h")) is not None]
    return {
        "last": _f(bars[-1].get("c")),
        "volume": sum(_f(bar.get("v")) or 0 for bar in bars),
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "bars": len(bars),
    }


def _summary_from_reports(reports):
    eligible = sum(int(row.get("eligible_stock_movers") or 0) for row in reports)
    captured = sum(int(row.get("eligible_top10_overlap") or 0) for row in reports)
    missed = sum(int(row.get("eligible_false_negatives") or 0) for row in reports)
    return {
        "ok": True,
        "days": len(reports),
        "eligible_movers": eligible,
        "captured": captured,
        "missed": missed,
        "capture_rate_pct": round(captured / eligible * 100, 1) if eligible else None,
        "daily": reports,
    }


def _feature_group(rows):
    def average(key):
        values = [_f(row.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 3) if values else None

    ranges = []
    for row in rows:
        high = _f(row.get("premarket_high"))
        low = _f(row.get("premarket_low"))
        if high and low and low > 0:
            ranges.append((high / low - 1) * 100)
    return {
        "count": len(rows),
        "avg_move_pct": average("move_pct"),
        "avg_premarket_gap_pct": average("premarket_gap_pct"),
        "premarket_gap_coverage": sum(_f(row.get("premarket_gap_pct")) is not None for row in rows),
        "avg_premarket_volume": average("premarket_volume"),
        "premarket_volume_coverage": sum(_f(row.get("premarket_volume")) is not None for row in rows),
        "avg_premarket_range_pct": round(sum(ranges) / len(ranges), 3) if ranges else None,
        "verified_current_day": sum(bool(row.get("verified_current_day")) for row in rows),
    }


def install_missed_movers_learning(app, core, learning_store, strategy_version):
    state = {"last_run_day": None, "last_attempt_epoch": 0, "last_result": None, "last_error": None, "auto_task_started": False}

    async def run_audit(day, now=None):
        now = now or datetime.now(timezone.utc)
        local_now = now.astimezone(NY)
        result = {
            "record_type": "missed_mover_report",
            "ticker": "__DAILY_REPORT__",
            "rank": 0,
            "scan_id": f"missed-movers:{day}",
            "signal_time": now.isoformat(),
            "epoch": now.timestamp(),
            "trade_date": day,
            "strategy_version": strategy_version,
            "threshold_pct": MOVE_THRESHOLD_PCT,
            "status": "pending",
            "discovery_source": "alpaca_sip_market_movers",
            "point_in_time": True,
        }
        if day != local_now.date().isoformat() or local_now.time() < AUDIT_AFTER:
            result.update(status="waiting_for_completed_session", saved=0)
            return result
        state["last_attempt_epoch"] = now.timestamp()
        if not (getattr(core, "ALPACA_KEY", None) and getattr(core, "ALPACA_SECRET", None)):
            result.update(status="no_credentials", saved=0)
            _save_report(learning_store, result)
            state.update(last_run_day=day, last_result=result)
            return result
        market_day = await _is_market_day(core, day)
        if market_day is not True:
            result.update(status="market_calendar_unavailable" if market_day is None else "not_a_market_day", saved=0)
            _save_report(learning_store, result)
            state["last_result"] = result
            if market_day is False:
                state["last_run_day"] = day
            return result

        try:
            loader = getattr(learning_store, "load_by_type", None)
            if callable(loader):
                day_start = datetime.combine(datetime.fromisoformat(day).date(), time.min, NY).timestamp()
                stored_rows = loader("scanner_signal", since_epoch=day_start)
                stored_rows.extend(loader("scheduled_checkpoint", since_epoch=day_start))
            else:
                stored_rows = learning_store.load(AUDIT_STORE_LIMIT)
            top = _top10_for_day(stored_rows, day, strategy_version)
        except Exception as exc:
            result.update(status="scanner_history_unavailable", error=type(exc).__name__, saved=0)
            _save_report(learning_store, result)
            state["last_result"] = result
            return result
        if not top:
            result.update(status="no_scanner_history", scanner_top10_symbols=0, saved=0)
            _save_report(learning_store, result)
            state["last_result"] = result
            return result

        discovered, diag = await _sip_movers(core)
        if diag.get("status") != "ok":
            result.update(status="mover_feed_unavailable", discovery_diag=diag, scanner_top10_symbols=len(top), saved=0)
            _save_report(learning_store, result)
            state["last_result"] = result
            return result

        movers = [item for item in discovered if item["move_pct"] >= MOVE_THRESHOLD_PCT]
        eligible_count = captured_count = verified_count = saved = 0
        missed = []
        captured = []
        excluded = {}
        for item in movers:
            symbol = item["symbol"]
            asset = await _asset(core, symbol)
            instrument = _instrument(asset, symbol)
            eligible = _eligible(asset, instrument)
            if not eligible:
                excluded[instrument] = excluded.get(instrument, 0) + 1
                continue
            eligible_count += 1
            hit = top.get(symbol)
            if hit:
                captured_count += 1
            snapshot = await _iex_snapshot(core, symbol)
            verified = _snapshot_is_for_day(snapshot, day)
            if verified:
                verified_count += 1
            pm = await _premarket(core, symbol, day)
            previous_close = _f(((snapshot or {}).get("prevDailyBar") or {}).get("c"))
            pm_last = pm.get("last")
            pm_gap = (pm_last / previous_close - 1) * 100 if pm_last and previous_close else None
            row = {
                "record_type": "missed_mover_observation",
                "ticker": symbol,
                "rank": len(missed) + 1,
                "scan_id": f"missed-movers:{day}",
                "signal_time": now.isoformat(),
                "epoch": now.timestamp(),
                "trade_date": day,
                "strategy_version": strategy_version,
                "move_pct": round(item["move_pct"], 3),
                "price": item["price"],
                "volume": _f(((snapshot or {}).get("dailyBar") or {}).get("v")),
                "was_top10": bool(hit),
                "top10_best_rank": hit["rank"] if hit else None,
                "first_seen_top10": hit["first_seen"] if hit else None,
                "verified_current_day": verified,
                "asset_name": (asset or {}).get("name"),
                "instrument_type": instrument,
                "premarket_gap_pct": round(pm_gap, 3) if pm_gap is not None else None,
                "premarket_volume": pm.get("volume"),
                "premarket_high": pm.get("high"),
                "premarket_low": pm.get("low"),
                "premarket_last": pm_last,
                "discovery_source": "alpaca_sip_market_movers",
                "verification_feed": core.ALPACA_FEED,
            }
            learning_store.upsert(row)
            saved += 1
            observed = {
                "symbol": symbol,
                "name": row["asset_name"],
                "move_pct": round(item["move_pct"], 2),
                "rank": hit["rank"] if hit else None,
                "verified_current_day": verified,
                "premarket_gap_pct": row["premarket_gap_pct"],
                "premarket_volume": row["premarket_volume"],
                "premarket_high": row["premarket_high"],
                "premarket_low": row["premarket_low"],
            }
            (captured if hit else missed).append(observed)

        result.update(
            status="complete",
            threshold_pct=MOVE_THRESHOLD_PCT,
            top_movers_observed=len(movers),
            eligible_stock_movers=eligible_count,
            eligible_top10_overlap=captured_count,
            eligible_false_negatives=max(0, eligible_count - captured_count),
            capture_rate_pct=round(captured_count / eligible_count * 100, 1) if eligible_count else None,
            scanner_top10_symbols=len(top),
            excluded_instruments=excluded,
            verified_current_day=verified_count,
            captured_movers=captured,
            missed=missed,
            feature_comparison={"captured": _feature_group(captured), "missed": _feature_group(missed)},
            saved=saved,
            discovery_diag=diag,
            top10_capture_definition="Eligible Alpaca SIP gainers at or above threshold that appeared in any saved Top-10 scan for this trading date.",
            verification_note="IEX snapshot verification is reported separately and does not remove SIP-identified movers from the denominator.",
        )
        _save_report(learning_store, result)
        state.update(last_run_day=day, last_result=result, last_error=None)
        return result

    @app.post("/api/learning/missed-movers")
    async def missed_movers():
        now = datetime.now(timezone.utc)
        day = now.astimezone(NY).date().isoformat()
        return await run_audit(day, now)

    @app.get("/api/learning/missed-movers/summary")
    async def missed_summary(days: int = 30):
        loader = getattr(learning_store, "load_by_type", None)
        rows = loader("missed_mover_report", since_epoch=datetime.now(timezone.utc).timestamp() - 366 * 86400) if callable(loader) else learning_store.load(AUDIT_STORE_LIMIT)
        reports = [
            row for row in rows
            if row.get("record_type") == "missed_mover_report"
            and row.get("strategy_version") == strategy_version
            and row.get("status") == "complete"
        ]
        reports.sort(key=lambda row: row.get("trade_date") or "", reverse=True)
        selected = reports[:max(1, min(int(days or 30), 365))]
        return {
            **_summary_from_reports(selected),
            "strategy_version": strategy_version,
            "latest": selected[0] if selected else None,
            "auto_audit": {"after_new_york_close": AUDIT_AFTER.strftime("%H:%M"), "state": state},
        }

    async def daily_loop():
        state["auto_task_started"] = True
        while True:
            try:
                now = datetime.now(timezone.utc)
                local_now = now.astimezone(NY)
                day = local_now.date().isoformat()
                retry_ready = now.timestamp() - float(state.get("last_attempt_epoch") or 0) >= 300
                if local_now.weekday() < 5 and local_now.time() >= AUDIT_AFTER and state.get("last_run_day") != day and retry_ready:
                    await run_audit(day, now)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["last_error"] = type(exc).__name__
            await asyncio.sleep(60)

    @app.on_event("startup")
    async def _start_missed_mover_audit():
        if not state["auto_task_started"]:
            asyncio.create_task(daily_loop())

    return state


def _save_report(learning_store, report):
    learning_store.upsert(report)
