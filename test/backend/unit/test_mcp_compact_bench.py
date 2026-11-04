"""Measurement integrity tests; never invoke a model or a compiler."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'compact_bench', Path(__file__).resolve().parents[3] / 'scripts/mcp-bench-qwen.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class BenchIntegrityTests(unittest.TestCase):
    def test_remote_audit_selects_declared_project_and_latest_version(self):
        first, probe = 'p_' + 'a' * 32, 'p_' + 'b' * 32
        calls = [{'name': 'save_project', 'output': {'ok': True, 'project_id': project, 'version': version}}
                 for project, version in ((first, 'old'), (first, 'final'), (probe, 'probe'))]
        events = [{'type': 'text', 'part': {'text': 'Saved ' + first}}]
        self.assertEqual(bench.final_saved(calls, events)['version'], 'final')
        self.assertEqual(bench.final_saved(calls, [])['project_id'], probe)
        self.assertIsNone(bench.final_saved([], events))

    def test_session_proof_refuses_coaching_or_the_wrong_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'P2-B1'
            run.mkdir()
            (run / 'run.json').write_text(json.dumps({'run': run.name, 'case': 'B1', 'status': 'finished'}))
            (run / 'opencode.jsonl').write_text(json.dumps({'type': 'text', 'sessionID': 'session'}) + '\n')
            user = {'info': {'role': 'user'}, 'parts': [{'type': 'text', 'text': bench.PROMPTS['B1']}]}
            assistant = {'info': {'role': 'assistant', 'providerID': 'hyperqwen', 'modelID': 'qwen3.8-27b'}}
            doc = {'messages': [user, assistant]}

            def export(argv, **kwargs):
                self.assertEqual(argv, ['opencode', 'export', 'session', '--pure'])
                json.dump(doc, kwargs['stdout'])

            with patch.object(bench.subprocess, 'run', side_effect=export):
                self.assertTrue(bench.verify_sessions(root)[0]['verified'])
                doc['messages'].append(user)
                self.assertFalse(bench.verify_sessions(root)[0]['verified'])
                doc['messages'].pop()
                assistant['info']['modelID'] = 'another-model'
                self.assertFalse(bench.verify_sessions(root)[0]['verified'])


if __name__ == '__main__':
    unittest.main()
