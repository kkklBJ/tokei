import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import quote

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path, records, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record) + "\n")


def usage_line(sid, timestamp, loop, prompt, cached, completion, reasoning):
    return {
        "ts": timestamp,
        "msg": "shell.turn.inference_done",
        "sid": sid,
        "ctx": {
            "loop_index": loop,
            "prompt_tokens": prompt,
            "cached_prompt_tokens": cached,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
        },
    }


class GrokUsageTests(unittest.TestCase):
    def setUp(self):
        self.old_home = USAGE.GROK_HOME
        self.old_dir = USAGE.GROK_DIR
        self.old_log = USAGE.GROK_LOG
        self.old_cache = USAGE._SCAN_CACHE_FILE

    def tearDown(self):
        USAGE.GROK_HOME = self.old_home
        USAGE.GROK_DIR = self.old_dir
        USAGE.GROK_LOG = self.old_log
        USAGE._SCAN_CACHE_FILE = self.old_cache

    def configure(self, root):
        USAGE.GROK_HOME = str(root)
        USAGE.GROK_DIR = str(root / "sessions")
        USAGE.GROK_LOG = str(root / "logs" / "unified.jsonl")
        USAGE._SCAN_CACHE_FILE = str(root / "scan-cache.json")

    def create_session(self, root, sid, project, timestamp, with_signals=True):
        session = root / "sessions" / quote(project, safe="") / sid
        session.mkdir(parents=True)
        write_json(session / "summary.json", {
            "info": {"id": sid},
            "created_at": timestamp,
            "updated_at": timestamp,
            "current_model_id": "grok-4.5",
        })
        if with_signals:
            write_json(session / "signals.json", {
                "turnCount": 3,
                "toolCallCount": 2,
                "sessionDurationSeconds": 60,
                "contextTokensUsed": 1000,
                "contextWindowTokens": 10000,
                "latencySampleCount": 2,
                "avgTimeToFirstTokenMs": 500,
                "avgResponseTimeMs": 1500,
            })
        write_jsonl(session / "events.jsonl", [
            {"type": "turn_started"},
            {"type": "turn_ended", "outcome": "completed"},
            {"type": "turn_ended", "outcome": "cancelled"},
            {"type": "turn_ended", "outcome": "error"},
        ])
        (session / "updates.jsonl").write_text("", encoding="utf-8")
        return session

    def test_real_usage_is_split_deduplicated_incremental_and_old_records_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            sid = "019f-test-session"
            self.create_session(root, sid, "/tmp/grok-project", now)
            log = root / "logs" / "unified.jsonl"
            old_format = {"ts": now, "msg": "shell.turn.inference_done", "sid": sid,
                          "ctx": {"loop_index": 0, "model_elapsed_ms": 100}}
            first = usage_line(sid, now, 1, 1000, 800, 100, 30)
            second = usage_line(sid, now, 2, 500, 100, 50, 10)
            write_jsonl(log, [old_format, first, first, second])

            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_grok(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_grok_usage_record",
                side_effect=AssertionError("unchanged Grok log was reparsed"),
            ):
                cached_result = USAGE.scan_grok(USAGE.range_bounds(), cache)

            later = (datetime.now().astimezone() + timedelta(seconds=1)).replace(microsecond=0).isoformat()
            write_jsonl(log, [usage_line(sid, later, 3, 200, 150, 20, 5)], mode="a")
            appended = USAGE.scan_grok(USAGE.range_bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 600)
        self.assertEqual(usage["cr"], 900)
        self.assertEqual(usage["out"], 110)
        self.assertEqual(usage["reason"], 40)
        self.assertAlmostEqual(usage["cost"], 0.00237, places=8)
        self.assertAlmostEqual(usage["models"]["grok-4.5"]["cost"], 0.00237, places=8)
        self.assertEqual(usage["usage_calls"], 2)
        self.assertEqual(usage["errors"], 1)
        self.assertEqual(usage["cancellations"], 1)
        self.assertEqual(cached_result["ranges"]["all"]["usage_calls"], 2)
        self.assertEqual(appended["ranges"]["all"]["usage_calls"], 3)
        self.assertEqual(len(cache["grok_usage"]["records"]), 3)

    def test_same_inode_rewrite_invalidates_incremental_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            sid = "019f-rewrite-session"
            self.create_session(root, sid, "/tmp/rewrite", now, with_signals=False)
            log = root / "logs" / "unified.jsonl"
            write_jsonl(log, [usage_line(sid, now, 1, 1000, 800, 100, 30)])
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            first = USAGE.scan_grok(USAGE.range_bounds(), cache)

            write_jsonl(log, [usage_line(sid, now, 1, 2000, 700, 200, 40)])
            second = USAGE.scan_grok(USAGE.range_bounds(), cache)

        self.assertEqual(first["ranges"]["all"]["in"], 200)
        self.assertEqual(second["ranges"]["all"]["in"], 1300)
        self.assertEqual(second["ranges"]["all"]["cr"], 700)
        self.assertEqual(second["ranges"]["all"]["usage_calls"], 1)

    def test_daily_wrapped_and_projects_use_real_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0)
            timestamp = now.isoformat()
            day_key = now.date().isoformat()
            sid = "019f-project-session"
            project = "/tmp/grok-build-project"
            self.create_session(root, sid, project, timestamp, with_signals=False)
            write_jsonl(root / "logs" / "unified.jsonl", [
                usage_line(sid, timestamp, 1, 1000, 800, 100, 30),
            ])
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_grok(USAGE.range_bounds(), cache)
            USAGE._cache_dashboard_days(cache, USAGE._GROK_DAYS_CACHE_KEY, result["days"])
            USAGE._save_scan_cache(cache)

            daily = USAGE.build_daily_costs("all", refresh=False)
            wrapped = USAGE.build_wrapped("all", refresh=False)
            output = io.StringIO()
            with mock.patch.object(USAGE, "compute"), contextlib.redirect_stdout(output):
                USAGE.projects()
            projects = json.loads(output.getvalue())

        row = next(item for item in daily["daily"] if item["date"] == day_key)
        self.assertEqual((row["g_in"], row["g_cr"], row["g_out"], row["g_reason"]),
                         (200, 800, 70, 30))
        self.assertEqual(row["tokens"], 1100)
        self.assertEqual(wrapped["total_tokens"], 1100)
        self.assertEqual(wrapped["hours"][now.hour], 1100)
        project_row = next(item for item in projects if item["path"] == project)
        self.assertEqual(project_row["sessions"], 1)
        self.assertEqual(project_row["tokens"], 1100)
        self.assertEqual(project_row["top_model"], "Grok 4.5 (Grok Build)")

    def test_cost_flows_to_card_dashboard_wrapped_and_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0)
            timestamp = now.isoformat()
            day_key = now.date().isoformat()
            sid = "019f-cost-session"
            project = "/tmp/grok-cost-project"
            self.create_session(root, sid, project, timestamp, with_signals=False)
            write_jsonl(root / "logs" / "unified.jsonl", [
                usage_line(sid, timestamp, 1, 2_000_000, 1_000_000, 200_000, 50_000),
            ])
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_grok(USAGE.range_bounds(), cache)
            USAGE._cache_dashboard_days(cache, USAGE._GROK_DAYS_CACHE_KEY, result["days"])
            USAGE._save_scan_cache(cache)

            daily = USAGE.build_daily_costs("all", refresh=False)
            wrapped = USAGE.build_wrapped("all", refresh=False)
            output = io.StringIO()
            with mock.patch.object(USAGE, "compute"), contextlib.redirect_stdout(output):
                USAGE.projects()
            projects = json.loads(output.getvalue())

        expected = 3.5
        usage = result["ranges"]["all"]
        self.assertAlmostEqual(usage["cost"], expected, places=6)
        self.assertAlmostEqual(usage["models"]["grok-4.5"]["cost"], expected, places=6)
        row = next(item for item in daily["daily"] if item["date"] == day_key)
        self.assertEqual(row["grok"], expected)
        self.assertEqual(row["total"], expected)
        model = next(item for item in daily["models"] if item["tool"] == "grok")
        self.assertEqual(model["cost"], expected)
        self.assertAlmostEqual(wrapped["total_cost"], expected, places=6)
        project_row = next(item for item in projects if item["path"] == project)
        self.assertAlmostEqual(project_row["cost"], expected, places=6)

    def test_grok_46_uses_high_context_price_at_200k_prompt_tokens(self):
        below_threshold = {"in": 149_999, "cr": 50_000, "out": 10_000, "reason": 0}
        at_threshold = {"in": 150_000, "cr": 50_000, "out": 10_000, "reason": 0}

        self.assertAlmostEqual(
            USAGE._grok_usage_cost(below_threshold, "grok-4.6"),
            0.384998,
            places=8,
        )
        self.assertAlmostEqual(
            USAGE._grok_usage_cost(at_threshold, "grok-4.6"),
            0.77,
            places=8,
        )

    def test_usage_is_classified_by_inference_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0)
            yesterday = now - timedelta(days=1)
            sid = "019f-cross-day-session"
            self.create_session(root, sid, "/tmp/cross-day", now.isoformat(), with_signals=False)
            write_jsonl(root / "logs" / "unified.jsonl", [
                usage_line(sid, yesterday.isoformat(), 1, 2000, 1000, 200, 50),
                usage_line(sid, now.isoformat(), 2, 1000, 800, 100, 30),
            ])
            result = USAGE.scan_grok(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

        today = result["ranges"]["today"]
        previous = result["ranges"]["yesterday"]
        self.assertEqual(today["in"] + today["cr"] + today["out"] + today["reason"], 1100)
        self.assertEqual(previous["in"] + previous["cr"] + previous["out"] + previous["reason"], 2200)


if __name__ == "__main__":
    unittest.main()
