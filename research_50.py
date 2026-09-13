import asyncio
import statistics
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException

from long_strategy import CORE_UNIVERSE, ETF_SYMBOLS, SECTOR_MAP, SECTOR_ETFS, _point_in_time_pick

# 50 monthly scenarios: Jan-2020 through Feb-2024. Every point has a full
# one-year outcome window and spans crash, rebound, bull, bear and recovery.
SCENARIOS = []
y, m = 2020, 1
for _ in range(50):
    if m == 12:
        nxt = datetime(y + 1, 1, 1)
    else:
        nxt = datetime(y, m + 1, 1)
    last = nxt - timedelta(days=1)
    SCENARIOS.append(last.date().isoformat())
    m += 1
    if m == 13:
        y += 1
        m = 1

PRESETS = {
    "balanced": {},
    "defensive": {"overext": 0.65, "riskoff": 8.0, "vol": 4.0, "rs": 0.12, "trend": 2.0},
    "relative_strength": {"overext": 0.25, "riskoff": 3.0, "vol": 1.0, "rs": 0.28, "trend": 1.0},
    "anti_parabolic": {"overext": 1.0, "riskoff": 4.0, "vol": 2.0, "rs": 0.10, "trend": 2.0},
    "trend_quality": {"overext": 0.40, "riskoff": 5.0, "vol": 2.0, "rs": 0.16, "trend": 5.0},
    "recovery": {"overext": 0.30, "riskoff": 1.0, "vol": 1.0, "rs": 0.22, "trend": 1.0},
}


def _adj(row, preset):
    p = PRESETS[preset]
    if preset == "balanced":
        return float(row.get("score") or 0)
    m = row.get("metrics") or {}
    s = float(row.get("score") or 0)
    s -= float(m.get("overextension_penalty") or 0) * p.get("overext", 0)
    if m.get("regime") == "risk_off":
        s -= p.get("riskoff", 0)
    vol = float(m.get("volatility") or 0)
    if vol > 55:
        s -= p.get("vol", 0)
    rsvals = [m.get("rs_market_6m"), m.get("rs_market_12m"), m.get("rs_sector_6m"), m.get("rs_sector_12m")]
    rsvals = [float(x) for x in rsvals if x is not None]
    if rsvals:
        s += statistics.mean(rsvals) * p.get("rs", 0)
    reasons = set(m.get("reasons") or [])
    if "above_ma200" in reasons and "trend_alignment" in reasons:
        s += p.get("trend", 0)
    # Recovery preset does not punish all risk-off names equally; it rewards
    # genuine relative strength while avoiding extreme extension.
    if preset == "recovery" and m.get("regime") in {"risk_off", "transition"}:
        if rsvals and statistics.mean(rsvals) > 5:
            s += 4
        if float(m.get("dist_ma50_pct") or 0) > 20:
            s -= 5
    return round(s, 3)


def _pick(rows, preset, top=10):
    ranked = sorted(rows, key=lambda r: _adj(r, preset), reverse=True)
    out, counts = [], {}
    for r in ranked:
        sec = SECTOR_MAP.get(r["symbol"], "OTHER")
        if counts.get(sec, 0) >= 3:
            continue
        x = dict(r)
        x["research_score"] = _adj(r, preset)
        out.append(x)
        counts[sec] = counts.get(sec, 0) + 1
        if len(out) >= top:
            break
    return out


def _summary(picks):
    one = [x for x in picks if x.get("return_1m_pct") is not None]
    year = [x for x in picks if x.get("return_12m_pct") is not None]
    return {
        "picks": len(picks),
        "success_1m_pct": round(100 * sum(bool(x.get("success_1m")) for x in one) / len(one), 1) if one else None,
        "avg_1m_pct": round(statistics.mean(x["return_1m_pct"] for x in one), 2) if one else None,
        "success_12m_pct": round(100 * sum(bool(x.get("success_12m")) for x in year) / len(year), 1) if year else None,
        "avg_12m_pct": round(statistics.mean(x["return_12m_pct"] for x in year), 2) if year else None,
    }


def _quality(stats):
    # Training objective uses both hit-rate and average return, avoiding a model
    # that wins often with tiny gains or relies on one huge outlier.
    return (stats.get("success_1m_pct") or 0) * 0.20 + (stats.get("success_12m_pct") or 0) * 0.35 + (stats.get("avg_1m_pct") or 0) * 0.35 + (stats.get("avg_12m_pct") or 0) * 0.10


def _lessons(picks):
    fails = [x for x in picks if not x.get("success_1m")]
    if not fails:
        return ["כל בחירות החודש עברו את יעד 4%+; ממשיכים לבדוק עמידות בתקופה הבאה."]
    n = len(fails)
    over = sum(float((x.get("metrics") or {}).get("overextension_penalty") or 0) > 0 for x in fails)
    riskoff = sum((x.get("metrics") or {}).get("regime") == "risk_off" for x in fails)
    weakrs = 0
    highvol = 0
    for x in fails:
        m = x.get("metrics") or {}
        rs = [m.get("rs_market_6m"), m.get("rs_sector_6m")]
        rs = [float(v) for v in rs if v is not None]
        if rs and statistics.mean(rs) < 0:
            weakrs += 1
        if float(m.get("volatility") or 0) > 55:
            highvol += 1
    out = []
    if over / n >= 0.35: out.append("חלק משמעותי מהכישלונות היו מניות מורחבות מדי; נדרש קנס חזק יותר ל-overextension.")
    if riskoff / n >= 0.35: out.append("כישלונות רבים הופיעו ב-risk-off; יש להקשיח את מסנן משטר השוק.")
    if weakrs / n >= 0.35: out.append("לכישלונות רבים הייתה חולשה יחסית מול השוק/סקטור; יש להגדיל משקל Relative Strength.")
    if highvol / n >= 0.35: out.append("תנודתיות גבוהה בולטת בכישלונות; יש להעדיף איכות מגמה על high-beta.")
    if not out: out.append("לא נמצא כשל יחיד דומיננטי; משאירים מודל מאוזן ונמנעים מכוונון יתר.")
    return out


