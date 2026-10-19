import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE
import test_codex_dedup as fixtures


class ProjectAccountingTests(unittest.TestCase):
    def test_ranking_includes_codex_deduplicated_tokens_and_cost(self):
        day = {"in": 100, "cached": 90, "out": 10, "reason": 4, "cost": 7.5}
        cache = {"codex": {
            "canonical": {"proj": "/tmp/project", "days": {"2024-01-08": day}},
            "replay": {"proj": "/tmp/project", "days": {}},
        }}
        with mock.patch.object(USAGE, "_load_ledger", return_value={}):
            wrapped = USAGE.build_wrapped("all", refresh=False, _cache=cache)
        self.assertEqual(wrapped["projects"], [
            {"name": "project", "tokens": 110, "cost": 7.5, "cost_cny": 0},
        ])

        with mock.patch.object(USAGE, "compute"), \
             mock.patch.object(USAGE, "_load_scan_cache", return_value=cache), \
             mock.patch.object(USAGE, "_detect_local_servers", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            USAGE.projects()
        project = json.loads(output.getvalue())[0]
        self.assertEqual((project["tokens"], project["cost"]), (110, 7.5))

    def test_project_metadata_is_backfilled_without_reparsing_usage(self):
        fixture = fixtures.CodexScanDedupTests()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-project.jsonl"
            path.write_text("\n".join([
                fixture.session_meta("project"),
                fixture.token_count("2024-01-08T00:01:00Z", (100, 80, 10, 4), (100, 80, 10, 4)),
            ]) + "\n")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(Path(tmp) / "archive")), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(Path(tmp) / "cache.json")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                USAGE.scan_codex(fixture.bounds(), cache)
                entry = cache["codex"][str(path.resolve())]
                self.assertEqual(entry.get("proj"), "/tmp/project")
                entry.pop("proj")  # An existing installed cache predates this field.
                with mock.patch.object(USAGE, "_iter_codex_usage_records", side_effect=AssertionError("usage must remain cached")):
                    USAGE.scan_codex(fixture.bounds(), cache)
                self.assertEqual(entry.get("proj"), "/tmp/project")
