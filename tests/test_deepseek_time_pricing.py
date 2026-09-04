import unittest
from datetime import datetime, timezone

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class DeepSeekTimePricingTests(unittest.TestCase):
    @staticmethod
    def at_utc(day, hour, minute=0):
        return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)

    def test_flash_peak_boundaries_are_evaluated_in_beijing_time(self):
        # 01:00 UTC = 09:00 Beijing, and 10:00 UTC = 18:00 Beijing.
        off_peak_before_morning = USAGE._raw_price(
            "deepseek-v4-flash", at=self.at_utc(19, 0, 59), provider="deepseek"
        )
        peak_morning = USAGE._raw_price(
            "deepseek-v4-flash", at=self.at_utc(19, 1), provider="deepseek"
        )
        off_peak_midday = USAGE._raw_price(
            "deepseek-v4-flash", at=self.at_utc(19, 4), provider="deepseek"
        )
        peak_afternoon = USAGE._raw_price(
            "deepseek-v4-flash", at=self.at_utc(19, 6), provider="deepseek"
        )
        off_peak_evening = USAGE._raw_price(
            "deepseek-v4-flash", at=self.at_utc(19, 10), provider="deepseek"
        )

        self.assertEqual(off_peak_before_morning["in"], 0.22)
        self.assertEqual(peak_morning["in"], 0.44)
        self.assertEqual(off_peak_midday["in"], 0.22)
        self.assertEqual(peak_afternoon["in"], 0.44)
        self.assertEqual(off_peak_evening["in"], 0.22)

    def test_pro_uses_the_same_schedule_with_its_own_prices(self):
        price = USAGE._raw_price(
            "DeepSeek-V4-Pro-0813",
            at=self.at_utc(19, 1),
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
        )

        self.assertEqual(price["in"], 1.32)
        self.assertEqual(price["out"], 3.96)
        self.assertEqual(price["cache_read"], 0.044)

    def test_price_change_is_effective_at_midnight_and_keeps_previous_history(self):
        before_cutover = USAGE._raw_price(
            "deepseek-v4-flash",
            at=self.at_utc(16, 15, 59),
            provider="deepseek",
        )
        at_cutover = USAGE._raw_price(
            "deepseek-v4-flash",
            at=self.at_utc(16, 16),
            provider="deepseek",
        )
        peak_after_cutover = USAGE._raw_price(
            "deepseek-v4-flash",
            at=self.at_utc(17, 1),
            provider="deepseek",
        )

        self.assertEqual(before_cutover["in"], 0.14)
        self.assertEqual(before_cutover["out"], 0.28)
        self.assertEqual(before_cutover["cache_read"], 0.0028)
        self.assertEqual(at_cutover["in"], 0.22)
        self.assertEqual(at_cutover["out"], 0.66)
        self.assertEqual(at_cutover["cache_read"], 0.007)
        self.assertEqual(peak_after_cutover["in"], 0.44)

    def test_openrouter_and_missing_timestamp_keep_static_pricing(self):
        static = USAGE._DEEPSEEK_PREVIOUS_PRICES["deepseek/deepseek-v4-flash"]
        no_timestamp = USAGE._raw_price(
            "deepseek-v4-flash", at=None, provider="deepseek"
        )
        openrouter = USAGE._raw_price(
            "deepseek/deepseek-v4-flash",
            at=self.at_utc(19, 1),
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
        )

        self.assertEqual(no_timestamp, static)
        self.assertEqual(openrouter, USAGE._raw_price("deepseek/deepseek-v4-flash"))

    def test_claude_event_cost_uses_event_timestamp(self):
        line = (
            '{"type":"assistant","timestamp":"2026-08-19T01:00:00Z",'
            '"message":{"model":"deepseek-v4-flash","usage":'
            '{"input_tokens":1000000,"output_tokens":1000000}}}'
        )

        event = USAGE._claude_usage(line, want_dt=True)

        self.assertIsNotNone(event)
        self.assertAlmostEqual(event["cost"], 1.76)

    def test_recalculation_does_not_replace_mixed_time_cost(self):
        model = {
            "name": "deepseek/deepseek-v4-flash",
            "in": 2_000_000,
            "out": 2_000_000,
            "cr": 0,
            "cw": 0,
            "reason": 0,
            "cost": 3.52,
        }
        result = {"zcode": {"ranges": {"today": {"models": [model], "cost": 3.52}}}}

        USAGE._recalc_costs(result)

        self.assertEqual(model["cost"], 3.52)
        self.assertEqual(result["zcode"]["ranges"]["today"]["cost"], 3.52)


if __name__ == "__main__":
    unittest.main()
