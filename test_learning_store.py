import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import learning_store


class LearningStoreHistoryTests(unittest.TestCase):
    def test_legacy_store_migrates_and_type_history_is_not_crowded_out(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"learning.sqlite3"
            previous_path=learning_store.SQLITE_PATH
            learning_store.SQLITE_PATH=path
            try:
                with sqlite3.connect(path) as con:
                    con.execute("""CREATE TABLE strategy_learning_signals (
                        signal_id TEXT PRIMARY KEY, scan_id TEXT, ticker TEXT NOT NULL,
                        signal_epoch REAL NOT NULL, signal_time TEXT, payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                    for i in range(3205):
                        record_type="scheduled_checkpoint" if i%2==0 else "scanner_signal"
                        row={"record_type":record_type,"ticker":f"T{i%100}","rank":1,
                             "epoch":float(i),"signal_time":f"2026-09-{(i%28)+1:02d}T09:45:00Z"}
                        con.execute("INSERT INTO strategy_learning_signals(signal_id,scan_id,ticker,signal_epoch,signal_time,payload) VALUES(?,?,?,?,?,?)",
                                    (f"scan-{i}",f"scan-{i}",row["ticker"],row["epoch"],row["signal_time"],json.dumps(row)))

                learning_store.initialize()
                checkpoints=learning_store.load_by_type("scheduled_checkpoint")
                self.assertEqual(len(checkpoints),1603)
                self.assertEqual(checkpoints[0]["epoch"],0.0)
                self.assertEqual(checkpoints[-1]["epoch"],3204.0)
                self.assertEqual(len(learning_store.load_by_type("scheduled_checkpoint",since_epoch=3200)),3)
                self.assertEqual(learning_store.count(),3205)
                self.assertEqual(learning_store.count("scanner_signal"),1602)
                self.assertEqual(learning_store.status()["stored_signals"],3205)
                self.assertEqual(learning_store.status()["scheduled_checkpoints"],1603)
            finally:
                learning_store.SQLITE_PATH=previous_path


if __name__=="__main__":
    unittest.main()
