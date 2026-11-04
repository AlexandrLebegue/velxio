"""Frozen measurement inputs; no model calls, compiler or product changes."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('chat_generalization_driver', ROOT/'scripts/chat-bench-qwen.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class GeneralizationInputs(unittest.TestCase):
    def test_requirements_are_user_prompts_and_the_seed_does_not_implement_the_task(self):
        from app.mcp.compact import Catalog
        from app.agent.workspace import checked_document
        catalog = Catalog.from_snapshot(ROOT/'backend/app/mcp/compact/catalog.snapshot.json')
        suite = json.loads((ROOT/'scripts/chat-generalization-cases.json').read_text())
        self.assertEqual(len(suite['cases']), 6)
        for key, case in suite['cases'].items():
            with self.subTest(case=key):
                self.assertNotIn('\n', case['prompt'])
                for tool in ('save_project','from_example','get_reference','build_project'):
                    self.assertNotIn(tool, case['prompt'])
                doc = checked_document(driver.suite_document(case, catalog))
                self.assertEqual(doc['components'], [])
                self.assertEqual(doc['wires'], [])
                if 'initial' in case:
                    self.assertEqual(case['expected']['board'], doc['boards'][0]['boardKind'])
                    source = '\n'.join(f['content'] for files in doc['fileGroups'].values() for f in files)
                    self.assertIn('void loop() {}', source)
                    self.assertNotIn('digitalWrite', source)
                    self.assertNotIn('millis()', source)

    def test_all_required_native_components_have_real_packaged_pins(self):
        from app.mcp.compact import Catalog
        catalog = Catalog.from_snapshot(ROOT/'backend/app/mcp/compact/catalog.snapshot.json')
        suite = json.loads((ROOT/'scripts/chat-generalization-cases.json').read_text())
        for key, case in suite['cases'].items():
            for component in case['expected']['component_counts']:
                with self.subTest(case=key, component=component):
                    entry = catalog.get_reference(id='component:'+component, section='pins')
                    self.assertTrue(entry['ok'], entry)
                    self.assertIsInstance(entry['data'], list, entry)
                    self.assertGreater(len(entry['data']), 0)


if __name__ == '__main__':
    unittest.main()
