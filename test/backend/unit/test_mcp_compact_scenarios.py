"""Deterministic authoring/build contracts; never contacts a model or compiler."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('compact_scenarios', ROOT / 'scripts/mcp-compact-scenarios.py')
scenarios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)


class DeterministicScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_scenarios_match_checked_in_counts_without_errors_or_loops(self):
        result = await scenarios.evaluate()
        expected = json.loads((ROOT / 'docs/mcp-compact-scenarios.json').read_text())
        self.assertEqual(result, expected)
        self.assertFalse(result['real_llm_used'] or result['real_compiler_used'])
        self.assertEqual([case['tool_calls'] for case in result['baseline']], [8, 7, 8])
        self.assertEqual([case['tool_calls'] for case in result['paged_manual']], [15, 12, 13])
        for case in result['paged_manual']:
            self.assertGreater(case['reference_pages_followed'], 0)
            self.assertLessEqual(case['max_catalog_response_bytes'], 24 * 1024)
            self.assertEqual(case['unexpected_errors'], 0)
            self.assertEqual(case['repeated_identical_calls'], 0)
        for case in result['error_recovery']:
            self.assertEqual(case['tool_calls'], 6)
            self.assertEqual(case['expected_errors'], 1)
            self.assertEqual(case['unexpected_errors'], 0)
            self.assertEqual(case['repeated_identical_calls'], 0)
        for case in result['scenarios']:
            self.assertEqual(case['tool_calls'], 5)
            self.assertEqual(case['calls_by_tool'].get('get_reference', 0), 0)
            self.assertEqual(case['unexpected_errors'], 0)
            self.assertEqual(case['repeated_identical_calls'], 0)
            self.assertEqual(case['controlled_build_callbacks'], 1)
            self.assertEqual(case['build_status_polls'], 0)
            self.assertEqual(case['simulation'], 'unsupported')
            self.assertTrue(case['test_only'])
