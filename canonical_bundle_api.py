"""Keep the legacy stock-bundle contract on the canonical market-data APIs."""
import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

NY = ZoneInfo("America/New_York")


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bars(points):
    out = []
    for point in points or []:
        close = point.get("c")
        if close is None:
            continue
        out.append({
            "d": point.get("t"), "t": point.get("t"),
            "o": point.get("o"), "h": point.get("h"), "l": point.get("l"),
            "c": close, "v": close, "volume": point.get("v") or 0,
        })
    return out


def install(app, market_api):
    """Override a legacy bundle route so UI prices and charts share one source.

    The prior endpoint is retained only to preserve its news payload. Its quote
    and bars are always replaced by the canonical timestamped endpoints.
    """
    old = next((r for r in app.routes if getattr(r, "path", None) == "/api/stock/{symbol}/bundle"
                and "GET" in getattr(r, "methods", set())), None)
    old_bundle = old.endpoint if old else None
    if old is not None:
        app.router.routes.remove(old)

    async def legacy_news(symbol, range_name):
        if old_bundle is None:
            return {}
        try:
            value = old_bundle(symbol=symbol, range=range_name)
            return await value if inspect.isawaitable(value) else value
        except Exception:
            return {}

    async def canonical_bundle(symbol: str, range: str = "1D"):
        symbol = symbol.upper().strip()
        legacy_task = asyncio.create_task(legacy_news(symbol, range))
        quote_task = asyncio.create_task(market_api["quote"](symbol))
        chart_task = asyncio.create_task(market_api["chart"](symbol, range))
        legacy, quote, chart = await asyncio.gather(legacy_task, quote_task, chart_task, return_exceptions=True)
        if isinstance(quote, Exception):
            quote = {"symbol": symbol, "price": None, "change_percent": None, "price_timestamp": None,
                     "source": "Alpaca", "feed": None, "freshness": {"state": "unavailable", "age_seconds": None}}
        if isinstance(chart, Exception):
            chart = {"symbol": symbol, "points": [], "source": "Alpaca", "feed": None,
                     "last_bar_at": None, "generated_at": datetime.now(timezone.utc).isoformat(), "delayed_minutes": None}
        if isinstance(legacy, Exception) or not isinstance(legacy, dict):
            legacy = {}

        points = chart.get("points") or []
        bars = _bars(points)
        last = bars[-1] if bars else None
        last_at = chart.get("last_bar_at")
        now = datetime.now(timezone.utc)
        session = chart.get("session")
        quote_freshness = dict(quote.get("freshness") or {})
        quote_state = quote_freshness.get("state", "unavailable")

        # In extended hours a closed 5-minute SIP bar is the most precise
        # canonical price. Account for the 5-minute bar's start timestamp when
        # checking age; the provider adds a 16-minute SIP delay.
        latest_close = float(last["c"]) if last else None
        last_dt = _parse_time(last_at)
        if session in {"premarket", "afterhours"} and last_dt:
            effective_age = (now - (last_dt + timedelta(minutes=5))).total_seconds()
            max_age = 20 * 60
            same_session_day = last_dt.astimezone(NY).date() == now.astimezone(NY).date()
            if same_session_day and -60 <= effective_age <= max_age and latest_close and latest_close > 0:
                quote["price"] = round(latest_close, 4)
                quote["change_percent"] = (
                    round((latest_close / float(quote["previous_close"]) - 1) * 100, 3)
                    if quote.get("previous_close") else quote.get("change_percent")
                )
                quote["price_timestamp"] = last_at
                quote["price_source"] = "latest_delayed_sip_bar_close"
                quote_state = "current_delayed"
                quote_freshness.update({"state": quote_state, "age_seconds": round(max(0, effective_age), 1),
                                        "max_age_seconds": max_age, "timestamp_is_today": True,
                                        "usable_as_current_price": True})
            else:
                quote["price"] = None
                quote_state = "stale" if same_session_day else "previous_session"
                quote_freshness.update({"state": quote_state, "age_seconds": round(max(0, effective_age), 1),
                                        "max_age_seconds": max_age, "timestamp_is_today": same_session_day,
                                        "usable_as_current_price": False})
        elif quote_state not in {"current", "current_delayed", "market_closed"}:
            quote["price"] = None

        quote["change"] = quote.get("change_percent")
        quote["date"] = quote.get("price_timestamp")
        quote["freshness"] = quote_freshness
        result = dict(legacy)
        result.update({
            "symbol": symbol, "range": chart.get("range", range),
            "provider": chart.get("source", "Alpaca"), "feed": chart.get("feed"),
            "quote": quote, "bars": bars, "news": legacy.get("news") or [],
            "freshness": {**quote_freshness, "last_bar_at": last_at, "generated_at": chart.get("generated_at")},
            "generated_at": chart.get("generated_at"),
            "data_integrity": {"quote_source": quote.get("price_source"), "chart_feed": chart.get("feed"),
                               "quote_timestamp": quote.get("price_timestamp"), "last_bar_at": last_at,
                               "freshness": quote_state},
        })
        return result

    app.add_api_route("/api/stock/{symbol}/bundle", canonical_bundle, methods=["GET"], name="canonical_stock_bundle")
    return canonical_bundle
