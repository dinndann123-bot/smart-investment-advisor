import unittest
from datetime import datetime, timezone

from timing_signals import annotate_and_record


class Store:
    def __init__(self):self.rows=[]
    def load(self,limit=3000):return list(self.rows[-limit:])
    def upsert(self,row):
        key=(row.get('scan_id'),row.get('ticker'),row.get('rank'))
        self.rows=[x for x in self.rows if (x.get('scan_id'),x.get('ticker'),x.get('rank'))!=key]
        self.rows.append(dict(row))


def eligible(price=10):
    return {'ticker':'TEST','rank':1,'price':price,'breakout_stage':'early_breakout','rvol':3,'rvol_reliable':True,
            'minute_volume_burst':2,'day_volume':200000,'historical_baseline_volume':20000,
            'dollar_volume':2000000,'spread_bps':20,'intraday_move_used_pct':70,
            'current_range_position':.7,'snapshot_gap_pct':2,'change_pct':3}


class TimingSignalsTests(unittest.TestCase):
    def test_entry_is_recorded_once_and_exit_at_target(self):
        store=Store();t=datetime(2026,9,24,14,0,tzinfo=timezone.utc)
        first=eligible();events=annotate_and_record([first],store,'scan-1',t)
        self.assertEqual(first['timing_signal'],'entry');self.assertEqual(len(events),1)
        again=eligible(10.1);events=annotate_and_record([again],store,'scan-2',t)
        self.assertEqual(again['timing_signal'],'active');self.assertEqual(len(events),0)
        target=eligible(10.21);events=annotate_and_record([target],store,'scan-3',t)
        self.assertEqual(target['timing_signal'],'exit');self.assertEqual(events[0]['reason'],'יעד רווח 2% הושג')

    def test_wide_spread_never_creates_entry(self):
        store=Store();row=eligible();row['spread_bps']=120
        events=annotate_and_record([row],store,'scan-1',datetime(2026,9,24,14,0,tzinfo=timezone.utc))
        self.assertEqual(row['timing_signal'],'watch');self.assertFalse(events)


if __name__=='__main__':unittest.main()
