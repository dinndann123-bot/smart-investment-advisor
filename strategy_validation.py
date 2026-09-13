import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

NY = ZoneInfo("America/New_York")
DEFAULT_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","TSLA","AMD","AVGO","PLTR","HOOD",
    "COIN","MARA","RIOT","SMCI","SOFI","RIVN","IONQ","SOUN","RKLB","APP",
    "MU","ARM","MRVL","CRWD","SNOW","UBER","AFRM","UPST","CVNA","NFLX",
]

MODELS = {
    "balanced": {"momentum": 0.25, "rvol": 0.30, "liquidity": 0.15, "structure": 0.20, "price": 0.10},
    "volume_heavy": {"momentum": 0.20, "rvol": 0.40, "liquidity": 0.15, "structure": 0.15, "price": 0.10},
    "momentum_heavy": {"momentum": 0.40, "rvol": 0.25, "liquidity": 0.10, "structure": 0.15, "price": 0.10},
    "structure_heavy": {"momentum": 0.20, "rvol": 0.25, "liquidity": 0.15, "structure": 0.30, "price": 0.10},
}


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _component_scores(change_pct, rvol, est_daily_volume, price, strength):
    # All components are computed from data available before 10:00 New York time.
    momentum = 100 * _clamp((change_pct - 1.0) / 11.0) if change_pct is not None else 0
    rvol_s = 100 * _clamp((rvol - 0.8) / 3.2) if rvol is not None else 0
    if est_daily_volume >= 5_000_000:
        liquidity = 100
    elif est_daily_volume >= 2_000_000:
        liquidity = 85
    elif est_daily_volume >= 750_000:
        liquidity = 65
    elif est_daily_volume >= 250_000:
        liquidity = 40
    else:
        liquidity = 10
    structure = 100 * _clamp((strength - 0.35) / 0.60) if strength is not None else 0
    if 2 <= price <= 100:
        price_s = 100
    elif 1 <= price < 2 or 100 < price <= 250:
        price_s = 65
    else:
        price_s = 25
    return {
        "momentum": momentum,
        "rvol": rvol_s,
        "liquidity": liquidity,
        "structure": structure,
        "price": price_s,
    }


def _model_score(components, weights, change_pct, rvol, est_daily_volume, price):
    score = sum(components[k] * weights[k] for k in weights)
    # Risk/extension penalties are intentionally simple and visible.
    if change_pct > 25:
        score -= 10
    if change_pct > 45:
        score -= 10
    if price < 1:
        score -= 15
    if est_daily_volume < 150_000:
        score -= 12
    if rvol is not None and rvol < 1:
        score -= 8
    return int(round(max(0, min(100, score))))


def _parse_bar(b):
    ts = datetime.fromisoformat(str(b.get("t", "")).replace("Z", "+00:00")).astimezone(NY)
    return {
        "ts": ts,
        "o": float(b.get("o") or 0),
        "h": float(b.get("h") or 0),
        "l": float(b.get("l") or 0),
        "c": float(b.get("c") or 0),
        "v": float(b.get("v") or 0),
    }


async def _fetch_symbol_days(client, symbol, headers, feed, days):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 15)
    r = await client.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
        headers=headers,
        params={
            "timeframe": "15Min",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "adjustment": "split",
            "feed": feed,
            "sort": "asc",
        },
    )
    if r.status_code >= 400:
        return [], f"{symbol}: HTTP {r.status_code}"
    raw = (r.json() or {}).get("bars") or []
    grouped = defaultdict(list)
    for b in raw:
        try:
            x = _parse_bar(b)
            t = x["ts"].time()
            if dtime(9, 30) <= t < dtime(16, 0):
                grouped[x["ts"].date().isoformat()].append(x)
        except Exception:
            continue
    days_out = []
    for d in sorted(grouped):
        arr = sorted(grouped[d], key=lambda x: x["ts"])
        if len(arr) >= 8:
            days_out.append((d, arr))
    return days_out[-days:], None


