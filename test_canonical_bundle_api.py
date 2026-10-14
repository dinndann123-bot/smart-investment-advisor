import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from canonical_bundle_api import install
from chart_api_v7 import _chart_feed, _trim_intraday_session


class CanonicalBundleTests(unittest.TestCase):
    def test_extended_intraday_chart_uses_sip_for_iex_accounts(self):
        self.assertEqual(_chart_feed("1D", "premarket", "iex"), "sip")
        self.assertEqual(_chart_feed("1D", "afterhours", "iex"), "sip")

    def test_regular_intraday_chart_keeps_configured_feed(self):
        self.assertEqual(_chart_feed("1D", "regular", "iex"), "iex")
        self.assertEqual(_chart_feed("1D", "regular", "sip"), "sip")

    def test_day_chart_during_regular_session_contains_only_todays_bars(self):
        now = datetime.fromisoformat("2026-10-14T13:33:00+00:00")
        points = [{"t": "2026-10-13T19:55:00Z"}, {"t": "2026-10-14T13:30:00Z"}]
        self.assertEqual(_trim_intraday_session(points, "1D", "regular", now), [points[1]])

    def test_day_chart_premarket_keeps_prior_close_context(self):
        now = datetime.fromisoformat("2026-10-14T12:00:00+00:00")
        points = [{"t": "2026-10-13T19:55:00Z"}, {"t": "2026-10-14T11:55:00Z"}]
        self.assertEqual(_trim_intraday_session(points, "1D", "premarket", now), points)

    def test_bundle_replaces_stale_legacy_quote_and_bars_from_canonical_source(self):
        app = FastAPI()

        @app.get("/api/stock/{symbol}/bundle")
        async def legacy_bundle(symbol: str, range: str = "1D"):
            return {"news": [{"title": "headline"}], "quote": {"price": 5.64}, "bars": [{"v": 5.64}]}

        now = datetime.now(timezone.utc)
        last_bar_at = (now - timedelta(minutes=21)).replace(second=0, microsecond=0).isoformat()

        async def quote(symbol):
            return {"symbol": symbol, "price": None, "previous_close": 90.0,
                    "change_percent": None, "price_timestamp": None, "source": "Alpaca",
                    "feed": "delayed_sip", "freshness": {"state": "stale", "age_seconds": 1300}}

        async def chart(symbol, range):
            return {"symbol": symbol, "range": range, "session": "premarket", "source": "Alpaca",
                    "feed": "sip", "delayed_minutes": 16, "generated_at": now.isoformat(),
                    "last_bar_at": last_bar_at,
                    "points": [{"t": last_bar_at, "o": 99, "h": 101, "l": 98, "c": 100, "v": 5000}]}

        install(app, {"quote": quote, "chart": chart})
        route = next(r for r in app.routes if getattr(r, "path", None) == "/api/stock/{symbol}/bundle")
        result = asyncio.run(route.endpoint("RIG", "1D"))

        self.assertEqual(result["quote"]["price"], 100.0)
        self.assertEqual(result["quote"]["price_source"], "latest_delayed_sip_bar_close")
        self.assertEqual(result["freshness"]["state"], "current_delayed")
        self.assertEqual(result["bars"][-1]["v"], 100)
        self.assertEqual(result["news"][0]["title"], "headline")
        self.assertEqual(result["data_integrity"]["quote_timestamp"], last_bar_at)

    def test_bundle_never_falls_back_to_previous_session_price(self):
        app = FastAPI()
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).replace(second=0, microsecond=0).isoformat()

        async def quote(symbol):
            return {"symbol": symbol, "price": None, "freshness": {"state": "stale"}, "source": "Alpaca"}

        async def chart(symbol, range):
            return {"symbol": symbol, "range": range, "session": "premarket", "source": "Alpaca",
                    "feed": "sip", "last_bar_at": yesterday, "generated_at": now.isoformat(),
                    "points": [{"t": yesterday, "o": 10, "h": 10, "l": 9, "c": 9.5, "v": 100}]}

        install(app, {"quote": quote, "chart": chart})
        route = next(r for r in app.routes if getattr(r, "path", None) == "/api/stock/{symbol}/bundle")
        result = asyncio.run(route.endpoint("RIG", "1D"))

        self.assertIsNone(result["quote"]["price"])
        self.assertEqual(result["freshness"]["state"], "previous_session")


if __name__ == "__main__":
    unittest.main()
