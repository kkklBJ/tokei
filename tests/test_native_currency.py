import unittest
import hashlib
from datetime import datetime, timezone
from unittest import mock
from test_codex_limits import USAGE
from test_deepseek_harness import harness_event


class NativeCurrencyTests(unittest.TestCase):
    def test_mixed_official_and_channel_survive_ledger_ranges_and_dashboard(self):
        ts = int(datetime(2026, 9, 11, 4, tzinfo=timezone.utc).timestamp() * 1000)
        event = harness_event('assistant/message', ts, 1, 1,
                              {'inputTokens': 1_000_000, 'outputTokens': 1_000_000,
                               'cacheReadTokens': 1_000_000}, model='deepseek-v4-flash')
        official = USAGE._deepseek_harness_usage_record(event)
        self.assertEqual(official['cost'], 0)
        self.assertAlmostEqual(official['cost_cny'], 5.02)
        event['data']['message']['source']['provider'] = 'openrouter'
        event['data']['step'] = 2
        with mock.patch.object(USAGE, '_raw_price', return_value={
            'in': 0.1, 'out': 0.2, 'cache_read': 0.01, 'cache_write': 0}):
            channel = USAGE._deepseek_harness_usage_record(event)
        self.assertAlmostEqual(channel['cost'], 0.31)
        self.assertEqual(channel['cost_cny'], 0)
        sources = {}
        for record in (official, channel):
            USAGE._ledger_add_record_source(sources, 'session', record['date'], record)
        day = sources['session'][official['date']]
        bucket = USAGE._empty_token_bucket()
        USAGE._merge_token_day(bucket, day)
        self.assertAlmostEqual(bucket['cost'], 0.31)
        self.assertAlmostEqual(bucket['cost_cny'], 5.02)
        models = USAGE._format_token_models(bucket['models'])
        self.assertEqual(len(models), 1)
        self.assertAlmostEqual(models[0]['cost_cny'], 5.02)
        result = {'deepseek_harness': {'ranges': {'today': {'models': models, 'cost': .31, 'cost_cny': 5.02}}}}
        USAGE._recalc_costs(result)
        self.assertAlmostEqual(models[0]['cost'], .31)
        self.assertAlmostEqual(models[0]['cost_cny'], 5.02)
        cache = {'deepseek_harness': {'a': {'sid': 'session', 'records': [official, channel]}}}
        ledger = {'tools': {'deepseek_harness': {official['date']: day}}}
        with mock.patch.object(USAGE, '_load_ledger', return_value=ledger):
            dashboard = USAGE.build_daily_costs(refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped(refresh=False, _cache=cache)
        self.assertAlmostEqual(sum(d['cost_cny'] for d in dashboard['daily']), 5.02)
        self.assertAlmostEqual(sum(m.get('cost_cny', 0) for m in dashboard['models']), 5.02)
        self.assertAlmostEqual(wrapped['cost_cny'], 5.02)
        self.assertAlmostEqual(wrapped['total_cost'], .31)

    def test_opencode_requires_explicit_official_provider(self):
        message = {'role': 'assistant', 'modelID': 'deepseek-flash',
                   'time': {'created': int(datetime(2026, 9, 11, 6, tzinfo=timezone.utc).timestamp()*1000)},
                   'tokens': {'input': 1_000_000, 'output': 1_000_000}, 'cost': .75}
        for provider, usd, cny in [('deepseek', 0, 10), ('openrouter', .75, 0), ('', .75, 0)]:
            with self.subTest(provider=provider):
                message['providerID'] = provider
                day = USAGE._opencode_message_day(message)
                self.assertEqual(day['cost'], usd)
                self.assertEqual(day['cost_cny'], cny)
                merged = USAGE._empty_token_day()
                USAGE._merge_live_token_day(merged, day)
                self.assertEqual(merged['cost_cny'], cny)
                self.assertEqual(merged['models']['deepseek-flash']['cost_cny'], cny)

    def test_new_currency_revision_replaces_old_usd_source(self):
        old = {'in': 1_000_000, 'cost': .15, '_cost_version': 4}
        new = {'in': 1_000_000, 'cost': 0, 'cost_cny': 1, '_cost_version': 5}
        ledger = {'v': USAGE._LEDGER_VERSION, 'tools': {'deepseek_harness': {
            '2026-09-11': dict(old, _sources={hashlib.sha256(b's').hexdigest(): old})}}}
        saved = USAGE._LEDGER_CACHE.copy()
        try:
            USAGE._LEDGER_CACHE.update(data=ledger, dirty=False)
            result = USAGE.ledger_reconcile('deepseek_harness', {'2026-09-11': new},
                                            {'s': {'2026-09-11': new}})
            self.assertEqual(result['2026-09-11']['cost'], 0)
            self.assertEqual(result['2026-09-11']['cost_cny'], 1)
        finally:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(saved)
