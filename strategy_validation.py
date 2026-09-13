import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

NY = ZoneInfo("America/New_York")

# A broad liquid/volatile US-equity universe. We deliberately include large caps,
# mid caps, recent momentum names and high-beta names. The validation selects
# candidates independently for EACH historical day using only data available by
# 10:00 New York time, which is much closer to how the live scanner behaves.
BROAD_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AMD","AVGO",
    "PLTR","HOOD","COIN","MARA","RIOT","SMCI","SOFI","RIVN","IONQ","SOUN",
    "RKLB","APP","MU","INTC","ARM","QCOM","MRVL","CRWD","NET","SNOW",
    "SHOP","UBER","PYPL","NFLX","ORCL","TSM","NIO","LCID","AFRM","UPST",
    "CVNA","DKNG","RBLX","PATH","AI","BBAI","QBTS","RGTI","QUBT","ACHR",
    "JOBY","LUNR","ASTS","RDW","SPCE","OPEN","CHPT","QS","LAZR","HIMS",
    "TEM","RXRX","VRT","DELL","ANET","PANW","DDOG","MDB","ZS","OKTA",
    "CELH","CAVA","RDDT","DUOL","TOST","NU","GRAB","PINS","SNAP","ROKU",
    "FUBO","GME","AMC","KOSS","BB","WULF","CLSK","IREN","CIFR","HUT",
    "BITF","BTDR","CORZ","MSTR","XYZ","SQ","RKT","LMND","ROOT","CVS",
    "WBD","PARA","T","F","GM","BAC","C","JPM","XOM","OXY"
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
    momentum = 100 * _clamp((change_pct - 0.5) / 12.0) if change_pct is not None else 0
    rvol_s = 100 * _clamp((rvol - 0.75) / 3.25) if rvol is not None else 0
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
    structure = 100 * _clamp((strength - 0.30) / 0.65) if strength is not None else 0
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
    if change_pct > 25:
        score -= 8
    if change_pct > 45:
        score -= 10
    if price < 1:
        score -= 15
    if est_daily_volume < 150_000:
        score -= 12
    if rvol is not None and rvol < 1:
        score -= 6
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


async def _fetch_symbol_days(client, symbol, headers, feed, calendar_days):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=calendar_days + 20)
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
    out = []
    for d in sorted(grouped):
        arr = sorted(grouped[d], key=lambda x: x["ts"])
        if len(arr) >= 8:
            out.append((d, arr))
    return out, None


def _build_symbol_events(symbol, symbol_days):
    events = []
    prior_early_volumes = []
    for day, bars in symbol_days:
        early = [b for b in bars if b["ts"].time() < dtime(10, 0)]
        post = [b for b in bars if b["ts"].time() >= dtime(10, 0)]
        if len(early) < 2 or len(post) < 4:
            continue
        early_vol = sum(b["v"] for b in early)
        baseline = statistics.median(prior_early_volumes[-20:]) if len(prior_early_volumes) >= 8 else None
        prior_early_volumes.append(early_vol)
        if not baseline or baseline <= 0:
            continue
        rvol = early_vol / baseline
        open_px = early[0]["o"] or early[0]["c"]
        cutoff_px = early[-1]["c"]
        if open_px <= 0 or cutoff_px <= 0:
            continue
        change_pct = (cutoff_px / open_px - 1) * 100
        lows = [b["l"] for b in early if b["l"] > 0]
        if not lows:
            continue
        lo = min(lows)
        hi = max(b["h"] for b in early)
        strength = (cutoff_px - lo) / (hi - lo) if hi > lo else 0.5
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
            "hit_2pct": max_up >= 2.0,
            "hit_3pct": max_up >= 3.0,
            "hit_5pct": max_up >= 5.0,
            "exploded_5pct": max_up >= 5.0,
            "quality_win": max_up >= 3.0 and max_down > -3.0,
        })
    return events


def _candidate_rank(e):
    # Uses ONLY information known by 10:00. This is intentionally separate from
    # the model score so the backtest can test whether the score adds value.
    momentum = max(0.0, min(30.0, e["change_1000_pct"]))
    rvol = max(0.0, min(6.0, e["rvol_1000"]))
    liq = min(5.0, e["est_daily_volume"] / 1_000_000)
    return momentum * 2.0 + rvol * 7.0 + liq * 2.0 + e["structure"] * 10.0


