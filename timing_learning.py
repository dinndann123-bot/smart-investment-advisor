"""Timing-learning engine for intraday signals.
Measures entry windows, MFE/MAE and peak timing without changing the existing score yet.
"""
from datetime import time as dtime
import statistics

ENTRY_WINDOWS = [
    ("09:30", dtime(9,30)),
    ("09:35", dtime(9,35)),
    ("09:45", dtime(9,45)),
    ("10:00", dtime(10,0)),
]


def _pct(a, b):
    return ((b / a) - 1) * 100 if a and b else None


def _first_at_or_after(bars, clock):
    return next((b for b in bars if b["ts"].time() >= clock), None)


def measure_entry_window(bars, label, clock):
    entry = _first_at_or_after(bars, clock)
    if not entry:
        return None
    later = [b for b in bars if b["ts"] >= entry["ts"]]
    if not later or entry["c"] <= 0:
        return None
    peak = max(later, key=lambda b: b["h"])
    trough = min(later, key=lambda b: b["l"])
    mfe = _pct(entry["c"], peak["h"])
    mae = _pct(entry["c"], trough["l"])
    minutes_to_peak = max(0, (peak["ts"] - entry["ts"]).total_seconds() / 60)
    close_return = _pct(entry["c"], later[-1]["c"])
    return {
        "entry_window_ny": label,
        "entry_time": entry["ts"].isoformat(),
        "entry_price": round(entry["c"], 4),
        "peak_time": peak["ts"].isoformat(),
        "peak_price": round(peak["h"], 4),
        "trough_time": trough["ts"].isoformat(),
        "trough_price": round(trough["l"], 4),
        "mfe_pct": round(mfe, 3) if mfe is not None else None,
        "mae_pct": round(mae, 3) if mae is not None else None,
        "minutes_to_peak": round(minutes_to_peak, 1),
        "close_return_pct": round(close_return, 3) if close_return is not None else None,
    }


def measure_day_timing(bars):
    return [x for label, clock in ENTRY_WINDOWS if (x := measure_entry_window(bars, label, clock))]


def summarize_timing(events):
    """Summarize only completed historical events; suitable for train/holdout reporting."""
    by_window = {}
    for event in events:
        for row in event.get("timing_windows") or []:
            by_window.setdefault(row["entry_window_ny"], []).append(row)
    out = []
    for label, rows in sorted(by_window.items()):
        mfes = [r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]
        maes = [r["mae_pct"] for r in rows if r.get("mae_pct") is not None]
        peaks = [r["minutes_to_peak"] for r in rows if r.get("minutes_to_peak") is not None]
        closes = [r["close_return_pct"] for r in rows if r.get("close_return_pct") is not None]
        out.append({
            "entry_window_ny": label,
            "samples": len(rows),
            "median_mfe_pct": round(statistics.median(mfes), 3) if mfes else None,
            "median_mae_pct": round(statistics.median(maes), 3) if maes else None,
            "median_minutes_to_peak": round(statistics.median(peaks), 1) if peaks else None,
            "positive_close_pct": round(100 * sum(v > 0 for v in closes) / len(closes), 2) if closes else None,
        })
    return out
