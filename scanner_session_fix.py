"""Session-aware scanner data repair.

Keeps the existing ranking policy intact.  This module only repairs the time
window used for live/historical volume comparisons and makes overnight vs
premarket vs regular-session coverage explicit.
"""
from datetime import datetime, timezone

VERSION = "scanner-session-data-v1"


def install(core):
    previous_enrich = core.enrich
    f = core.f
    NY = core.NY

    def enrich_session_aware(row, bars):
        # Preserve every existing enrichment/quality-guard field first.
        row = previous_enrich(row, bars)
        now = datetime.now(timezone.utc).astimezone(NY)
        cur = now.hour * 60 + now.minute
        try:
            source_time = datetime.fromisoformat(str(row.get('market_timestamp')).replace('Z', '+00:00')).astimezone(NY)
        except (TypeError, ValueError):
            source_time = None
        row['market_timestamp_current_day'] = bool(source_time and source_time.date() == now.date())

        if cur < 240:
            session = "overnight_closed"
            window_start = None
        elif cur < 570:
            session = "premarket"
            window_start = 240
        elif cur < 960:
            session = "regular"
            window_start = 570
        elif cur < 1200:
            session = "afterhours"
            window_start = 960
        else:
            session = "overnight_closed"
            window_start = None

        by_day = {}
        for bar in bars or []:
            try:
                z = datetime.fromisoformat(str(bar.get("t")).replace("Z", "+00:00")).astimezone(NY)
                by_day.setdefault(z.date(), []).append((z, bar))
            except Exception:
                continue

        today = by_day.get(now.date(), [])
        today_window = []
        hist = []
        if window_start is not None:
            for d, items in by_day.items():
                selected = [(z, b) for z, b in items if window_start <= z.hour * 60 + z.minute <= cur]
                if d == now.date():
                    today_window = selected
                else:
                    vol = sum(f((b or {}).get("v")) for _, b in selected)
                    if vol > 0:
                        hist.append(vol)

        baseline = sum(hist[-5:]) / len(hist[-5:]) if hist else 0.0
        live_window_volume = sum(f((b or {}).get("v")) for _, b in today_window)
        # During PM/regular hours prefer like-for-like clock volume.  Snapshot
        # cumulative volume is a fallback only when current bars are missing.
        live_for_rvol = live_window_volume if live_window_volume > 0 else f(row.get("day_volume"))
        rvol = live_for_rvol / baseline if baseline > 0 else None

        row["market_session"] = session
        row["today_bars_count"] = len(today)
        row["session_bars_count"] = len(today_window)
        row["clock_baseline_volume"] = round(baseline) if baseline > 0 else None
        row["clock_live_volume"] = round(live_window_volume) if live_window_volume > 0 else None
        row["rvol_basis"] = "same_clock_5day" if baseline > 0 and live_window_volume > 0 else "snapshot_fallback"

        if not row['market_timestamp_current_day'] and not today_window:
            row['data_freshness_status'] = 'previous_session_snapshot'
            row['rvol'] = None
            row['rvol_raw'] = None
            row['rvol_reliable'] = False
            row['minute_volume_burst'] = None
            row['today_bars_count'] = 0
            return row

        if session == "overnight_closed":
            # Zero bars before 04:00 ET is expected, not a feed failure and not
            # a predictive signal.  Never manufacture PM information here.
            row["rvol"] = None
            row["rvol_raw"] = None
            row["rvol_reliable"] = False
            row["minute_volume_burst"] = None
            row["data_freshness_status"] = "waiting_for_premarket"
        elif rvol is not None:
            row["rvol_raw"] = round(rvol, 2)
            row["rvol"] = round(min(rvol, 25.0), 2)
            row["rvol_capped"] = rvol > 25.0
            row["rvol_reliable"] = bool(baseline >= 1000 and live_for_rvol >= 1000)
            row["data_freshness_status"] = "live_bars" if today_window else "snapshot_fallback"
        else:
            row["rvol_reliable"] = False
            row["data_freshness_status"] = "insufficient_clock_baseline"

        return row

    core.enrich = enrich_session_aware
    core.SCANNER_SESSION_DATA_FIX = {
        "installed": True,
        "version": VERSION,
        "premarket_window_et": "04:00-current",
        "regular_window_et": "09:30-current",
        "overnight_zero_bars_expected": True,
        "ranking_weights_changed": False,
    }
    print(f"SCANNER_SESSION_FIX_INSTALLED version={VERSION}", flush=True)
    return core.SCANNER_SESSION_DATA_FIX
