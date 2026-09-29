import unittest
from pathlib import Path


class ScannerOutputTruthTests(unittest.TestCase):
    def test_source_contains_score_and_risk_guards(self):
        source=Path("scanner_core.py").read_text(encoding="utf-8")
        self.assertIn("x['score']=min(94",source)
        self.assertIn("volume<20000",source)
        self.assertIn("not relevant(symbol,item)",source)

    def test_ui_loads_long_prices_and_full_ticker_badges(self):
        source=Path("index.html").read_text(encoding="utf-8")
        self.assertIn('.slice(0,5)',source)
        self.assertIn('loadMarketIndexes();refreshAll();',source)
        self.assertNotIn('s.price?money(s.price):"API"',source)
        self.assertIn('/api/learning/missed-movers/summary',source)
        self.assertIn('learnMissedSymbols',source)


if __name__ == "__main__":
    unittest.main()
