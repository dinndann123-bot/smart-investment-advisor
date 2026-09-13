import asyncio
import math
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, Query

_ASSET_CACHE = {"at": 0.0, "rows": []}
_ASSET_TTL = 3600


def _infer_type(asset):
    name = str(asset.get("name") or "").lower()
    if any(x in name for x in [" etf", "exchange traded", "fund", "trust", "ishares", "spdr", "invesco", "vanguard"]):
        return "ETF / קרן סל"
    return "מניה / נייר ערך"


def _safe_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def install_market_search(app):
    import sys
    mod = sys.modules.get(app.__module__) or sys.modules.get("app")
    if mod is None:
        return

    async def load_assets():
        now = datetime.now(timezone.utc).timestamp()
        if _ASSET_CACHE["rows"] and now - _ASSET_CACHE["at"] < _ASSET_TTL:
            return _ASSET_CACHE["rows"]
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):
            return []
        headers = {"APCA-API-KEY-ID": mod.ALPACA_KEY, "APCA-API-SECRET-KEY": mod.ALPACA_SECRET}
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(
                "https://paper-api.alpaca.markets/v2/assets",
                headers=headers,
                params={"asset_class": "us_equity", "status": "active"},
            )
            if r.status_code >= 400:
                raise HTTPException(502, "לא ניתן כרגע לטעון את רשימת ניירות הערך")
            rows = []
            for a in r.json() or []:
                if not a.get("tradable"):
                    continue
                symbol = str(a.get("symbol") or "").upper().strip()
                name = str(a.get("name") or symbol).strip()
                if not symbol:
                    continue
                rows.append({
                    "symbol": symbol,
                    "name": name,
                    "exchange": a.get("exchange"),
                    "asset_class": a.get("class") or a.get("asset_class") or "us_equity",
                    "fractionable": bool(a.get("fractionable")),
                    "shortable": bool(a.get("shortable")),
                    "easy_to_borrow": bool(a.get("easy_to_borrow")),
                    "type_he": _infer_type(a),
                })
            _ASSET_CACHE.update({"at": now, "rows": rows})
            return rows

    @app.get("/api/market-search")
    async def market_search(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(20, ge=1, le=50)):
        rows = await load_assets()
        needle = q.strip().lower()
        if not rows:
            return {"query": q, "results": [], "source": "alpaca", "note": "Alpaca לא מחובר ולכן החיפוש המלא אינו זמין."}

        def rank(x):
            s = x["symbol"].lower(); n = x["name"].lower()
            if s == needle: return 0
            if s.startswith(needle): return 1
            if needle in s: return 2
            if n.startswith(needle): return 3
            if needle in n: return 4
            return 99

        matches = [x for x in rows if rank(x) < 99]
        matches.sort(key=lambda x: (rank(x), len(x["symbol"]), x["name"]))
        return {"query": q, "count": len(matches), "results": matches[:limit], "source": "alpaca_assets"}

    def success_stats(symbol, score):
        try:
            con = mod._db()
            run = con.execute("SELECT id FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not run:
                con.close(); return {"pct": None, "samples": 0, "basis": "אין Backtest"}
            rid = run["id"]
            exact = con.execute(
                """SELECT COUNT(*) n, SUM(CASE WHEN hit1=1 THEN 1 ELSE 0 END) wins
                   FROM backtest_events WHERE run_id=? AND symbol=? AND signaled=1""",
                (rid, symbol),
            ).fetchone()
            if exact and (exact["n"] or 0) >= 5:
                n = int(exact["n"]); wins = int(exact["wins"] or 0)
                con.close()
                return {"pct": round(wins/n*100, 1), "samples": n, "basis": "אותות היסטוריים של הנייר עצמו"}
            if score is None:
                con.close(); return {"pct": None, "samples": int(exact["n"] or 0) if exact else 0, "basis": "אין מספיק היסטוריה"}
            if score >= 90: lo, hi = 90, 100
            elif score >= 85: lo, hi = 85, 89.999
            elif score >= 80: lo, hi = 80, 84.999
            else: lo, hi = 70, 79.999
            bucket = con.execute(
                """SELECT COUNT(*) n, SUM(CASE WHEN hit1=1 THEN 1 ELSE 0 END) wins
                   FROM backtest_events WHERE run_id=? AND signaled=1 AND score>=? AND score<=?""",
                (rid, lo, hi),
            ).fetchone()
            con.close()
            n = int(bucket["n"] or 0) if bucket else 0
            if n < 10:
                return {"pct": None, "samples": n, "basis": "מדגם קטן מדי בטווח הציון"}
            wins = int(bucket["wins"] or 0)
            return {"pct": round(wins/n*100, 1), "samples": n, "basis": f"מקרים היסטוריים בציון {int(lo)}–{int(hi)}"}
        except Exception:
            return {"pct": None, "samples": 0, "basis": "נתון לא זמין"}

    @app.get("/api/market-asset/{symbol}")
    async def market_asset(symbol: str):
        symbol = symbol.upper().strip()
        assets = await load_assets()
        asset = next((x for x in assets if x["symbol"] == symbol), None)
        if assets and not asset:
            raise HTTPException(404, "נייר הערך לא נמצא ברשימת הנכסים הפעילים")
        asset = asset or {"symbol": symbol, "name": symbol, "exchange": None, "type_he": "נייר ערך"}

        async with httpx.AsyncClient(timeout=35) as client:
            one_y_task = asyncio.create_task(mod._alpaca_stock_bundle(client, symbol, "1Y"))
            one_d_task = asyncio.create_task(mod._alpaca_stock_bundle(client, symbol, "1D"))
            one_y, one_d = await asyncio.gather(one_y_task, one_d_task)
            if not one_y.get("bars"):
                one_y = await mod._yahoo_stock_bundle(client, symbol, "1Y")
            if not one_d.get("bars"):
                one_d = await mod._yahoo_stock_bundle(client, symbol, "1D")

        bars = one_y.get("bars") or []
        quote = one_d.get("quote") or one_y.get("quote") or {}
        news = one_d.get("news") or one_y.get("news") or []
        closes = [_safe_float(b.get("v") if b.get("v") is not None else b.get("c")) for b in bars]
        closes = [x for x in closes if x and x > 0]
        vols = [_safe_float(b.get("volume") if b.get("volume") is not None else b.get("v")) for b in bars]
        vols = [x for x in vols if x is not None and x >= 0]
        highs = [_safe_float(b.get("h")) for b in bars]; highs = [x for x in highs if x]
        lows = [_safe_float(b.get("l")) for b in bars]; lows = [x for x in lows if x]
        price = _safe_float(quote.get("price")) or (closes[-1] if closes else None)
        change = _safe_float(quote.get("change"))
        one_year_return = ((closes[-1] / closes[0] - 1) * 100) if len(closes) >= 2 and closes[0] else None
        avg_daily_volume = (sum(vols[-252:]) / len(vols[-252:])) if vols else None
        annual_volume = sum(vols[-252:]) if vols else None
        annual_dollar_turnover = None
        if bars:
            vals=[]
            for b in bars[-252:]:
                c=_safe_float(b.get("v") if b.get("v") is not None else b.get("c")); v=_safe_float(b.get("volume"))
                if c is not None and v is not None: vals.append(c*v)
            annual_dollar_turnover=sum(vals) if vals else None

        latest_bar = bars[-1] if bars else {}
        current_vol = _safe_float(latest_bar.get("volume"))
        baseline = (sum(vols[-21:-1]) / len(vols[-21:-1])) if len(vols) >= 21 else avg_daily_volume
        rvol = (current_vol / baseline) if current_vol is not None and baseline else None
        intraday_strength = None
        hi=_safe_float(latest_bar.get("h")); lo=_safe_float(latest_bar.get("l")); close=_safe_float(latest_bar.get("v") if latest_bar.get("v") is not None else latest_bar.get("c"))
        if hi is not None and lo is not None and close is not None and hi > lo:
            intraday_strength=(close-lo)/(hi-lo)

        score = mod._score_day_candidate(
            change_pct=change,
            rvol=rvol,
            daily_volume=current_vol or avg_daily_volume or 0,
            price=price,
            news_count=len(news),
            news_minutes=None,
            intraday_strength=intraday_strength,
        ) if price else None
        hist = success_stats(symbol, score)

        news_out=[]
        for x in news[:8]:
            news_out.append({
                "title": x.get("title") or x.get("headline"),
                "source": x.get("source"),
                "url": x.get("url"),
                "published_at": x.get("published_at") or x.get("created_at"),
            })

        return {
            "asset": asset,
            "price": price,
            "change_pct": round(change,2) if change is not None else None,
            "method_score": score,
            "historical_success": hist,
            "year": {
                "return_pct": round(one_year_return,2) if one_year_return is not None else None,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "avg_daily_volume": round(avg_daily_volume) if avg_daily_volume is not None else None,
                "annual_share_volume": round(annual_volume) if annual_volume is not None else None,
                "annual_dollar_turnover": round(annual_dollar_turnover,2) if annual_dollar_turnover is not None else None,
                "trading_days": len(bars),
            },
            "rvol": round(rvol,2) if rvol is not None else None,
            "news_count": len(news_out),
            "catalyst": news_out[0]["title"] if news_out else None,
            "news": news_out,
            "provider": "Alpaca" if one_y.get("bars") else "Public fallback",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "definitions": {
                "method_score": "ציון התאמה 0–100 לשיטת המסחר היומי; אינו אחוז סיכוי לרווח.",
                "historical_success": "אחוז ההצלחה שנמדד ב-Backtest על הנייר עצמו או על מקרים היסטוריים בעלי ציון דומה.",
                "annual_dollar_turnover": "סכום משוער של מחיר×מחזור בכל ימי המסחר שנאספו בשנה האחרונה; זהו מחזור מסחר, לא הכנסות החברה.",
            },
        }
