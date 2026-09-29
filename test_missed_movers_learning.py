import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import missed_movers_learning as missed_module
from missed_movers_learning import _feature_group, _summary_from_reports, _top10_for_day


class FakeApp:
    def __init__(self):
        self.routes = {}

    def post(self, path):
        return self._route("POST", path)

    def get(self, path):
        return self._route("GET", path)

    def _route(self, method, path):
        def register(function):
            self.routes[(method, path)] = function
            return function
        return register

    def on_event(self, _event):
        return lambda function: function


class FakeStore:
    def __init__(self, rows):
        self.rows = list(rows)

    def load(self, _limit):
        return list(self.rows)

    def upsert(self, row):
        self.rows.append(dict(row))


class MissedMoversLearningTests(unittest.TestCase):
    def test_top10_collapses_repeated_scans_and_ignores_non_scanner_rows(self):
        rows = [
            {"ticker": "NVDA", "rank": 7, "epoch": 1790701200},
            {"ticker": "NVDA", "rank": 2, "epoch": 1790701260},
            {"ticker": "AAPL", "rank": 1, "epoch": 1790701200, "record_type": "timing_event"},
            {"ticker": "TSLA", "rank": 11, "epoch": 1790701200},
            {"ticker": "AMD", "rank": 1, "epoch": 1790701200, "record_type": "missed_mover_observation"},
        ]
        day = datetime.fromtimestamp(1790701200, timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        result = _top10_for_day(rows, day, "strategy-v1")
        self.assertEqual(set(result), {"NVDA"})
        self.assertEqual(result["NVDA"]["rank"], 2)

    def test_top10_rejects_other_strategy_and_other_trading_day(self):
        day = "2026-09-29"
        utc_epoch = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc).timestamp()
        rows = [
            {"ticker": "A", "rank": 1, "epoch": utc_epoch, "strategy_version": "old"},
            {"ticker": "B", "rank": 1, "epoch": utc_epoch - 86400},
        ]
        self.assertEqual(_top10_for_day(rows, day, "current"), {})

    def test_capture_rate_uses_captured_plus_missed_eligible_movers(self):
        result = _summary_from_reports([
            {"eligible_stock_movers": 10, "eligible_top10_overlap": 4, "eligible_false_negatives": 6},
            {"eligible_stock_movers": 5, "eligible_top10_overlap": 3, "eligible_false_negatives": 2},
        ])
        self.assertEqual(result["eligible_movers"], 15)
        self.assertEqual(result["captured"], 7)
        self.assertEqual(result["missed"], 8)
        self.assertEqual(result["capture_rate_pct"], 46.7)

    def test_feature_group_reports_missing_data_coverage(self):
        result = _feature_group([
            {"move_pct": 12.0, "premarket_gap_pct": 2.0, "premarket_volume": 1000, "premarket_high": 11, "premarket_low": 10, "verified_current_day": True},
            {"move_pct": 10.0, "premarket_gap_pct": None, "premarket_volume": None, "verified_current_day": False},
        ])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["avg_move_pct"], 11.0)
        self.assertEqual(result["premarket_gap_coverage"], 1)
        self.assertEqual(result["premarket_volume_coverage"], 1)
        self.assertEqual(result["verified_current_day"], 1)

    def test_end_of_day_audit_persists_captured_and_missed_movers(self):
        trade_day = "2026-09-29"
        store = FakeStore([{
            "ticker": "AAA", "rank": 3,
            "epoch": datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc).timestamp(),
        }])
        core = type("Core", (), {"ALPACA_KEY": "key", "ALPACA_SECRET": "secret", "ALPACA_FEED": "iex"})()
        app = FakeApp()

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                value = datetime(2026, 9, 29, 20, 15, tzinfo=timezone.utc)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)

        async def movers(_core):
            return [
                {"symbol": "AAA", "move_pct": 12.0, "price": 22.0},
                {"symbol": "BBB", "move_pct": 15.0, "price": 30.0},
            ], {"status": "ok", "count": 2}

        async def asset(_core, symbol):
            return {"name": f"{symbol} Common Stock", "status": "active", "tradable": True}

        async def snapshot(_core, _symbol):
            return {"dailyBar": {"t": f"{trade_day}T13:30:00Z", "v": 100}, "prevDailyBar": {"c": 20}}

        async def premarket(_core, _symbol, _day):
            return {"last": 21.0, "volume": 1000, "high": 22.0, "low": 20.0}

        missed_module.install_missed_movers_learning(app, core, store, "strategy-current")
        with patch.object(missed_module, "datetime", FixedDateTime), \
             patch.object(missed_module, "_is_market_day", return_value=True), \
             patch.object(missed_module, "_sip_movers", side_effect=movers), \
             patch.object(missed_module, "_asset", side_effect=asset), \
             patch.object(missed_module, "_iex_snapshot", side_effect=snapshot), \
             patch.object(missed_module, "_premarket", side_effect=premarket):
            result = asyncio.run(app.routes[("POST", "/api/learning/missed-movers")]())

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["eligible_stock_movers"], 2)
        self.assertEqual(result["eligible_top10_overlap"], 1)
        self.assertEqual(result["eligible_false_negatives"], 1)
        self.assertEqual(result["capture_rate_pct"], 50.0)
        self.assertEqual(result["missed"][0]["symbol"], "BBB")
        self.assertEqual(result["feature_comparison"]["captured"]["count"], 1)
        self.assertEqual(result["feature_comparison"]["missed"]["count"], 1)
        self.assertTrue(any(row.get("record_type") == "missed_mover_report" for row in store.rows))


if __name__ == "__main__":
    unittest.main()
