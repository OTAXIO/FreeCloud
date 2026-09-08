from __future__ import annotations

import unittest

from wyy_assist.tracker import StableStateTracker


class TrackerTests(unittest.TestCase):
    def test_debounces_and_counts_success_transition_once(self) -> None:
        tracker = StableStateTracker(consecutive_hits=2)
        self.assertIsNone(tracker.observe("ready"))
        ready = tracker.observe("ready")
        self.assertIsNotNone(ready)
        assert ready is not None
        self.assertTrue(ready.changed)

        self.assertIsNone(tracker.observe("success"))
        success = tracker.observe("success")
        self.assertIsNotNone(success)
        assert success is not None
        self.assertEqual(success.success_count, 1)
        self.assertTrue(success.changed)

        repeated = tracker.observe("success")
        self.assertIsNotNone(repeated)
        assert repeated is not None
        self.assertEqual(repeated.success_count, 1)
        self.assertFalse(repeated.changed)

    def test_unknown_breaks_candidate_streak(self) -> None:
        tracker = StableStateTracker(consecutive_hits=2)
        self.assertIsNone(tracker.observe("ad"))
        self.assertIsNone(tracker.observe(None))
        self.assertIsNone(tracker.observe("ad"))
        transition = tracker.observe("ad")
        self.assertIsNotNone(transition)

    def test_counts_each_transition_into_ad(self) -> None:
        tracker = StableStateTracker(consecutive_hits=1)
        first = tracker.observe("ad")
        assert first is not None
        self.assertEqual(first.ad_count, 1)
        tracker.observe("ready")
        second = tracker.observe("ad")
        assert second is not None
        self.assertEqual(second.ad_count, 2)


if __name__ == "__main__":
    unittest.main()