def _build_events(symbol, symbol_days):
    events = []
    prior_early_volumes = []
    for day, bars in symbol_days:
        early = [b for b in bars if b["ts"].time() < dtime(10, 0)]
        post = [b for b in bars if b["ts"].time() >= dtime(10, 0)]
        if len(early) < 2 or len(post) < 4:
            continue
        early_vol = sum(b["v"] for b in early)
        baseline = statistics.median(prior_early_volumes[-10:]) if len(prior_early_volumes) >= 5 else None
        rvol = early_vol / baseline if baseline and baseline > 0 else None
        prior_early_volumes.append(early_vol)
        if rvol is None:
            continue
        open_px = early[0]["o"] or early[0]["c"]
        cutoff_px = early[-1]["c"]
        if open_px <= 0 or cutoff_px <= 0:
            continue
        change_pct = (cutoff_px / open_px - 1) * 100
        lo = min(b["l"] for b in early if b["l"] > 0)
        hi = max(b["h"] for b in early)
        strength = (cutoff_px - lo) / (hi - lo) if hi > lo else 0.5
        # 30 minutes observed out of a 6.5h regular session.
        est_daily_volume = early_vol * 13
        components = _component_scores(change_pct, rvol, est_daily_volume, cutoff_px, strength)
        scores = {name: _model_score(components, w, change_pct, rvol, est_daily_volume, cutoff_px) for name, w in MODELS.items()}
        max_up = (max(b["h"] for b in post) / cutoff_px - 1) * 100
        max_down = (min(b["l"] for b in post) / cutoff_px - 1) * 100
        close_ret = (post[-1]["c"] / cutoff_px - 1) * 100
        events.append({
            "symbol": symbol,
            "date": day,
            "price_1000": round(cutoff_px, 4),
            "change_1000_pct": round(change_pct, 3),
            "rvol_1000": round(rvol, 3),
            "structure": round(strength, 3),
            "est_daily_volume": int(est_daily_volume),
            "scores": scores,
            "max_up_after_1000_pct": round(max_up, 3),
            "max_down_after_1000_pct": round(max_down, 3),
            "close_after_1000_pct": round(close_ret, 3),
            "exploded_5pct": max_up >= 5.0,
            "quality_win": max_up >= 5.0 and max_down > -3.5,
        })
    return events


def _metrics(events, model, threshold):
    picks = [e for e in events if e["scores"][model] >= threshold]
    if not picks:
        return {"signals": 0, "hit_rate_pct": None, "quality_rate_pct": None, "avg_max_up_pct": None, "avg_drawdown_pct": None, "avg_close_pct": None}
    return {
        "signals": len(picks),
        "hit_rate_pct": round(100 * sum(e["exploded_5pct"] for e in picks) / len(picks), 2),
        "quality_rate_pct": round(100 * sum(e["quality_win"] for e in picks) / len(picks), 2),
        "avg_max_up_pct": round(statistics.mean(e["max_up_after_1000_pct"] for e in picks), 2),
        "avg_drawdown_pct": round(statistics.mean(e["max_down_after_1000_pct"] for e in picks), 2),
        "avg_close_pct": round(statistics.mean(e["close_after_1000_pct"] for e in picks), 2),
    }


def _choose_model(train):
    best = None
    for model in MODELS:
        for threshold in (60, 65, 70, 75, 80):
            m = _metrics(train, model, threshold)
            if m["signals"] < 10 or m["hit_rate_pct"] is None:
                continue
            # Precision first, then upside, while mildly penalizing deep drawdown.
            utility = m["hit_rate_pct"] + 1.5 * m["avg_max_up_pct"] + 0.5 * m["avg_drawdown_pct"]
            row = {"model": model, "threshold": threshold, "utility": round(utility, 3), "train": m}
            if best is None or row["utility"] > best["utility"]:
                best = row
    if best is None:
        best = {"model": "balanced", "threshold": 70, "utility": None, "train": _metrics(train, "balanced", 70)}
    return best


