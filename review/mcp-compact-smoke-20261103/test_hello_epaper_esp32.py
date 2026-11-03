"""Offline structural fixture only; never compiles, installs or claims display output.

Run: python3 -m unittest discover -s review/mcp-compact-smoke-20261103 \
    -p 'test_hello_epaper_esp32.py' -v
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
INPUTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'test/backend/unit'))
from app.mcp.compact import Catalog, ProjectChecker, ProjectStore
from app.mcp.compact.projects import canonical
# Reuse the existing native format fixture and complete bounded artifact readers.
import test_mcp_compact_projects as project_fixtures
import test_mcp_compact_checks as check_fixtures


class HelloEpaperESP32Tests(unittest.TestCase):
    def test_native_save_check_and_review_env_offline(self):
        with patch('socket.socket', side_effect=AssertionError('Network forbidden in review fixture')), \
                tempfile.TemporaryDirectory(prefix='compact-hello-epaper-') as temporary:
            document = json.loads((INPUTS / 'hello-epaper-esp32.vlx').read_bytes())
            native = project_fixtures.document()
            self.assertEqual(document['format'], native['format'])
            self.assertEqual(document['version'], native['version'])
            catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
            self.store = ProjectStore(Path(temporary) / 'store')
            saved = self.store.save_project(document=document)
            self.assertTrue(saved['ok'], saved)
            self.assertIsNone(saved['download_url'])
            self.assertEqual(saved['version'], hashlib.sha256(canonical(document)).hexdigest())
            restored = project_fixtures.ProjectStoreTests.read_all(self, saved['project_artifact_id'])
            self.assertEqual(json.loads(restored), document)

            checker = ProjectChecker(self.store, catalog, source_root=ROOT)
            checked = checker.check_project(project_id=saved['project_id'], version=saved['version'])
            self.assertTrue(checked['ok'], checked)
            self.assertEqual(checked['structure_status'], 'valid', checked)
            self.assertEqual(checked['status'], 'partial')
            report = check_fixtures.ProjectCheckTests.report(self, checked)
            self.assertEqual(report['counts']['error'], 0, report['issues'])
            self.assertTrue(report['compiler_policy_sources'])
            self.assertIn('electrical_validation', checked['checks_unavailable'])
            self.assertIn('functional_simulation', checked['checks_unavailable'])
            # No fabricated local library availability in this unit test.
            self.assertIn('installed_dependencies', checked['checks_unavailable'])
            self.assertNotIn('dependency_name_unknown', {i['code'] for i in report['issues']})

            board = document['boards'][0]
            panel = document['components'][0]
            self.assertIn('board:' + board['boardKind'], catalog._entries)
            self.assertIn('component:' + panel['metadataId'], catalog._entries)
            self.assertEqual(panel['properties']['panelKind'], 'epaper-2in9-bw')
            self.assertEqual(board['libraries'], ['GxEPD2', 'Adafruit GFX Library', 'Adafruit BusIO'])
            self.assertEqual(len(document['wires']), 8)
            sketch = document['fileGroups'][board['activeFileGroupId']][0]
            self.assertEqual(sketch['name'], 'sketch.ino')
            self.assertIn('display.print("Hello World")', sketch['content'])
            self.assertIn('GxEPD2_290_T94', sketch['content'])

            env = dict(line.split('=', 1) for line in (INPUTS / 'review.env').read_text().splitlines()
                       if line and not line.startswith('#'))
            self.assertEqual(env['MCP_REVIEW_ISOLATED'], '1')
            self.assertEqual(env['REVIEW_ROOT'], '/tmp/smoke-20261103-a')
            self.assertEqual(env['IDF_ROOT'], '/opt/esp-idf-v5')
            self.assertEqual(env['PROJECT_BOARD_ID'], board['id'])
            self.assertEqual(env['PROJECT_VLX'], '/review-input/hello-epaper-esp32.vlx')
            for name in ('GXEPD2_ROOT', 'GFX_ROOT', 'BUSIO_ROOT'):
                self.assertTrue(env[name].startswith('/review-libs/'))


if __name__ == '__main__':
    unittest.main()
