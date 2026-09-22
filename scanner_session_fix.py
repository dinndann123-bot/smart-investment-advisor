"""Session-aware scanner market-data layer.

Premarket uses Alpaca's delayed consolidated SIP bars (ending 16 minutes behind
wall clock) so ranking is based on actual extended-hours trades instead of a
stale IEX snapshot. Regular-session behavior remains on the configured live
feed. Ranking policy itself is unchanged.
"""
from datetime import datetime, timedelta, timezone

VERSION = "scanner-session-data-v2-sip-premarket"


def install(core):
    previous_enrich = core.enrich
    previous_bars = core.bars
    f = core.f
    NY = core.NY

    async def session_bars(symbol, client):
        now_utc = datetime.now(timezone.utc)
        now = now_utc.astimezone(NY)
        cur = now.hour * 60 + now.minute
        if 240 <= cur < 570:
            # Alpaca permits historical consolidated SIP on the current plan,
            # but the most recent SIP data must remain delayed. Fetch enough
            # history for the same-clock five-session RVOL baseline.
            end = now_utc - timedelta(minutes=16)
            start = now_utc - timedelta(days=10)
            try:
                response = await client.get(
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                    headers=core.hdr(),
                    params={
                        "timeframe": "5Min",
                        "start": start.isoformat().replace("+00:00", "Z"),
                        "end": end.isoformat().replace("+00:00", "Z"),
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
        now = datetime.now(timezone.utc).astimezone(NY)
        cur = now.hour * 60 + now.minute
        try:
            source_time = datetime.fromisoformat(str(row.get("market_timestamp")).replace("Z", "+00:00")).astimezone(NY)
        except (TypeError, ValueError):
            source_time = None

        if cur < 240:
            session, window_start = "overnight_closed", None
        elif cur < 570:
            session, window_start = "premarket", 240
        elif cur < 960:
            session, window_start = "regular", 570
        elif cur < 1200:
            session, window_start = "afterhours", 960
        else:
            session, window_start = "overnight_closed", None

        by_day = {}
        for bar in bars or []:
            try:
                z = datetime.fromisoformat(str(bar.get("t")).replace("Z", "+00:00")).astimezone(NY)
                by_day.setdefault(z.date(), []).append((z, bar))
            except Exception:
                continue

        today = by_day.get(now.date(), [])
        today_window, hist = [], []
        if window_start is not None:
            for day, items in by_day.items():
                selected = [(z, b) for z, b in items if window_start <= z.hour * 60 + z.minute <= cur]
                if day == now.date():
                    today_window = selected
                else:
                    volume = sum(f((b or {}).get("v")) for _, b in selected)
                    if volume > 0:
                        hist.append(volume)

        baseline = sum(hist[-5:]) / len(hist[-5:]) if hist else 0.0
        live_window_volume = sum(f((b or {}).get("v")) for _, b in today_window)

        # In premarket the delayed SIP bars are the authoritative price/volume
        # source. Do not mix yesterday's IEX snapshot price with today's SIP RVOL.
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
                row["market_timestamp_current_day"] = True
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

        row["market_timestamp_current_day"] = bool(source_time and source_time.date() == now.date())
        live_for_rvol = live_window_volume if live_window_volume > 0 else f(row.get("day_volume"))
        rvol = live_for_rvol / baseline if baseline > 0 else None
        row["market_session"] = session
        row["today_bars_count"] = len(today)
        row["session_bars_count"] = len(today_window)
        row["clock_baseline_volume"] = round(baseline) if baseline > 0 else None
        row["historical_baseline_volume"] = round(baseline) if baseline > 0 else row.get("historical_baseline_volume")
        row["clock_live_volume"] = round(live_window_volume) if live_window_volume > 0 else None
        row["rvol_basis"] = "same_clock_5day" if baseline > 0 and live_window_volume > 0 else "snapshot_fallback"

        if not row["market_timestamp_current_day"] and not today_window:
            row["data_freshness_status"] = "previous_session_snapshot"
            row["rvol"] = row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["minute_volume_burst"] = None
            row["today_bars_count"] = 0
            return row
        if session == "overnight_closed":
            row["rvol"] = row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["minute_volume_burst"] = None
            row["data_freshness_status"] = "waiting_for_premarket"
        elif rvol is not None:
            row["rvol_raw"] = round(rvol, 2)
            row["rvol"] = round(min(rvol, 25.0), 2)
            row["rvol_capped"] = rvol > 25.0
            row["rvol_reliable"] = bool(baseline >= 1000 and live_for_rvol >= 1000)
            row["data_freshness_status"] = "delayed_sip_bars" if session == "premarket" and today_window else ("live_bars" if today_window else "snapshot_fallback")
        else:
            row["rvol"] = row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["data_freshness_status"] = "insufficient_clock_baseline"
        return row

    core.bars = session_bars
    core.enrich = enrich_session_aware
    core.SCANNER_SESSION_DATA_FIX = {
        "installed": True,
        "version": VERSION,
        "premarket_source": "Alpaca delayed consolidated SIP",
        "premarket_delay_minutes": 16,
        "premarket_window_et": "04:00-current-minus-delay",
        "regular_window_et": "09:30-current",
        "ranking_weights_changed": False,
    }
    print(f"SCANNER_SESSION_FIX_INSTALLED version={VERSION}", flush=True)
    return core.SCANNER_SESSION_DATA_FIX
