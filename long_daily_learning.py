"""Prospective daily validation for the app's displayed long-horizon list.

The daily forecast is a deliberately simple baseline: mean of the previous five
completed close-to-close returns, capped at +/-5%. It is kept separate from the
long-term score and from the day-trading scanner.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

TICKERS = ["TSSI", "NVTS", "CTRI", "CRMD", "POET", "RKLB", "PLTR", "APP", "SMCI", "MYRG"]
SCORES = {"TSSI":86,"NVTS":85,"CTRI":83,"CRMD":82,"POET":78,"RKLB":77,"PLTR":76,"APP":75,"SMCI":74,"MYRG":73}
ET = ZoneInfo("America/New_York")


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _record_id(record):
    return record.get("record_type") == "long_daily_prediction"


def _forecast(bars):
    completed = [b for b in bars if _finite(b.get("c")) and _finite(b.get("c")) > 0]
    returns = [(b["c"] / a["c"] - 1) * 100 for a, b in zip(completed[-6:-1], completed[-5:])]
    if len(returns) != 5:
        return None
    raw = sum(returns) / len(returns)
    return round(max(-5.0, min(5.0, raw)), 3)


def install_long_daily_learning(app, store, market_module, quote_fetcher=None):
    async def _bars(client, ticker, headers, feed):
        url = f"https://data.alpaca.markets/v2/stocks/{ticker}/bars"
        now = datetime.now(timezone.utc)
        response = await client.get(
            url,
            headers=headers,
            params={"timeframe": "1Day", "start": (now.replace(hour=0, minute=0, second=0) - timedelta(days=25)).isoformat(),
                    "end": now.isoformat(), "limit": 20, "adjustment": "split", "feed": feed, "sort": "asc"},
        )
        if response.status_code >= 400:
            return []
        return (response.json() or {}).get("bars") or []

    def _all_records():
        loader = getattr(store, "load_long_daily", None)
        return [r for r in (loader() if loader else store.load(3000)) if _record_id(r)]

    def _save(record):
        saver = getattr(store, "upsert_long_daily", None)
        (saver or store.upsert)(record)

    @app.post("/api/learning/long-daily/capture")
    async def capture_long_daily():
        """Freeze today's ten displayed long-term picks and a daily baseline forecast."""
        if not (getattr(market_module, "ALPACA_KEY", None) and getattr(market_module, "ALPACA_SECRET", None)):
            raise HTTPException(503, "Alpaca data is not configured")
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(ET)
        if not (4 <= now_et.hour < 16):
            raise HTTPException(425, "צילום התחזית היומי פתוח רק במהלך הפרה־מרקט/יום המסחר (04:00–15:59 ניו יורק)")
        trade_date = now_utc.astimezone(ET).date().isoformat()
        existing = {r.get("ticker"): r for r in _all_records() if r.get("trade_date") == trade_date}
        if len(existing) == 10:
            return {"ok": True, "created": 0, "already_captured": True, "trade_date": trade_date,
                    "records": [existing[t] for t in TICKERS if t in existing],
                    "message": "התחזית היומית כבר ננעלה; לא מחליפים תחזית קיימת."}

        headers = {"APCA-API-KEY-ID": market_module.ALPACA_KEY,
                   "APCA-API-SECRET-KEY": market_module.ALPACA_SECRET}
        feed = getattr(market_module, "ALPACA_FEED", "iex")
        if feed not in {"iex", "sip", "delayed_sip"}:
            feed = "iex"
        async with httpx.AsyncClient(timeout=25) as client:
            batches = await asyncio.gather(*[_bars(client, s, headers, feed) for s in TICKERS])
        if quote_fetcher:
            fetched_quotes = await asyncio.gather(*[quote_fetcher(s) for s in TICKERS], return_exceptions=True)
            quotes = {s:(q if not isinstance(q,Exception) else {}) for s,q in zip(TICKERS,fetched_quotes)}
        else:
            quotes = {}

        created = []
        for ticker, raw_bars in zip(TICKERS, batches):
            parsed = [{"d": str(b.get("t", ""))[:10], "c": _finite(b.get("c")),
                       "h": _finite(b.get("h")), "l": _finite(b.get("l"))}
                      for b in raw_bars if str(b.get("t", ""))[:10] < trade_date]
            closes = [b for b in parsed if b["c"] and b["c"] > 0]
            if len(closes) < 6:
                continue
            prediction = _forecast(closes)
            if prediction is None:
                continue
            prior_close = closes[-1]["c"]
            quote = quotes.get(ticker) or {}
            freshness = quote.get("freshness") or {}
            live_price = _finite(quote.get("price")) if freshness.get("usable_as_current_price") else None
            row = {
                "record_type": "long_daily_prediction",
                "scan_id": f"long-daily:{trade_date}", "ticker": ticker, "rank": TICKERS.index(ticker) + 1,
                "trade_date": trade_date, "epoch": now_utc.timestamp(), "captured_at": now_utc.isoformat(),
                "strategy_version": "displayed-long-list-v1", "long_term_score": SCORES[ticker], "forecast_method": "mean_previous_5_completed_daily_returns_capped_5pct",
                "forecast_return_pct": prediction, "forecast_close": round(prior_close * (1 + prediction / 100), 4),
                "prior_close": round(prior_close, 4), "snapshot_price": round(live_price, 4) if live_price else None,
                "snapshot_price_source": quote.get("source") if live_price else None,
                "snapshot_price_timestamp": quote.get("price_timestamp") if live_price else None,
                "snapshot_price_session": quote.get("session"), "snapshot_price_feed": quote.get("feed"),
                "snapshot_price_freshness": freshness.get("state", "unavailable"),
                "data_feed": feed, "forecast_closed": False, "actual_return_pct": None,
                "actual_close": None, "forecast_error_pct_points": None,
                "data_quality": "historical_forecast_inputs_valid",
            }
            created.append(row)
        merged = dict(existing)
        merged.update({r["ticker"]: r for r in created})
        if len(merged) != 10:
            raise HTTPException(503, f"נמצאו נתונים תקינים רק ל־{len(merged)} מתוך 10 מניות; התחזית לא ננעלה")
        for ticker in TICKERS:
            if ticker not in existing:
                _save(merged[ticker])
        return {"ok": True, "created": len(created), "already_captured": False, "trade_date": trade_date,
                "forecast_definition": "ממוצע תשואות הסגירה של 5 ימי המסחר המלאים הקודמים, מוגבל ל־±5%",
                "records": created}

    @app.post("/api/learning/long-daily/evaluate")
    async def evaluate_long_daily():
        now_et = datetime.now(timezone.utc).astimezone(ET)
        if (now_et.hour, now_et.minute) < (16, 15):
            raise HTTPException(425, "הערכת יום תתבצע אחרי 16:15 שעון ניו יורק, כדי לא למדוד נר יומי חלקי")
        if not (getattr(market_module, "ALPACA_KEY", None) and getattr(market_module, "ALPACA_SECRET", None)):
            raise HTTPException(503, "Alpaca data is not configured")
        trade_date = now_et.date().isoformat()
        records = [r for r in _all_records() if r.get("trade_date") == trade_date]
        if len(records) != 10:
            raise HTTPException(409, "לא נמצאה תחזית נעולה של 10 מניות להיום")
        headers = {"APCA-API-KEY-ID": market_module.ALPACA_KEY,
                   "APCA-API-SECRET-KEY": market_module.ALPACA_SECRET}
        feed = records[0].get("data_feed", "iex")
        async with httpx.AsyncClient(timeout=25) as client:
            batches = await asyncio.gather(*[_bars(client, r["ticker"], headers, feed) for r in records])
        updated = []
        for record, raw in zip(records, batches):
            candle = next((b for b in raw if str(b.get("t", ""))[:10] == trade_date), None)
            close = _finite((candle or {}).get("c"))
            previous = _finite(record.get("prior_close"))
            if not (candle and close and previous and close > 0 and previous > 0):
                updated.append(record)
                continue
            record.update({"actual_close": round(close, 4), "actual_high": _finite(candle.get("h")),
                           "actual_low": _finite(candle.get("l")),
                           "actual_return_pct": round((close / previous - 1) * 100, 3),
                           "forecast_error_pct_points": round((close / previous - 1) * 100 - record["forecast_return_pct"], 3),
                           "forecast_direction_correct": ((close / previous - 1) * record["forecast_return_pct"] > 0),
                           "evaluated_at": datetime.now(timezone.utc).isoformat(), "forecast_closed": True})
            _save(record)
            updated.append(record)
        valid = [r for r in updated if r.get("forecast_closed")]
        return {"ok": True, "trade_date": trade_date, "evaluated": len(valid), "pending": 10-len(valid),
                "direction_accuracy_pct": round(100 * sum(bool(r["forecast_direction_correct"]) for r in valid) / len(valid), 1) if valid else None,
                "mean_absolute_forecast_error_pct_points": round(sum(abs(r["forecast_error_pct_points"]) for r in valid)/len(valid), 3) if valid else None,
                "records": updated}

    @app.get("/api/learning/long-daily")
    async def long_daily_summary():
        records = _all_records()
        days = {}
        for record in records:
            days.setdefault(record.get("trade_date"), []).append(record)
        daily = []
        prior_symbols = set()
        for day in sorted(days):
            rows = days[day]
            symbols = {r.get("ticker") for r in rows if r.get("ticker")}
            done = [r for r in rows if r.get("forecast_closed") and r.get("actual_return_pct") is not None]
            daily.append({"trade_date": day, "selected": len(rows), "evaluated": len(done),
                          "direction_accuracy_pct": round(100 * sum(bool(r.get("forecast_direction_correct")) for r in done) / len(done), 1) if done else None,
                          "mean_actual_return_pct": round(sum(r["actual_return_pct"] for r in done)/len(done), 3) if done else None,
                          "mean_absolute_forecast_error_pct_points": round(sum(abs(r["forecast_error_pct_points"]) for r in done)/len(done), 3) if done else None,
                          "added_since_previous_capture": sorted(symbols - prior_symbols) if prior_symbols else [],
                          "removed_since_previous_capture": sorted(prior_symbols - symbols) if prior_symbols else []})
            prior_symbols = symbols
        evaluated = [r for r in records if r.get("forecast_closed") and r.get("actual_return_pct") is not None]
        total = len(evaluated)
        return {"ok": True, "scope": "daily outcomes of the app's displayed long-term ten; separate from DAY scanner and long-term success",
                "forecast_method": "mean_previous_5_completed_daily_returns_capped_5pct",
                "sample_size": total, "days": daily,
                "direction_accuracy_pct": round(100 * sum(bool(r.get("forecast_direction_correct")) for r in evaluated)/total, 1) if total else None,
                "mean_absolute_forecast_error_pct_points": round(sum(abs(r["forecast_error_pct_points"]) for r in evaluated)/total, 3) if total else None,
                "records": records}

    return {"installed": True, "ticker_count": len(TICKERS), "forecast": "prior five completed daily returns"}
