import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


WEEK = USAGE._QUOTA_WEEK_HOURS * 3600


def _anchor(reset, used, seen=0):
    return {"reset": reset, "first_seen": seen, "last_seen": seen, "max_used": used}


class MergeQuotaAnchorsTests(unittest.TestCase):
    def test_same_window_seen_on_two_machines_collapses_into_one_row(self):
        anchors = {"codex": [_anchor(1000, 30.0, seen=600)]}
        USAGE._merge_quota_anchors(anchors, {"codex": [
            {"reset": 1000 + USAGE._QUOTA_ANCHOR_JITTER - 1, "first_seen": 400,
             "last_seen": 900, "max_used": 71.0},
        ]})
        self.assertEqual(len(anchors["codex"]), 1)
        self.assertEqual(anchors["codex"][0]["max_used"], 71.0)
        self.assertEqual(anchors["codex"][0]["last_seen"], 900)

    def test_window_only_the_peer_saw_is_added(self):
        anchors = {}
        USAGE._merge_quota_anchors(
            anchors, {"grok": [_anchor(2000, 8.0, seen=1500)]})
        self.assertEqual([r["reset"] for r in anchors["grok"]], [2000])

    def test_lower_peer_reading_never_lowers_the_local_peak(self):
        anchors = {"codex": [_anchor(1000, 88.0, seen=900)]}
        USAGE._merge_quota_anchors(
            anchors, {"codex": [{"reset": 1000, "last_seen": 950, "max_used": 12.0}]})
        self.assertEqual(anchors["codex"][0]["max_used"], 88.0)

    def test_junk_in_a_peer_snapshot_is_dropped_without_creating_rows(self):
        anchors = {}
        USAGE._merge_quota_anchors(anchors, {
            "codex": [{"reset": "下周"}, {"reset": 0}, {"no": "reset"}, "nope", None],
            "notatool": [_anchor(1000, 5.0)],
            "grok": "notalist",
        })
        self.assertEqual(anchors, {})

    def test_unreadable_max_used_counts_as_zero_instead_of_raising(self):
        anchors = {}
        USAGE._merge_quota_anchors(
            anchors, {"codex": [{"reset": 1000, "max_used": "满", "last_seen": "刚刚"}]})
        self.assertEqual(anchors["codex"][0]["max_used"], 0.0)
        self.assertEqual(anchors["codex"][0]["last_seen"], 0)

    def test_empty_incoming_is_a_no_op(self):
        anchors = {"codex": [_anchor(1000, 30.0)]}
        USAGE._merge_quota_anchors(anchors, None)
        self.assertEqual(anchors, {"codex": [_anchor(1000, 30.0)]})


