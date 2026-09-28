import asyncio
import unittest
from datetime import datetime, timezone

from fastapi import FastAPI

from live_signals_canonical import install


class FakeStore:
    def load(self, _limit):
        now=datetime.now(timezone.utc).isoformat()
        return [
            {"ticker":"AMPX","signal_time":now,"signal_price":10,"score":74,
             "scan_id":"scan-1","ret15m_pct":1.25},
            {"ticker":"HAL","signal_time":now,"signal_price":33,"score":69,
             "scan_id":"scan-1"},
        ]

    def status(self):
        return {"backend":"postgresql","durable":True,"stored_signals":2,"connected":True}


class CanonicalLiveSignalsTests(unittest.TestCase):
    def test_summary_surfaces_durable_scanner_records_without_fabrication(self):
        app=FastAPI();install(app,FakeStore())
        route=next(r for r in app.routes if getattr(r,"path",None)=="/api/live-signals/summary")
        payload=asyncio.run(route.endpoint(refresh=True))
        self.assertEqual(payload["storage"]["backend"],"postgresql")
        self.assertEqual(payload["today"]["signals"],2)
        self.assertEqual(payload["today"]["evaluated"],1)
        self.assertEqual(payload["recent"][0]["status"],"target1")
        self.assertIsNone(payload["recent"][1]["current_return_pct"])


if __name__ == "__main__":
    unittest.main()
