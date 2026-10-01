import unittest

from fastapi import FastAPI

from scanner_async_v67 import install_async_scanner


class AsyncScannerHealthTests(unittest.TestCase):
    def test_closed_market_is_reported_as_closed_even_with_today_bar_data(self):
        scanner=install_async_scanner(FastAPI(),lambda **_:None)
        health=scanner["classify_market_data"]({
            "session":"closed",
            "diagnostic_sample":[{"todayBars":1,"market_session":"closed"}],
        })
        self.assertEqual(health["quality"],"market_closed")
        self.assertIn("סגור",health["message_he"])


if __name__=="__main__":
    unittest.main()
