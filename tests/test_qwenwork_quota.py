import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class QwenWorkQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old_home = USAGE.QWENWORK_HOME
        self.old_config = USAGE.QWENWORK_MCP_CONFIG
        self.old_status = USAGE.QWENWORK_STATUS
        self.old_cache = USAGE.QWENWORK_QUOTA_CACHE
        self.old_user = USAGE._USER_DIR
        self.old_env = {
            key: USAGE.os.environ.get(key)
            for key in ("TOKEI_QWENWORK_QUOTA", "TOKEI_QWENWORK_HOME")
        }
        for key in self.old_env:
            USAGE.os.environ.pop(key, None)

    def tearDown(self):
        USAGE.QWENWORK_HOME = self.old_home
        USAGE.QWENWORK_MCP_CONFIG = self.old_config
        USAGE.QWENWORK_STATUS = self.old_status
        USAGE.QWENWORK_QUOTA_CACHE = self.old_cache
        USAGE._USER_DIR = self.old_user
        for key, value in self.old_env.items():
            if value is None:
                USAGE.os.environ.pop(key, None)
            else:
                USAGE.os.environ[key] = value

    def configure(self, root, *, enabled=True, url="http://127.0.0.1:54365"):
        USAGE.QWENWORK_HOME = str(root / ".qwenworkcn")
        USAGE.QWENWORK_MCP_CONFIG = str(root / ".qwenworkcn" / "mcp-adaptor.config")
        USAGE.QWENWORK_STATUS = str(root / ".qwenworkcn" / ".status.json")
        USAGE.QWENWORK_QUOTA_CACHE = str(root / ".tokei" / "qwenwork_quota_cache.json")
        USAGE._USER_DIR = str(root / ".tokei")
        Path(USAGE.QWENWORK_HOME).mkdir(parents=True, exist_ok=True)
        Path(USAGE._USER_DIR).mkdir(parents=True, exist_ok=True)
        Path(USAGE._USER_DIR, "config.json").write_text(
            json.dumps({"qwenwork_quota_enabled": enabled}), encoding="utf-8")
        token = "a" * 64
        config_path = Path(USAGE.QWENWORK_MCP_CONFIG)
        config_path.write_text(json.dumps({"url": url, "token": token}), encoding="utf-8")
        config_path.chmod(0o600)
        status_path = Path(USAGE.QWENWORK_STATUS)
        status_path.write_text("{}", encoding="utf-8")
        status_path.chmod(0o600)
        return token

    @staticmethod
    def usage_payload(data):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "structuredContent": {
                    "ok": True,
                    "key": "qwenwork.usage",
                    "data": data,
                }
            },
        }

    @staticmethod
    def real_shape():
        return {
            "available": True,
            "aggregateRemainingPercent": None,
            "isQuotaExceeded": False,
            "expiresAt": None,
            "planExpiration": None,
            "segments": [{
                "id": "plan",
                "kind": "plan_credits",
                "total": 0,
                "used": 0,
                "remaining": 2100,
                "percentageUsed": 0,
                "unit": "credits",
                "renewsAt": None,
                "planExpiration": None,
            }],
            # These aliases mirror the segment and must not be added again.
            "planCredits": {
                "total": 0,
                "used": 0,
                "remaining": 2100,
                "percentage": 0,
                "unit": "credits",
            },
            "addOnCredits": None,
            "sharedResourcePackage": None,
            "sharedAddOnCredits": None,
            "isTeamPlan": False,
        }

    def test_disabled_by_default_never_calls_local_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root, enabled=False)
            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc") as rpc:
                self.assertEqual(USAGE.scan_qwenwork_quota(), {})
                rpc.assert_not_called()

    def test_environment_can_force_enable_or_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root, enabled=True)
            with mock.patch.dict(USAGE.os.environ, {"TOKEI_QWENWORK_QUOTA": "0"}):
                self.assertFalse(USAGE._qwenwork_quota_enabled())
            Path(USAGE._USER_DIR, "config.json").write_text(
                json.dumps({"qwenwork_quota_enabled": False}), encoding="utf-8")
            with mock.patch.dict(USAGE.os.environ, {"TOKEI_QWENWORK_QUOTA": "1"}):
                self.assertTrue(USAGE._qwenwork_quota_enabled())

    def test_config_requires_private_regular_file_and_strict_loopback_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = self.configure(root)
            config = USAGE._read_qwenwork_mcp_config()
            self.assertEqual(config["port"], 54365)
            self.assertEqual(config["token"], token)
            self.assertNotIn(token, config["marker"])

            path = Path(USAGE.QWENWORK_MCP_CONFIG)
            path.chmod(0o644)
            self.assertIsNone(USAGE._read_qwenwork_mcp_config())
            path.chmod(0o600)
            path.write_text(json.dumps({
                "url": "http://localhost:54365", "token": token,
            }), encoding="utf-8")
            path.chmod(0o600)
            self.assertIsNone(USAGE._read_qwenwork_mcp_config())

            path.unlink()
            target = root / "capability.json"
            target.write_text(json.dumps({
                "url": "http://127.0.0.1:54365", "token": token,
            }), encoding="utf-8")
            target.chmod(0o600)
            path.symlink_to(target)
            self.assertIsNone(USAGE._read_qwenwork_mcp_config())

    def test_normalizes_real_shape_without_double_counting_alias(self):
        quota = USAGE._normalize_qwenwork_usage(self.real_shape(), updated=1_786_650_000)
        self.assertTrue(quota["available"])
        self.assertEqual(quota["remaining"], 2100)
        self.assertIsNone(quota["remaining_pct"])
        self.assertEqual(len(quota["segments"]), 1)
        self.assertEqual(quota["segments"][0]["remaining"], 2100)
        self.assertIsNone(quota["segments"][0]["percentage_used"])
        self.assertFalse(quota["exceeded"])
        self.assertFalse(quota["stale"])

    def test_alias_fallback_and_shared_package_stay_separate(self):
        quota = USAGE._normalize_qwenwork_usage({
            "available": True,
            "aggregateRemainingPercent": "72.5",
            "planCredits": {
                "remaining": "100", "total": 500, "percentage": 80, "unit": "credits",
            },
            "addOnCredits": {
                "remaining": 40, "total": 100, "percentage": 60, "unit": "credits",
            },
            "sharedResourcePackage": {
                "cap": 10000, "used": 2500, "remaining": 7500,
                "percentage": 25, "unit": "requests",
            },
            "isTeamPlan": True,
        })
        self.assertEqual(quota["remaining"], 140)
        self.assertEqual(quota["remaining_pct"], 72.5)
        self.assertEqual(quota["shared"]["remaining"], 7500)
        self.assertEqual(quota["shared"]["unit"], "requests")
        self.assertTrue(quota["is_team"])

    def test_shared_add_on_alias_is_not_added_to_personal_balance(self):
        quota = USAGE._normalize_qwenwork_usage({
            "available": True,
            "planCredits": {"remaining": 100, "total": 500, "unit": "credits"},
            "sharedAddOnCredits": {
                "remaining": 700, "total": 1000, "percentage": 30, "unit": "credits",
            },
        })
        self.assertEqual(quota["remaining"], 100)
        self.assertEqual(len(quota["segments"]), 1)
        self.assertEqual(quota["shared"]["remaining"], 700)

    def test_invalid_numbers_are_dropped_and_percentages_clamped(self):
        quota = USAGE._normalize_qwenwork_usage({
            "available": True,
            "aggregateRemainingPercent": 140,
            "segments": [{
                "id": "plan", "kind": "plan_credits", "unit": "credits",
                "remaining": float("nan"), "total": -3, "percentageUsed": -20,
            }],
        })
        self.assertEqual(quota["remaining_pct"], 100)
        self.assertIsNone(quota["remaining"])
        self.assertEqual(quota["segments"][0]["total"], 0)
        self.assertIsNone(quota["segments"][0]["percentage_used"])

    def test_non_credit_segments_are_not_added_to_personal_balance(self):
        quota = USAGE._normalize_qwenwork_usage({
            "available": True,
            "segments": [
                {"id": "plan", "kind": "plan_credits", "remaining": 100,
                 "unit": "credits"},
                {"id": "requests", "kind": "plan_credits", "remaining": 7500,
                 "unit": "requests"},
            ],
        })
        self.assertEqual(quota["remaining"], 100)
        self.assertEqual(len(quota["segments"]), 2)

    def test_extracts_structured_and_text_mcp_envelopes(self):
        data = self.real_shape()
        self.assertEqual(
            USAGE._qwenwork_mcp_data(self.usage_payload(data))["segments"][0]["remaining"],
            2100,
        )
        text_payload = {
            "result": {"content": [{
                "type": "text",
                "text": json.dumps({"ok": True, "key": "qwenwork.usage", "data": data}),
            }]}
        }
        self.assertEqual(
            USAGE._qwenwork_mcp_data(text_payload)["planCredits"]["remaining"], 2100)
        wrong_key = self.usage_payload(data)
        wrong_key["result"]["structuredContent"]["key"] = "qwenwork.account"
        self.assertIsNone(USAGE._qwenwork_mcp_data(wrong_key))

    def test_rpc_posts_only_fixed_read_resource_and_parses_sse(self):
        token = "b" * 64
        payload = self.usage_payload(self.real_shape())
        body = ("event: message\ndata: " + json.dumps(payload) + "\n\n").encode("utf-8")

        class FakeResponse:
            status = 200

            def read(self, _limit):
                return body

            def getheader(self, _name):
                return "text/event-stream"

        class FakeConnection:
            def __init__(self, host, port, timeout):
                self.host, self.port, self.timeout = host, port, timeout
                self.request_args = None

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)

            def getresponse(self):
                return FakeResponse()

            def close(self):
                pass

        connection = FakeConnection("", 0, 0)
        with mock.patch("http.client.HTTPConnection", return_value=connection):
            result = USAGE._qwenwork_mcp_rpc({"port": 54365, "token": token})

        self.assertEqual(result["result"]["structuredContent"]["key"], "qwenwork.usage")
        args, kwargs = connection.request_args
        self.assertEqual(args[0:2], ("POST", "/"))
        request_json = json.loads(kwargs["body"])
        self.assertEqual(request_json["method"], "tools/call")
        self.assertEqual(request_json["params"], {
            "name": "qw_query", "arguments": {"key": "qwenwork.usage"},
        })
        self.assertEqual(kwargs["headers"]["x-api-key"], token)

    def test_scan_writes_private_token_free_cache_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = self.configure(root)
            payload = self.usage_payload(self.real_shape())
            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc", return_value=payload) as rpc:
                quota = USAGE.scan_qwenwork_quota()
                self.assertEqual(quota["remaining"], 2100)
                self.assertEqual(rpc.call_count, 1)

            cache_path = Path(USAGE.QWENWORK_QUOTA_CACHE)
            cache_text = cache_path.read_text(encoding="utf-8")
            self.assertNotIn(token, cache_text)
            self.assertEqual(stat.S_IMODE(cache_path.stat().st_mode), 0o600)

            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc") as rpc:
                cached = USAGE.scan_qwenwork_quota()
                rpc.assert_not_called()
            self.assertEqual(cached["remaining"], 2100)
            self.assertEqual(cached["source"], "mcp")
            self.assertFalse(cached["stale"])

    def test_failed_refresh_uses_matching_short_fallback_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            payload = self.usage_payload(self.real_shape())
            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc", return_value=payload):
                USAGE.scan_qwenwork_quota()

            cache_path = Path(USAGE.QWENWORK_QUOTA_CACHE)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["fetched_at"] = USAGE.datetime.now().timestamp() - 400
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            cache_path.chmod(0o600)

            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc", return_value=None) as rpc:
                fallback = USAGE.scan_qwenwork_quota()
            self.assertEqual(rpc.call_count, 2)
            self.assertEqual(fallback["remaining"], 2100)
            self.assertEqual(fallback["source"], "cache")
            self.assertTrue(fallback["stale"])

    def test_status_generation_change_invalidates_fresh_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            with mock.patch.object(
                    USAGE, "_qwenwork_mcp_rpc",
                    return_value=self.usage_payload(self.real_shape())):
                USAGE.scan_qwenwork_quota()

            Path(USAGE.QWENWORK_STATUS).write_text('{"generation":2}', encoding="utf-8")
            Path(USAGE.QWENWORK_STATUS).chmod(0o600)
            changed = self.real_shape()
            changed["segments"][0]["remaining"] = 500
            changed["planCredits"]["remaining"] = 500
            with mock.patch.object(
                    USAGE, "_qwenwork_mcp_rpc",
                    return_value=self.usage_payload(changed)) as rpc:
                quota = USAGE.scan_qwenwork_quota()
            self.assertEqual(rpc.call_count, 1)
            self.assertEqual(quota["remaining"], 500)

    def test_unavailable_account_clears_previous_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            with mock.patch.object(
                    USAGE, "_qwenwork_mcp_rpc",
                    return_value=self.usage_payload(self.real_shape())):
                USAGE.scan_qwenwork_quota()

            cache_path = Path(USAGE.QWENWORK_QUOTA_CACHE)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["fetched_at"] = USAGE.datetime.now().timestamp() - 400
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            cache_path.chmod(0o600)
            unavailable = self.usage_payload({"available": False})
            with mock.patch.object(USAGE, "_qwenwork_mcp_rpc", return_value=unavailable) as rpc:
                self.assertEqual(USAGE.scan_qwenwork_quota(), {})
            self.assertEqual(rpc.call_count, 1)
            self.assertFalse(cache_path.exists())


if __name__ == "__main__":
    unittest.main()
