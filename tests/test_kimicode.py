import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def status(timestamp, message_id, usage):
    return {
        "timestamp": timestamp,
        "message": {
            "type": "StatusUpdate",
            "payload": {"message_id": message_id, "token_usage": usage},
        },
    }


def subagent(timestamp, agent_id, message_id, usage):
    return {
        "timestamp": timestamp,
        "message": {
            "type": "SubagentEvent",
            "payload": {
                "agent_id": agent_id,
                "event": status(timestamp, message_id, usage)["message"],
            },
        },
    }


class KimiCodeScanTests(unittest.TestCase):
    def create_session(self, root):
        project = "/tmp/kimi-project"
        project_hash = hashlib.md5(project.encode("utf-8")).hexdigest()
        session_dir = Path(root) / "sessions" / project_hash / "session-1"
        session_dir.mkdir(parents=True)
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        timestamp = now.timestamp()
        records = [
            {"type": "metadata", "protocol_version": "1"},
            status(timestamp, "message-1", {
                "input_other": 100,
                "output": 20,
                "input_cache_read": 30,
                "input_cache_creation": 5,
            }),
            # Same Agent scope and message ID is a duplicate replay.
            status(timestamp, "message-1", {"input_other": 999, "output": 999}),
            # A subagent may legitimately receive the same provider message ID.
            subagent(timestamp, "agent-1", "message-1", {
                "input_other": 40,
                "output": 8,
                "input_cache_read": 10,
                "input_cache_creation": 2,
            }),
            {"timestamp": timestamp, "message": {"type": "StatusUpdate", "payload": {
                "token_usage": {"input_other": 10, "output": 5},
            }}},
        ]
        wire = session_dir / "wire.jsonl"
        wire.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n{broken\n",
            encoding="utf-8",
        )
        (Path(root) / "kimi.json").write_text(json.dumps({
            "work_dirs": [{"path": project, "kaos": "local"}],
        }), encoding="utf-8")
        return wire, now, project

    def create_modern_session(self, root):
        project = "/tmp/kimi-modern-project"
        session_dir = Path(root) / "sessions" / "wd_kimi-modern_deadbeef" / "session-modern"
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        timestamp_ms = int(now.timestamp() * 1000)
        (session_dir / "state.json").parent.mkdir(parents=True)
        (session_dir / "state.json").write_text(json.dumps({
            "id": "session-modern",
            "version": 2,
            "cwd": project,
            "agents": {
                "main": {"type": "main"},
                "agent-1": {"type": "sub", "parentAgentId": "main"},
            },
        }), encoding="utf-8")

        def usage(time_offset, inp, out, cr=0, cw=0, scope="turn"):
            return {
                "type": "usage.record",
                "time": timestamp_ms + time_offset,
                "usageScope": scope,
                "model": "moonshot/kimi-k3",
                "usage": {
                    "inputOther": inp,
                    "output": out,
                    "inputCacheRead": cr,
                    "inputCacheCreation": cw,
                },
            }

        main_wire = session_dir / "agents" / "main" / "wire.jsonl"
        main_wire.parent.mkdir(parents=True)
        main_wire.write_text("\n".join(json.dumps(record) for record in [
            {"type": "metadata", "protocol_version": "1.5", "created_at": timestamp_ms},
            usage(1, 100, 20, 30, 5),
            usage(2, 10, 5, scope="session"),
        ]) + "\n", encoding="utf-8")

        sub_wire = session_dir / "agents" / "agent-1" / "wire.jsonl"
        sub_wire.parent.mkdir(parents=True)
        sub_wire.write_text("\n".join(json.dumps(record) for record in [
            {"type": "metadata", "protocol_version": "1.5", "created_at": timestamp_ms},
            usage(3, 40, 8, 10, 2),
        ]) + "\n", encoding="utf-8")
        return (main_wire, sub_wire), now, project

    def scan(self, root, cache=None):
        old_root = USAGE.KIMI_CODE_DIR
        USAGE.KIMI_CODE_DIR = str(root)
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            result = USAGE.scan_kimicode(USAGE.range_bounds(), scan_cache)
        finally:
            USAGE.KIMI_CODE_DIR = old_root
        return result, scan_cache

    def test_wire_usage_includes_scoped_subagents_and_splits_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            wire, now, project = self.create_session(tmp)
            result, cache = self.scan(tmp)

            with mock.patch.object(
                USAGE, "_scan_kimi_wire", side_effect=AssertionError("unchanged wire was rescanned")
            ):
                self.scan(tmp, cache=cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["out"], 33)
        self.assertEqual(usage["cr"], 40)
        self.assertEqual(usage["cw"], 7)
        self.assertEqual(USAGE.token_total(usage), 230)
        self.assertEqual(usage["sessions"], {"session-1"})
        self.assertEqual(usage["models"], {})
        self.assertEqual(usage["cost"], 0)
        entry = cache["kimicode"][str(wire)]
        self.assertEqual(entry["proj"], project)
        self.assertEqual(entry["days"][now.date().isoformat()]["hours"][now.hour], 230)

    def test_missing_source_clears_stale_cache(self):
        stale = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "kimicode": {"/old/wire.jsonl": {"sig": "old", "days": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(tmp, cache=stale)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(cache["kimicode"], {})
        self.assertTrue(cache["_dirty"])

    def test_protocol_1_5_scans_all_agents_and_counts_shared_session_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            wires, now, project = self.create_modern_session(tmp)
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["out"], 33)
        self.assertEqual(usage["cr"], 40)
        self.assertEqual(usage["cw"], 7)
        self.assertEqual(USAGE.token_total(usage), 230)
        self.assertEqual(usage["sessions"], {"session-modern"})
        self.assertEqual(usage["models"]["moonshot/kimi-k3"]["in"], 150)
        self.assertEqual(usage["models"]["moonshot/kimi-k3"]["out"], 33)
        self.assertEqual(usage["models"]["moonshot/kimi-k3"]["cr"], 40)
        self.assertEqual(usage["models"]["moonshot/kimi-k3"]["cw"], 7)
        self.assertEqual(len(cache["kimicode"]), 2)
        for wire in wires:
            entry = cache["kimicode"][str(wire)]
            self.assertEqual(entry["sid"], "session-modern")
            self.assertEqual(entry["proj"], project)
            self.assertEqual(entry["parser_version"], USAGE._KIMI_PARSER_VERSION)
            self.assertEqual(entry["days"][now.date().isoformat()]["hours"][now.hour],
                             USAGE.token_total(entry["days"][now.date().isoformat()]))

    def _write_root_wire(self, session_dir, records):
        (session_dir / "wire.jsonl").write_text("\n".join(json.dumps(record) for record in [
            {"type": "metadata", "protocol_version": "1.5"}, *records
        ]) + "\n", encoding="utf-8")

    def _agent_records(self, wires):
        records = []
        for wire in wires:
            for line in wire.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("type") == "usage.record":
                    records.append(record)
        return records

    def test_root_wire_mirroring_agent_records_is_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            wires, _, _ = self.create_modern_session(tmp)
            session_dir = wires[0].parents[2]
            self._write_root_wire(session_dir, self._agent_records(wires))
            result, cache = self.scan(tmp)

        # 根 wire 进了缓存,但每条记录都被 agent wire 抵扣掉,总量不变。
        self.assertIn(str(session_dir / "wire.jsonl"), cache["kimicode"])
        self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 230)

    def test_root_wire_with_own_records_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            wires, _, _ = self.create_modern_session(tmp)
            session_dir = wires[0].parents[2]
            mirrored = self._agent_records(wires)
            unique = dict(mirrored[0], usage={"inputOther": 700, "output": 77})
            self._write_root_wire(session_dir, [*mirrored, unique])
            result, _ = self.scan(tmp)

        # 镜像那几条抵扣掉,根 wire 独有的 777 仍要计入。
        self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 230 + 777)

    def test_root_wire_rescanned_when_agent_wires_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            wires, _, _ = self.create_modern_session(tmp)
            session_dir = wires[0].parents[2]
            mirrored = self._agent_records(wires)
            self._write_root_wire(session_dir, mirrored)
            first, cache = self.scan(tmp)
            self.assertEqual(USAGE.token_total(first["ranges"]["all"]), 230)

            # agent wire 被清空后,根 wire 的镜像记录就是唯一来源,必须重算。
            wires[0].write_text(json.dumps(
                {"type": "metadata", "protocol_version": "1.5"}) + "\n", encoding="utf-8")
            second, _ = self.scan(tmp, cache=cache)

        self.assertEqual(USAGE.token_total(second["ranges"]["all"]), 230)

    def test_ledger_preserves_usage_sessions_and_projects_after_wire_cleanup(self):
        ledger = {"v": USAGE._LEDGER_VERSION, "tools": {}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "_load_ledger_from_disk", return_value=ledger):
            _, _, project = self.create_modern_session(tmp)
            first, cache = self.scan(tmp)
            first_usage = first["ranges"]["all"]

            stored = USAGE._load_ledger()["tools"]["kimicode"]
            self.assertEqual(len(stored), 1)
            stored_day = next(iter(stored.values()))
            self.assertEqual(stored_day["sessions"], ["session-modern"])
            self.assertEqual(stored_day["projects"], [project])

            shutil.rmtree(Path(tmp) / "sessions")
            second, cache = self.scan(tmp, cache=cache)

        second_usage = second["ranges"]["all"]
        self.assertEqual(USAGE.token_total(second_usage), USAGE.token_total(first_usage))
        self.assertEqual(second_usage["sessions"], {"session-modern"})
        self.assertEqual(cache["kimicode"], {})
        self.assertIn("kimicode", ledger["tools"])

    def test_parser_upgrade_rescans_unchanged_modern_wires(self):
        with tempfile.TemporaryDirectory() as tmp:
            wires, _, _ = self.create_modern_session(tmp)
            _, cache = self.scan(tmp)
            for entry in cache["kimicode"].values():
                entry.pop("parser_version")
            with mock.patch.object(USAGE, "_scan_kimi_wire", wraps=USAGE._scan_kimi_wire) as parser:
                self.scan(tmp, cache=cache)
        self.assertEqual(parser.call_count, len(wires))

    def test_tokei_override_precedes_current_and_legacy_homes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            wires, _, _ = self.create_modern_session(tmp)
            with mock.patch.dict(os.environ, {
                "TOKEI_KIMI_DIR": tmp,
                "KIMI_CODE_HOME": other,
                "KIMI_SHARE_DIR": other,
            }):
                self.assertEqual(USAGE._kimi_roots(), [os.path.abspath(tmp)])
                self.assertEqual(USAGE._kimi_wire_files(), sorted(str(wire) for wire in wires))

    def test_daily_and_wrapped_include_kimi_tokens_hours_and_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, now, _ = self.create_session(tmp)
            result, cache = self.scan(tmp)
            self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 230)

            cache_path = Path(tmp) / "scan-cache.json"
            cache_path.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "kimicode": cache["kimicode"],
            }), encoding="utf-8")
            old_cache = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(cache_path)
            try:
                daily = USAGE.build_daily_costs("30d", refresh=False)
                wrapped = USAGE.build_wrapped("30d", refresh=False)
            finally:
                USAGE._SCAN_CACHE_FILE = old_cache

        self.assertEqual(daily["daily"][0]["tokens"], 230)
        self.assertEqual(daily["daily"][0]["kimicode"], 0)
        self.assertEqual(wrapped["total_tokens"], 230)
        self.assertEqual(wrapped["hours"][now.hour], 230)
        self.assertEqual(wrapped["projects"][0]["name"], "kimi-project")
        self.assertEqual(wrapped["projects"][0]["tokens"], 230)


if __name__ == "__main__":
    unittest.main()