class AnchorCyclesTests(unittest.TestCase):
    def test_latest_window_still_running_is_marked_current(self):
        anchors = {"codex": [_anchor(5 * WEEK, 40.0), _anchor(6 * WEEK, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", WEEK, 8, 6 * WEEK - 1)
        self.assertEqual(len(cycles), 2)
        self.assertTrue(cycles[0][3])
        self.assertFalse(cycles[1][3])

    def test_latest_window_already_over_is_history_not_current(self):
        # 读数断了就不会再有新锚点,最后一条也会过期 —— 别再摆成「进行中」。
        anchors = {"codex": [_anchor(5 * WEEK, 40.0), _anchor(6 * WEEK, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", WEEK, 8, 6 * WEEK + 1)
        self.assertEqual(len(cycles), 2)
        self.assertFalse(any(c[3] for c in cycles))

    def test_two_future_resets_still_yield_exactly_one_current_cycle(self):
        # 重锚会留下两条 reset 都在未来的锚点。面板只认第一条 current,
        # 多标一条另一条就既不在当前卡片也不在历史里了。
        anchors = {"codex": [_anchor(6 * WEEK, 40.0), _anchor(6 * WEEK + 3600, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", WEEK, 8, 5 * WEEK)
        self.assertEqual(sum(1 for c in cycles if c[3]), 1)
        self.assertTrue(cycles[0][3])
        self.assertEqual(cycles[0][0], 6 * WEEK + 3600 - WEEK)

    def test_zero_percent_early_reset_starts_a_new_cycle_immediately(self):
        old_reset = 6 * WEEK
        new_reset = old_reset + 4 * 24 * 3600
        anchors = {"codex": [_anchor(old_reset, 58.0)]}

        USAGE._record_quota_anchor(
            anchors, "codex", new_reset, 0.0, new_reset - WEEK + 60
        )
        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", WEEK, 8, new_reset - WEEK + 60
        )

        self.assertTrue(anchors["codex"][-1]["confirmed_reset"])
        self.assertEqual(len(cycles), 2)
        self.assertTrue(cycles[0][3])
        self.assertEqual(cycles[0][0], new_reset - WEEK)
        self.assertEqual(cycles[0][2], 0.0)
        self.assertEqual(cycles[1][1], new_reset - WEEK)

    def test_idle_zero_percent_drift_does_not_open_another_cycle(self):
        old_reset = 6 * WEEK
        first_zero_reset = old_reset + 4 * 24 * 3600
        drifted_reset = first_zero_reset + 3600
        anchors = {"codex": [_anchor(old_reset, 58.0)]}

        USAGE._record_quota_anchor(
            anchors, "codex", first_zero_reset, 0.0, first_zero_reset - WEEK
        )
        USAGE._record_quota_anchor(
            anchors, "codex", drifted_reset, 0.0, drifted_reset - WEEK
        )
        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", WEEK, 8, drifted_reset - WEEK
        )

        self.assertTrue(anchors["codex"][-2]["confirmed_reset"])
        self.assertNotIn("confirmed_reset", anchors["codex"][-1])
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0][0], first_zero_reset - WEEK)

    def test_confirmed_peer_reset_is_kept_without_local_history(self):
        reset = 6 * WEEK
        anchors = {}
        USAGE._merge_quota_anchors(anchors, {"codex": [{
            "reset": reset,
            "last_seen": reset - WEEK,
            "max_used": 0.0,
            "confirmed_reset": True,
        }]})

        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", WEEK, 8, reset - WEEK
        )

        self.assertTrue(anchors["codex"][0]["confirmed_reset"])
        self.assertEqual(len(cycles), 1)
        self.assertTrue(cycles[0][3])

    def test_detail_limit_keeps_older_cycles_for_ui_disclosure(self):
        anchors = {
            "codex": [
                _anchor((index + 2) * WEEK, 10.0 + index)
                for index in range(12)
            ]
        }

        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", WEEK, USAGE._QUOTA_CYCLE_HISTORY, 20 * WEEK
        )

        self.assertEqual(len(cycles), 12)
        self.assertGreater(len(cycles), 8)
        self.assertFalse(any(cycle[3] for cycle in cycles))


class CycleSpecsTests(unittest.TestCase):
    def _run(self, payload, peer_anchors, now, existing=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "quota_cycles.json")
            if existing is not None:
                Path(path).write_text(json.dumps({"anchors": existing}), encoding="utf-8")
            with mock.patch.object(USAGE, "_QUOTA_ANCHOR_FILE", path):
                charted, missing, anchors = USAGE._quota_cycle_specs(
                    payload, [(USAGE._QUOTA_SELF_DEVICE, {}, None, {})], peer_anchors, now)
            saved = (json.loads(Path(path).read_text(encoding="utf-8"))["anchors"]
                     if os.path.exists(path) else {})
        return charted, missing, anchors, saved

    def test_stale_reading_keeps_the_stored_history(self):
        # 过期读数被 _quota_tool_reading 挡在门外,但历史周期不该跟着一起消失。
        charted, missing, anchors, _saved = self._run(
            {"codex": {"pw": 100.0, "rw": 6 * WEEK, "pw_stale": True}},
            [], 6 * WEEK, existing={"codex": [_anchor(5 * WEEK, 40.0)]})
        self.assertEqual(charted, ["codex"])
        self.assertNotIn("codex", missing)
        self.assertEqual([r["reset"] for r in anchors["codex"]], [5 * WEEK])

    def test_peer_anchors_fill_in_history_this_machine_never_saw(self):
        charted, missing, anchors, saved = self._run(
            {}, [{"codex": [_anchor(5 * WEEK, 40.0, seen=5 * WEEK)]}], 6 * WEEK)
        self.assertEqual(charted, ["codex"])
        self.assertNotIn("codex", missing)
        self.assertEqual([r["reset"] for r in anchors["codex"]], [5 * WEEK])
        # 别人的观测不回写自己的账,否则一份读数会在两台机器之间来回记。
        self.assertEqual(saved, {})

    def test_reading_seen_on_this_machine_is_persisted(self):
        charted, _missing, _anchors, saved = self._run(
            {"grok": {"pct": 54.0, "reset": 6 * WEEK, "window": "week"}}, [], 5 * WEEK)
        self.assertEqual(charted, ["grok"])
        self.assertEqual([r["reset"] for r in saved["grok"]], [6 * WEEK])

    def test_tool_with_neither_reading_nor_history_is_reported_missing(self):
        charted, missing, _anchors, _saved = self._run({}, [], 6 * WEEK)
        self.assertEqual(charted, [])
        self.assertEqual(missing, ["claude", "codex", "grok"])


class DeviceLedgerAnchorTests(unittest.TestCase):
    def test_peer_anchors_are_collected_even_when_the_snapshot_has_no_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "air.json").write_text(json.dumps({
                "_device": "air",
                "_quota_anchors": {"codex": [_anchor(5 * WEEK, 40.0)]},
            }), encoding="utf-8")
            Path(tmp, "self.json").write_text(json.dumps({
                "_device": "self",
                "_quota_anchors": {"codex": [_anchor(9 * WEEK, 40.0)]},
            }), encoding="utf-8")
            with mock.patch.object(USAGE, "_load_tokei_config",
                                   return_value={"sync_dir": tmp, "device_id": "self"}), \
                 mock.patch.object(USAGE, "_load_ledger", return_value={}):
                devices, peer_anchors = USAGE._quota_device_ledgers()
        # 没有 _ledger 的 peer 不参与 token 合并,但它的周期观测照收。
        self.assertEqual([name for name, _t, _s, _d in devices], [USAGE._QUOTA_SELF_DEVICE])
        # 自己那份快照是本地锚点的副本,再并一遍就是自己跟自己对账。
        self.assertEqual(len(peer_anchors), 1)
        self.assertEqual([r["reset"] for r in peer_anchors[0]["codex"]], [5 * WEEK])


class SyncSnapshotAnchorTests(unittest.TestCase):
    def _snapshot(self, anchors):
        written = {}
        with mock.patch.object(USAGE, "compute", return_value={}), \
             mock.patch.object(USAGE, "_load_json", return_value={}), \
             mock.patch.object(USAGE, "_load_ledger", return_value={}), \
             mock.patch.object(USAGE, "_load_quota_anchors", return_value=anchors), \
             mock.patch.object(USAGE, "_write_configured_sync_snapshot",
                               side_effect=lambda d: written.update(d) or True):
            self.assertEqual(USAGE.write_sync_snapshot(), 0)
        return written

    def test_local_anchors_ride_along_with_the_snapshot(self):
        anchors = {"codex": [_anchor(5 * WEEK, 40.0)]}
        self.assertEqual(self._snapshot(anchors)["_quota_anchors"], anchors)

    def test_key_is_omitted_when_there_is_nothing_to_share(self):
        self.assertNotIn("_quota_anchors", self._snapshot({}))


if __name__ == "__main__":
    unittest.main()
