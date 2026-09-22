"""Session-aware scanner market-data layer.

Premarket uses Alpaca delayed consolidated SIP bars. All premarket freshness,
price, volume and RVOL calculations use the same delayed market-data clock so
the scanner never compares a delayed bar with wall-clock time or a stale IEX
snapshot. Regular-session behavior remains on the configured live feed.
"""
from datetime import datetime, timedelta, timezone

VERSION = "scanner-session-data-v3-sip-delayed-clock"
SIP_DELAY_MINUTES = 16


def install(core):
    previous_enrich = core.enrich
    previous_bars = core.bars
    f = core.f
    NY = core.NY

    def clocks():
        wall_utc = datetime.now(timezone.utc)
        wall_ny = wall_utc.astimezone(NY)
        market_utc = wall_utc - timedelta(minutes=SIP_DELAY_MINUTES)
        market_ny = market_utc.astimezone(NY)
        return wall_utc, wall_ny, market_utc, market_ny

    async def session_bars(symbol, client):
        wall_utc, wall_ny, market_utc, market_ny = clocks()
        cur = wall_ny.hour * 60 + wall_ny.minute
        if 240 <= cur < 570:
            start = market_utc - timedelta(days=10)
            try:
                response = await client.get(
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                    headers=core.hdr(),
                    params={
                        "timeframe": "5Min",
                        "start": start.isoformat().replace("+00:00", "Z"),
                        "end": market_utc.isoformat().replace("+00:00", "Z"),
                        "feed": "sip",
                        "adjustment": "split",
                        "limit": 5000,
                    },
                )
                if response.status_code < 400:
                    return (response.json() or {}).get("bars") or []
            except Exception:
                pass
        return await previous_bars(symbol, client)

    def enrich_session_aware(row, bars):
        row = previous_enrich(row, bars)
        wall_utc, wall_ny, market_utc, market_ny = clocks()
        wall_cur = wall_ny.hour * 60 + wall_ny.minute

        if wall_cur < 240:
            session, window_start, clock_now = "overnight_closed", None, wall_ny
        elif wall_cur < 570:
            # Delayed SIP is authoritative in premarket. Its own clock determines
            # both today's window and the historical same-clock comparison.
            session, window_start, clock_now = "premarket", 240, market_ny
        elif wall_cur < 960:
            session, window_start, clock_now = "regular", 570, wall_ny
        elif wall_cur < 1200:
            session, window_start, clock_now = "afterhours", 960, wall_ny
        else:
            session, window_start, clock_now = "overnight_closed", None, wall_ny

        clock_cur = clock_now.hour * 60 + clock_now.minute
        by_day = {}
        for bar in bars or []:
            try:
                z = datetime.fromisoformat(str(bar.get("t")).replace("Z", "+00:00")).astimezone(NY)
                by_day.setdefault(z.date(), []).append((z, bar))
            except Exception:
                continue

        today = by_day.get(clock_now.date(), [])
        today_window, hist = [], []
        if window_start is not None and clock_cur >= window_start:
            for day, items in by_day.items():
                selected = [(z, b) for z, b in items if window_start <= z.hour * 60 + z.minute <= clock_cur]
                if day == clock_now.date():
                    today_window = selected
                else:
                    volume = sum(f((b or {}).get("v")) for _, b in selected)
                    if volume > 0:
                        hist.append(volume)

        baseline = sum(hist[-5:]) / len(hist[-5:]) if hist else 0.0
        live_window_volume = sum(f((b or {}).get("v")) for _, b in today_window)
        source_time = None

        if session == "premarket" and today_window:
            latest_z, latest = today_window[-1]
            closes = [f(b.get("c")) for _, b in today_window if f(b.get("c")) > 0]
            highs = [f(b.get("h")) for _, b in today_window if f(b.get("h")) > 0]
            lows = [f(b.get("l")) for _, b in today_window if f(b.get("l")) > 0]
            price = f(latest.get("c"))
            prev = f(row.get("prev_close"))
            if price > 0:
                row["price"] = round(price, 4)
                row["market_timestamp"] = latest.get("t")
                row["data_feed"] = "sip_delayed"
                row["data_source"] = "Alpaca SIP delayed"
                row["day_volume"] = live_window_volume
                if prev > 0:
                    row["change_pct"] = round((price / prev - 1) * 100, 2)
                if highs and lows:
                    hi, lo = max(highs), min(lows)
                    row["day_high"], row["day_low"] = hi, lo
                    row["current_range_position"] = round((price - lo) / (hi - lo), 3) if hi > lo else 0.5
                    row["intraday_move_used_pct"] = round((price - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0
            source_time = latest_z
        else:
            try:
                source_time = datetime.fromisoformat(str(row.get("market_timestamp")).replace("Z", "+00:00")).astimezone(NY)
            except (TypeError, ValueError):
                source_time = None

        current_day = bool(source_time and source_time.date() == clock_now.date())
        row["market_timestamp_current_day"] = current_day
        row["market_session"] = session
        row["today_bars_count"] = len(today)
        row["session_bars_count"] = len(today_window)
        row["market_data_clock"] = clock_now.isoformat()
        row["market_data_delay_minutes"] = SIP_DELAY_MINUTES if session == "premarket" else 0
        row["clock_baseline_volume"] = round(baseline) if baseline > 0 else None
        row["historical_baseline_volume"] = round(baseline) if baseline > 0 else row.get("historical_baseline_volume")
        row["clock_live_volume"] = round(live_window_volume) if live_window_volume > 0 else None

        if session == "premarket":
            # No same-day SIP trades means no reliable premarket signal. Keep the
            # candidate for research/watch purposes, but do not manufacture RVOL
            # from yesterday's snapshot volume.
            if not today_window:
                row["data_freshness_status"] = "no_premarket_sip_trades"
                row["rvol"] = row["rvol_raw"] = None
                row["rvol_reliable"] = False
                row["minute_volume_burst"] = None
                row["rvol_basis"] = "unavailable"
                return row
            rvol = live_window_volume / baseline if baseline > 0 else None
            row["rvol_basis"] = "same_delayed_clock_5day" if rvol is not None else "insufficient_clock_baseline"
            if rvol is not None:
                row["rvol_raw"] = round(rvol, 2)
                row["rvol"] = round(min(rvol, 25.0), 2)
                row["rvol_capped"] = rvol > 25.0
                row["rvol_reliable"] = bool(baseline >= 1000 and live_window_volume >= 1000)
                row["data_freshness_status"] = "delayed_sip_bars"
            else:
                row["rvol"] = row["rvol_raw"] = None
                row["rvol_reliable"] = False
                row["data_freshness_status"] = "insufficient_clock_baseline"
            return row

        if not current_day and not today_window:
            row["data_freshness_status"] = "previous_session_snapshot"
            row["rvol"] = row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["minute_volume_burst"] = None
            row["today_bars_count"] = 0
        elif session == "overnight_closed":
            row["rvol"] = row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["minute_volume_burst"] = None
            row["data_freshness_status"] = "waiting_for_premarket"
        return row

    core.bars = session_bars
    core.enrich = enrich_session_aware
    core.SCANNER_SESSION_DATA_FIX = {
        "installed": True,
        "version": VERSION,
        "premarket_source": "Alpaca delayed consolidated SIP",
        "premarket_delay_minutes": SIP_DELAY_MINUTES,
        "premarket_clock": "source-clock-authoritative",
        "ranking_weights_changed": False,
    }
    print(f"SCANNER_SESSION_FIX_INSTALLED version={VERSION}", flush=True)
    return core.SCANNER_SESSION_DATA_FIX
