import unittest

from test_codex_limits import USAGE


class CostRecalculationTests(unittest.TestCase):
    def test_gemini_thoughts_are_priced_as_output(self):
        name = "Gemini 3.5 Flash"
        model = {
            "name": name,
            "in": 100,
            "out": 20,
            "cached": 30,
            "thoughts": 40,
            "cost": 0.0,
        }
        result = {"gemini": {"ranges": {"today": {"models": [model], "cost": 0.0}}}}

        USAGE._recalc_costs(result)

        price = USAGE._raw_price(USAGE._pricing_id(name))
        expected = (
            100 * price["in"]
            + 30 * price["cache_read"]
            + 60 * price["out"]
        ) / 1_000_000
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(model["cost"], expected, places=6)
        self.assertAlmostEqual(result["gemini"]["ranges"]["today"]["cost"], expected, places=6)

    def test_authoritative_tool_costs_are_preserved(self):
        for tool in ("claude", "pi", "hermes", "opencode", "openclaw"):
            model = {
                "name": "GPT-5.5",
                "in": 100,
                "out": 20,
                "cr": 30,
                "cw": 4,
                "cost": 42.0,
            }
            result = {tool: {"ranges": {"today": {"models": [model], "cost": 42.0}}}}

            USAGE._recalc_costs(result)

            self.assertEqual(model["cost"], 42.0, tool)
            self.assertEqual(result[tool]["ranges"]["today"]["cost"], 42.0, tool)

    def test_hermes_missing_cost_uses_pricing_fallback(self):
        name = "Deepseek V4 Flash"
        model = {
            "name": name,
            "in": 100,
            "out": 20,
            "cr": 30,
            "cw": 4,
            "reason": 5,
            "cost": 0.0,
        }
        result = {"hermes": {"ranges": {"today": {"models": [model], "cost": 0.0}}}}

        USAGE._recalc_costs(result)

        price = USAGE._raw_price(USAGE._pricing_id(name))
        expected = (
            100 * price["in"]
            + 25 * price["out"]
            + 30 * price["cache_read"]
            + 4 * price["cache_write"]
        ) / 1_000_000
        self.assertAlmostEqual(model["cost"], expected, places=6)
        self.assertAlmostEqual(result["hermes"]["ranges"]["today"]["cost"], expected, places=6)

    def test_grok_cached_and_reasoning_tokens_use_their_respective_prices(self):
        model = {
            "name": "Grok 4.5",
            "in": 1_000_000,
            "out": 150_000,
            "cr": 1_000_000,
            "reason": 50_000,
            "cost": 0.0,
        }
        result = {"grok": {"ranges": {"today": {"models": [model], "cost": 0.0}}}}

        USAGE._recalc_costs(result)

        self.assertAlmostEqual(model["cost"], 3.5, places=6)
        self.assertAlmostEqual(result["grok"]["ranges"]["today"]["cost"], 3.5, places=6)

    def test_grok_preserves_request_level_tiered_cost(self):
        model = {
            "name": "Grok 4.6",
            "in": 150_000,
            "out": 10_000,
            "cr": 50_000,
            "reason": 0,
            "cost": 0.77,
        }
        result = {"grok": {"ranges": {"today": {"models": [model], "cost": 0.77}}}}

        USAGE._recalc_costs(result)

        self.assertEqual(model["cost"], 0.77)
        self.assertEqual(result["grok"]["ranges"]["today"]["cost"], 0.77)

    def test_deepseek_harness_preserves_timestamp_aware_cost(self):
        model = {
            "name": "Deepseek V4 Pro",
            "in": 1_000_000,
            "out": 1_000_000,
            "cr": 1_000_000,
            "cw": 0,
            "reason": 0,
            "cost": 5.324,
        }
        result = {
            "deepseek_harness": {
                "ranges": {"today": {"models": [model], "cost": 5.324}},
            },
        }

        USAGE._recalc_costs(result)

        self.assertEqual(model["cost"], 5.324)
        self.assertEqual(result["deepseek_harness"]["ranges"]["today"]["cost"], 5.324)


if __name__ == "__main__":
    unittest.main()
