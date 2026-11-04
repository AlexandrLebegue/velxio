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
        for case in result['scenarios']:
            self.assertEqual(case['unexpected_errors'], 0)
            self.assertEqual(case['repeated_identical_calls'], 0)
            self.assertEqual(case['controlled_build_callbacks'], 1)
            self.assertEqual(case['build_status_polls'], 0)
            self.assertEqual(case['simulation'], 'unsupported')
            self.assertTrue(case['test_only'])