def install_research_50(app):
    import sys
    mod = sys.modules.get("app") or sys.modules.get(app.__module__)

    async def fetch_all():
        if mod is None or not (mod.ALPACA_KEY and mod.ALPACA_SECRET):
            raise HTTPException(503, "Alpaca לא מוגדר")
        headers = {"APCA-API-KEY-ID": mod.ALPACA_KEY, "APCA-API-SECRET-KEY": mod.ALPACA_SECRET}
        feed = mod.ALPACA_FEED if mod.ALPACA_FEED in {"iex", "sip", "delayed_sip"} else "iex"
        end = datetime.now(timezone.utc)
        start = datetime(2018, 1, 1, tzinfo=timezone.utc)
        symbols = list(dict.fromkeys(CORE_UNIVERSE + SECTOR_ETFS))
        sem = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=50) as client:
            async def one(symbol):
                async with sem:
                    r = await client.get(
                        f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                        headers=headers,
                        params={"timeframe":"1Day","start":start.isoformat(),"end":end.isoformat(),"limit":10000,"adjustment":"split","feed":feed,"sort":"asc"},
                    )
                    if r.status_code >= 400:
                        return symbol, []
                    rows=[]
                    for b in (r.json() or {}).get("bars") or []:
                        try:
                            c=float(b.get("c") or 0); h=float(b.get("h") or 0); v=float(b.get("v") or 0); d=str(b.get("t") or "")[:10]
                            if c>0 and h>0 and d: rows.append({"d":d,"c":c,"h":h,"v":v})
                        except Exception: pass
                    return symbol, rows
            pairs = await asyncio.gather(*[one(s) for s in symbols])
        return dict(pairs), feed

    @app.get("/api/strategy/long/research-50")
    async def research_50():
        data, feed = await fetch_all()
        spy = data.get("SPY", [])
        scenario_rows = {}
        spy_returns = {}
        for date in SCENARIOS:
            rows=[]
            for s in CORE_UNIVERSE:
                if s in ETF_SYMBOLS: continue
                p = _point_in_time_pick(s, data.get(s, []), date, spy, data.get(SECTOR_MAP.get(s, ""), []))
                if p: rows.append(p)
            scenario_rows[date]=rows
            sp = _point_in_time_pick("SPY", spy, date, spy, [])
            spy_returns[date] = {"m1": sp.get("return_1m_pct") if sp else None, "y1": sp.get("return_12m_pct") if sp else None}

        chosen_preset="balanced"
        completed_dates=[]
        all_live_picks=[]
        batches=[]
        for bi in range(5):
            dates=SCENARIOS[bi*10:(bi+1)*10]
            batch_picks=[]
            scenario_summaries=[]
            for d in dates:
                picks=_pick(scenario_rows[d], chosen_preset, 10)
                batch_picks.extend(picks)
                st=_summary(picks)
                sp=spy_returns[d]
                scenario_summaries.append({"date":d,"preset":chosen_preset,**st,"spy_1m_pct":sp["m1"],"spy_12m_pct":sp["y1"],"beat_spy_1m": st["avg_1m_pct"] is not None and sp["m1"] is not None and st["avg_1m_pct"]>sp["m1"],"beat_spy_12m": st["avg_12m_pct"] is not None and sp["y1"] is not None and st["avg_12m_pct"]>sp["y1"]})
            all_live_picks.extend(batch_picks)
            completed_dates.extend(dates)
            batch_summary=_summary(batch_picks)
            lessons=_lessons(batch_picks)

            # Learn only from already-completed scenarios. Each candidate preset is
            # replayed on past dates, never on the next unseen batch.
            preset_scores={}
            for preset in PRESETS:
                hist=[]
                for d in completed_dates:
                    hist.extend(_pick(scenario_rows[d], preset, 10))
                hs=_summary(hist)
                preset_scores[preset]={"quality":round(_quality(hs),3),**hs}
            next_preset=max(preset_scores, key=lambda k:preset_scores[k]["quality"])
            batches.append({"batch":bi+1,"dates":dates,"preset_used":chosen_preset,"summary":batch_summary,"lessons":lessons,"next_preset":next_preset,"preset_scores":preset_scores,"scenarios":scenario_summaries})
            chosen_preset=next_preset

        overall=_summary(all_live_picks)
        scenario_flat=[s for b in batches for s in b["scenarios"]]
        overall.update({
            "scenario_count":len(SCENARIOS),
            "stock_pick_count":len(all_live_picks),
            "beat_spy_1m_scenarios_pct":round(100*sum(bool(s["beat_spy_1m"]) for s in scenario_flat)/len(scenario_flat),1),
            "beat_spy_12m_scenarios_pct":round(100*sum(bool(s["beat_spy_12m"]) for s in scenario_flat)/len(scenario_flat),1),
        })
        return {"ok":True,"feed":feed,"method":"sequential 5x10 scenario research; tuning uses prior batches only","date_range":[SCENARIOS[0],SCENARIOS[-1]],"overall":overall,"batches":batches,"final_preset":chosen_preset,"presets":list(PRESETS.keys()),"limitations":["Universe is maintained today, so survivorship bias is reduced but not eliminated.","Price/volume only: historical fundamentals/news are not point-in-time inputs.","Adaptive preset selection improves the research process but does not guarantee future returns."]}