def _select_daily_universe(events, top_per_day=12, controls_per_day=8):
    by_day = defaultdict(list)
    for e in events:
        by_day[e["date"]].append(e)
    selected = []
    stats = []
    for day in sorted(by_day):
        arr = by_day[day]
        # Basic pre-10 eligibility only; no future return is used.
        eligible = [e for e in arr if e["price_1000"] >= 1 and e["est_daily_volume"] >= 100_000]
        if len(eligible) < 5:
            continue
        ranked = sorted(eligible, key=_candidate_rank, reverse=True)
        leaders = ranked[:top_per_day]
        # Add lower-ranked controls so the model is tested against plausible
        # non-winners, not only against preselected leaders.
        remainder = ranked[top_per_day:]
        if controls_per_day and remainder:
            step = max(1, len(remainder) // controls_per_day)
            controls = remainder[::step][:controls_per_day]
        else:
            controls = []
        chosen = leaders + controls
        for e in chosen:
            e = dict(e)
            e["candidate_rank_1000"] = round(_candidate_rank(e), 3)
            e["daily_candidate_type"] = "leader" if e in leaders else "control"
            selected.append(e)
        stats.append({"date": day, "eligible": len(eligible), "selected": len(chosen)})
    return selected, stats


def _sim_trade(e, target_pct, stop_pct=3.0):
    # With 15m aggregate bars we do not know intrabar ordering if both target and
    # stop were touched. Count ambiguous bars conservatively as a stop.
    up = e["max_up_after_1000_pct"]
    down = e["max_down_after_1000_pct"]
    if down <= -stop_pct and up >= target_pct:
        return -stop_pct
    if down <= -stop_pct:
        return -stop_pct
    if up >= target_pct:
        return target_pct
    return e["close_after_1000_pct"]


def _metrics(events, model, threshold):
    picks = [e for e in events if e["scores"][model] >= threshold]
    if not picks:
        return {
            "signals": 0, "hit_rate_2pct": None, "hit_rate_3pct": None,
            "hit_rate_pct": None, "quality_rate_pct": None, "avg_max_up_pct": None,
            "avg_drawdown_pct": None, "avg_close_pct": None,
            "expectancy_t2_s3_pct": None, "expectancy_t3_s3_pct": None,
            "expectancy_t5_s3_pct": None,
        }
    n = len(picks)
    return {
        "signals": n,
        "hit_rate_2pct": round(100 * sum(e["hit_2pct"] for e in picks) / n, 2),
        "hit_rate_3pct": round(100 * sum(e["hit_3pct"] for e in picks) / n, 2),
        "hit_rate_pct": round(100 * sum(e["hit_5pct"] for e in picks) / n, 2),
        "quality_rate_pct": round(100 * sum(e["quality_win"] for e in picks) / n, 2),
        "avg_max_up_pct": round(statistics.mean(e["max_up_after_1000_pct"] for e in picks), 2),
        "avg_drawdown_pct": round(statistics.mean(e["max_down_after_1000_pct"] for e in picks), 2),
        "avg_close_pct": round(statistics.mean(e["close_after_1000_pct"] for e in picks), 2),
        "expectancy_t2_s3_pct": round(statistics.mean(_sim_trade(e, 2, 3) for e in picks), 3),
        "expectancy_t3_s3_pct": round(statistics.mean(_sim_trade(e, 3, 3) for e in picks), 3),
        "expectancy_t5_s3_pct": round(statistics.mean(_sim_trade(e, 5, 3) for e in picks), 3),
    }


def _choose_model(train):
    best = None
    min_signals = max(20, int(len(train) * 0.03))
    for model in MODELS:
        for threshold in (50, 55, 60, 65, 70, 75, 80):
            m = _metrics(train, model, threshold)
            if m["signals"] < min_signals or m["hit_rate_3pct"] is None:
                continue
            utility = (
                m["hit_rate_3pct"]
                + 8.0 * (m["expectancy_t3_s3_pct"] or 0)
                + 0.8 * (m["avg_max_up_pct"] or 0)
                + 0.4 * (m["avg_drawdown_pct"] or 0)
            )
            row = {"model": model, "threshold": threshold, "utility": round(utility, 3), "train": m}
            if best is None or row["utility"] > best["utility"]:
                best = row
    if best is None:
        best = {"model": "balanced", "threshold": 60, "utility": None, "train": _metrics(train, "balanced", 60)}
    return best


def _buckets(events, model):
    specs = [(0, 49), (50, 59), (60, 69), (70, 79), (80, 89), (90, 100)]
    out = []
    for lo, hi in specs:
        arr = [e for e in events if lo <= e["scores"][model] <= hi]
        if not arr:
            out.append({"bucket": f"{lo}-{hi}", "samples": 0, "hit_rate_pct": None, "avg_max_up_pct": None})
            continue
        out.append({
            "bucket": f"{lo}-{hi}",
            "samples": len(arr),
            "hit_rate_pct": round(100 * sum(e["hit_5pct"] for e in arr) / len(arr), 2),
            "hit_rate_3pct": round(100 * sum(e["hit_3pct"] for e in arr) / len(arr), 2),
            "avg_max_up_pct": round(statistics.mean(e["max_up_after_1000_pct"] for e in arr), 2),
            "avg_drawdown_pct": round(statistics.mean(e["max_down_after_1000_pct"] for e in arr), 2),
        })
    return out


def install_strategy_validation(app):
    @app.get("/api/strategy/validate")
    async def validate_strategy(
        days: int = Query(180, ge=60, le=365),
        symbols: int = Query(90, ge=30, le=len(BROAD_UNIVERSE)),
    ):
        key = os.getenv("ALPACA_API_KEY", "").strip()
        secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
        feed = os.getenv("ALPACA_FEED", "iex").strip().lower() or "iex"
        if not key or not secret:
            raise HTTPException(503, "Alpaca לא מוגדר")
        if feed not in {"iex", "sip", "delayed_sip"}:
            feed = "iex"

        # Ignore stale UI defaults from older builds. We want a meaningful sample.
        calendar_days = max(days, 180)
        universe_size = max(symbols, 90)
        universe = BROAD_UNIVERSE[:universe_size]
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

        all_raw_events = []
        errors = []
        async with httpx.AsyncClient(timeout=40) as client:
            for symbol in universe:
                try:
                    sdays, err = await _fetch_symbol_days(client, symbol, headers, feed, calendar_days)
                    if err:
                        errors.append(err)
                        continue
                    all_raw_events.extend(_build_symbol_events(symbol, sdays))
                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")

        if len(all_raw_events) < 200:
            raise HTTPException(503, f"אין מספיק נתונים גולמיים לאימות אמין כרגע ({len(all_raw_events)}). שגיאות מקור: {len(errors)}")

        all_events, daily_stats = _select_daily_universe(all_raw_events, top_per_day=12, controls_per_day=8)
        if len(all_events) < 150:
            raise HTTPException(503, f"נבנה מדגם מועמדים קטן מדי ({len(all_events)}). נסה שוב לאחר בדיקת מקור הנתונים.")

        all_events.sort(key=lambda e: (e["date"], e["symbol"]))
        unique_dates = sorted({e["date"] for e in all_events})
        split_idx = max(1, int(len(unique_dates) * 0.70))
        split_date = unique_dates[min(split_idx, len(unique_dates)-1)]
        train = [e for e in all_events if e["date"] < split_date]
        test = [e for e in all_events if e["date"] >= split_date]
        chosen = _choose_model(train)
        test_metrics = _metrics(test, chosen["model"], chosen["threshold"])

        baseline_hit_5 = round(100 * sum(e["hit_5pct"] for e in test) / len(test), 2) if test else None
        baseline_hit_3 = round(100 * sum(e["hit_3pct"] for e in test) / len(test), 2) if test else None
        lift = round(test_metrics["hit_rate_pct"] / baseline_hit_5, 2) if baseline_hit_5 and test_metrics["hit_rate_pct"] is not None else None
        lift3 = round(test_metrics["hit_rate_3pct"] / baseline_hit_3, 2) if baseline_hit_3 and test_metrics["hit_rate_3pct"] is not None else None
        top_test = sorted(test, key=lambda e: e["scores"][chosen["model"]], reverse=True)[:30]

        return {
            "ok": True,
            "method": "historical daily-candidate walk-forward holdout",
            "cutoff_ny": "10:00",
            "feed": feed,
            "days_requested": calendar_days,
            "symbols_tested": universe,
            "universe_size": len(universe),
            "raw_events": len(all_raw_events),
            "daily_candidate_days": len(daily_stats),
            "samples": {"total": len(all_events), "train": len(train), "test": len(test), "split_date": split_date},
            "baseline_test_hit_rate_pct": baseline_hit_5,
            "baseline_test_hit_rate_3pct": baseline_hit_3,
            "selected": {
                "model": chosen["model"],
                "threshold": chosen["threshold"],
                "weights": MODELS[chosen["model"]],
                "train": chosen["train"],
                "test": test_metrics,
                "lift_vs_baseline": lift,
                "lift3_vs_baseline": lift3,
            },
            "score_buckets_test": _buckets(test, chosen["model"]),
            "top_test_signals": top_test,
            "errors": errors[:30],
            "error_count": len(errors),
            "limitations": [
                "המועמדים לכל יום נבחרים רק מנתוני טרום/פתיחת המסחר עד 10:00 ניו יורק; אין שימוש בתשואת העתיד בבחירת המועמד.",
                "היקום ההיסטורי רחב יותר מבעבר אך עדיין אינו כל שוק המניות האמריקאי, ולכן זו הפחתה של selection bias ולא ביטול מלא שלו.",
                "חדשות היסטוריות אינן נכנסות לכיול ולכן קטליזטור חדשותי נשאר שכבת אישור נפרדת.",
                "IEX הוא feed חלקי לעומת SIP; RVOL מחושב יחסית לאותה מניה ולכן שימושי יותר מנפח מוחלט.",
                "סימולציית target/stop על נרות 15 דקות שמרנית: אם target ו-stop נגעו באותו נר, היא סופרת stop.",
            ],
        }
