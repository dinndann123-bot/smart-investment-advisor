import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from strategy_health import build_strategy_health

NY = ZoneInfo("America/New_York")
VERSION = "strategy-learning-v6.8.5-session-aware"


def signal(ticker, date, rank, ret, *, version=VERSION):
    stamp = datetime.fromisoformat(f"{date}T10:00:00").replace(tzinfo=NY)
    return {"record_type":"scheduled_checkpoint","strategy_version":version,"trade_date":date,"ticker":ticker,"rank":rank,"epoch":stamp.timestamp(),"ret15m_pct":ret}


class StrategyHealthTests(unittest.TestCase):
    def test_empty_store_reports_waiting_without_fabricated_metrics(self):
        result = build_strategy_health([], {"connected":True}, VERSION)
        self.assertFalse(result["has_data"])
        self.assertEqual(result["status"], "waiting")
        self.assertIsNone(result["recent"])
        self.assertEqual(result["sample_count"], 0)
        self.assertTrue(result["production_weights_unchanged"])

    def test_uses_first_independent_top10_row_and_fixed_15m_outcome(self):
        now = datetime(2026,10,14,16,tzinfo=timezone.utc)
        rows = [signal("AAA","2026-10-13",1,1.5), signal("AAA","2026-10-13",2,-3.0), signal("BBB","2026-10-13",3,-1.0), signal("CCC","2026-10-13",1,8.0,version="old-version")]
        result = build_strategy_health(rows, {"connected":True}, VERSION, now=now)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["recent"]["hit1"], 50.0)
        self.assertEqual(result["recent"]["positive_rate"], 50.0)
        self.assertEqual(result["recent"]["expectancy_pct"], 0.25)
        self.assertEqual(result["recent"]["stops"], 50.0)
        self.assertEqual(result["status"], "watch")

    def test_database_unavailable_is_reported(self):
        result = build_strategy_health([], {"connected":False}, VERSION)
        self.assertEqual(result["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
