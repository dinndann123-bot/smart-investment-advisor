import unittest
from datetime import datetime, timezone

from scheduled_learning import (
    NY,
    _checkpoint_due,
    _session_close_utc,
    _shadow_profile,
)


class ScheduledLearningTests(unittest.TestCase):
    def test_checkpoint_accepts_small_scheduler_delay(self):
        now=datetime(2026,9,24,9,27,tzinfo=NY)
        self.assertEqual(_checkpoint_due(now,set()),'09:25_pre_open')

    def test_checkpoint_does_not_fabricate_late_capture(self):
        now=datetime(2026,9,24,10,5,tzinfo=NY)
        self.assertIsNone(_checkpoint_due(now,set()))

    def test_checkpoint_is_not_duplicated_after_restart(self):
        now=datetime(2026,9,24,9,26,tzinfo=NY)
        self.assertIsNone(_checkpoint_due(now,{'09:25_pre_open'}))

    def test_post_open_checkpoint_uses_completed_0945_window(self):
        now=datetime(2026,9,24,9,46,tzinfo=NY)
        self.assertEqual(_checkpoint_due(now,set()),'09:45_post_open')

    def test_day_ends_at_new_york_market_close(self):
        self.assertEqual(
            _session_close_utc('2026-09-23'),
            datetime(2026,9,23,20,0,tzinfo=timezone.utc),
        )

    def test_shadow_profile_separates_opportunity_and_entry_risk(self):
        profile=_shadow_profile({
            'rvol':3.2,'rvol_reliable':True,'minute_volume_burst':2.1,
            'day_volume':100000,'historical_baseline_volume':20000,
            'dollar_volume':2500000,'spread_bps':24,'price':25,
            'intraday_move_used_pct':75,'current_range_position':.72,
            'snapshot_gap_pct':2,'change_pct':3,
            'breakout_stage':'early_breakout',
        })
        self.assertEqual(profile['version'],'shadow-opportunity-entry-v3')
        self.assertEqual(profile['opportunity_score'],100)
        self.assertEqual(profile['entry_risk_score'],0)
        self.assertTrue(profile['research_eligible'])
        self.assertFalse(profile['production_effect'])

    def test_shadow_extreme_move_is_observed_but_entry_is_vetoed(self):
        profile=_shadow_profile({
            'rvol':20,'rvol_reliable':True,'minute_volume_burst':12,
            'day_volume':1000000,'historical_baseline_volume':10000,
            'dollar_volume':10000000,'spread_bps':20,'price':10,
            'intraday_move_used_pct':97,'current_range_position':.99,
            'snapshot_gap_pct':30,'change_pct':55,
            'breakout_stage':'already_extended',
        })
        self.assertTrue(profile['opportunity_detected'])
        self.assertFalse(profile['entry_window_ok'])
        self.assertFalse(profile['research_eligible'])
        self.assertIn('momentum_extreme',profile['entry_veto_reasons'])

    def test_shadow_rejects_untradable_spread_and_low_dollar_volume(self):
        profile=_shadow_profile({
            'rvol':4,'rvol_reliable':True,'minute_volume_burst':3,
            'day_volume':20000,'historical_baseline_volume':5000,
            'dollar_volume':400000,'spread_bps':180,'price':20,
            'intraday_move_used_pct':70,'current_range_position':.7,
            'snapshot_gap_pct':2,'change_pct':3,
            'breakout_stage':'early_breakout',
        })
        self.assertFalse(profile['opportunity_detected'])
        self.assertFalse(profile['entry_window_ok'])
        self.assertFalse(profile['research_eligible'])
        self.assertIn('wide_or_unknown_spread',profile['entry_veto_reasons'])


if __name__=='__main__':
    unittest.main()