def _buckets(events, model):
    specs = [(0, 59), (60, 69), (70, 79), (80, 89), (90, 100)]
    out = []
    for lo, hi in specs:
        arr = [e for e in events if lo <= e["scores"][model] <= hi]
        if not arr:
            out.append({"bucket": f"{lo}-{hi}", "samples": 0, "hit_rate_pct": None, "avg_max_up_pct": None})
            continue
        out.append({
            "bucket": f"{lo}-{hi}",
            "samples": len(arr),
            "hit_rate_pct": round(100 * sum(e["exploded_5pct"] for e in arr) / len(arr), 2),
            "avg_max_up_pct": round(statistics.mean(e["max_up_after_1000_pct"] for e in arr), 2),
        })
    return out


def install_strategy_validation(app):
    @app.get("/api/strategy/validate")
    async def validate_strategy(
        days: int = Query(60, ge=20, le=120),
        symbols: int = Query(20, ge=8, le=30),
    ):
        key = os.getenv("ALPACA_API_KEY", "").strip()
        secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
        feed = os.getenv("ALPACA_FEED", "iex").strip().lower() or "iex"
        if not key or not secret:
            raise HTTPException(503, "Alpaca לא מוגדר")
        if feed not in {"iex", "sip", "delayed_sip"}:
            feed = "iex"
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        universe = DEFAULT_UNIVERSE[:symbols]
        all_events = []
        errors = []
        async with httpx.AsyncClient(timeout=35) as client:
            for symbol in universe:
                try:
                    sdays, err = await _fetch_symbol_days(client, symbol, headers, feed, days)
                    if err:
                        errors.append(err)
                        continue
                    all_events.extend(_build_events(symbol, sdays))
                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")
        if len(all_events) < 25:
            raise HTTPException(503, f"אין מספיק דגימות לאימות אמין כרגע ({len(all_events)}).")
        all_events.sort(key=lambda e: (e["date"], e["symbol"]))
        unique_dates = sorted({e["date"] for e in all_events})
        split_idx = max(1, int(len(unique_dates) * 0.70))
        split_date = unique_dates[min(split_idx, len(unique_dates)-1)]
        train = [e for e in all_events if e["date"] < split_date]
        test = [e for e in all_events if e["date"] >= split_date]
        chosen = _choose_model(train)
        test_metrics = _metrics(test, chosen["model"], chosen["threshold"])
        baseline_hit = round(100 * sum(e["exploded_5pct"] for e in test) / len(test), 2) if test else None
        lift = round(test_metrics["hit_rate_pct"] / baseline_hit, 2) if baseline_hit and test_metrics["hit_rate_pct"] is not None else None
        top_test = sorted(test, key=lambda e: e["scores"][chosen["model"]], reverse=True)[:20]
        return {
            "ok": True,
            "method": "walk-forward holdout",
            "cutoff_ny": "10:00",
            "feed": feed,
            "days_requested": days,
            "symbols_tested": universe,
            "samples": {"total": len(all_events), "train": len(train), "test": len(test), "split_date": split_date},
            "baseline_test_hit_rate_pct": baseline_hit,
            "selected": {
                "model": chosen["model"],
                "threshold": chosen["threshold"],
                "weights": MODELS[chosen["model"]],
                "train": chosen["train"],
                "test": test_metrics,
                "lift_vs_baseline": lift,
            },
            "score_buckets_test": _buckets(test, chosen["model"]),
            "top_test_signals": top_test,
            "errors": errors[:20],
            "limitations": [
                "האימות משתמש רק במידע שוק שהיה זמין עד 10:00 ניו יורק; אין look-ahead בתכונות.",
                "חדשות היסטוריות אינן נכנסות לכיול הזה ולכן שכבת הקטליזטור נשארת גורם אישור נפרד ולא משקל שעבר אופטימיזציה.",
                "IEX הוא feed חלקי לעומת SIP; RVOL מחושב יחסית לעצמו ולכן שימושי, אך נפח מוחלט פחות מייצג את כלל השוק.",
                "זהו אימות סטטיסטי של סינון, לא הבטחת תשואה ולא סימולציית ביצוע מלאה עם slippage/fees.",
            ],
        }
