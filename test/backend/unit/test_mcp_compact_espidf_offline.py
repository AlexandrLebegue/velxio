"""Controlled SDK/cache doubles; NEVER invokes a real compiler or subprocess."""
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.espidf_offline import OfflinePlan, approved_template, digest, tree_manifest, validate_sources, verify_sdk
from app.mcp.compact.checks import CompilerPolicy
SOURCE = ROOT / 'backend/app/services/espidf_compiler.py'
TREE = ast.parse(SOURCE.read_text())

def template():
    # Evaluate only the actual checked-in template path expression.
    node = next(n for n in TREE.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_TEMPLATE_DIR' for t in n.targets))
    return eval(compile(ast.Expression(node.value), str(SOURCE), 'eval'), {'Path': Path, '__file__': str(SOURCE)})


class OfflinePolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_template_pin_and_legacy_projection(self):
        self.assertTrue(approved_template(template()))
        self.assertEqual(CompilerPolicy(ROOT).prefix, 'user_')

    def test_sources_scripts_paths_and_computed_includes_rejected(self):
        for name, content in [('CMakeLists.txt', ''), ('x.py', ''), ('../a.c', ''), ('a.c', '#include "../secret"'), ('a.c', '#include HEADER'), ('a.c', '#include_next <x>')]:
            with self.subTest(name=name, content=content), self.assertRaises(ValueError):
                validate_sources([{'name': name, 'content': content}])
        validate_sources([{'name': 'src/main.c', 'content': '#include <stdio.h>\nvoid app_main(){}'}])

    def test_actual_capability_requires_template_bytes_not_os_namespace(self):
        method = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == 'offline_capabilities')
        namespace = {'_TEMPLATE_DIR': template()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        result = namespace['offline_capabilities'](object())
        self.assertTrue(result['ready'])
        self.assertFalse(result['os_network_isolation'])
        with tempfile.TemporaryDirectory() as tmp:
            namespace['_TEMPLATE_DIR'] = Path(tmp)
            self.assertFalse(namespace['offline_capabilities'](object())['ready'])

    def test_sdk_member_hash_and_parent_links_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sdk = root / 'sdk'; (sdk / 'tools/cmake').mkdir(parents=True)
            members = []
            for name in ['tools/idf.py', 'tools/cmake/project.cmake']:
                p = sdk / name; p.write_text('CONTROLLED SDK PROOF')
                members.append({'path': 'sdk/' + name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            proof = {'inventory_root': tmp, 'members': members}
            verify_sdk(proof, sdk)
            (root / 'link').symlink_to(sdk, target_is_directory=True)
            linked = {'inventory_root': tmp, 'members': [dict(m, path=m['path'].replace('sdk/', 'link/')) for m in members]}
            with self.assertRaises(OSError): verify_sdk(linked, root / 'link')
            (sdk / 'tools/idf.py').write_text('changed')
            with self.assertRaises(ValueError): verify_sdk(proof, sdk)

    def test_env_local_not_global(self):
        before = dict(os.environ)
        result = OfflinePlan.environment({'CCACHE_REMOTE_STORAGE': 'forbidden', 'KEEP': 'yes'})
        self.assertEqual(result['IDF_COMPONENT_MANAGER'], '0')
        self.assertEqual(result['FETCHCONTENT_FULLY_DISCONNECTED'], 'ON')
        self.assertNotIn('CCACHE_REMOTE_STORAGE', result)
        self.assertEqual(dict(os.environ), before)

    def test_cached_component_missing_and_hooks_fail(self):
        with self.assertRaises(ValueError):
            OfflinePlan(template(), {}, {}, {'vendor/missing': '*'}, [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'cache'; root.mkdir()
            (root / 'CMakeLists.txt').write_text('execute_process(COMMAND curl example.invalid)')
            proof = {'source_root': str(root), 'tree_sha256': digest(tree_manifest(root))}
            with self.assertRaises(ValueError):
                OfflinePlan._copy_tree(proof, Path(tmp) / 'staged', True)
            (root / 'CMakeLists.txt').write_text('idf_component_register(SRCS "main.c")')
            (root / 'main.c').write_text('void local(){}')
            proof['tree_sha256'] = digest(tree_manifest(root))
            OfflinePlan._copy_tree(proof, Path(tmp) / 'good', True)
            self.assertEqual(tree_manifest(root), tree_manifest(Path(tmp) / 'good'))

    def test_library_recipes_never_staged_and_hash_links_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'cache'; root.mkdir()
            (root / 'CMakeLists.txt').write_text('execute_process(COMMAND false)')
            (root / 'a.h').write_text('// controlled')
            proof = {'source_root': str(root), 'tree_sha256': digest(tree_manifest(root))}
            OfflinePlan._copy_tree(proof, Path(tmp) / 'staged', False)
            self.assertFalse((Path(tmp) / 'staged/CMakeLists.txt').exists())
            (root / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(OSError): tree_manifest(root)

    async def test_actual_entry_reuses_inner_and_never_sync_warmup_install(self):
        method = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'compile_offline')
        namespace = dict(Path=Path, hashlib=hashlib, json=json, tempfile=tempfile, shutil=shutil,
                         _TEMPLATE_DIR=template(), _variant_lock=lambda _: asyncio.Lock(), _variant_lock_key=lambda *a: str(a))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        forbidden = AsyncMock(side_effect=AssertionError('INSTALL/DOWNLOAD/NORMAL COMPILE FORBIDDEN'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            members = []
            for name in ['tools/idf.py', 'tools/cmake/project.cmake']:
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('CONTROLLED NOT REAL SDK')
                members.append({'path': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            evidence = {'inventory_root': tmp, 'idf_root': tmp, 'members': members}
            calls = []
            async def inner(project, files, target, *args, **kwargs):
                calls.append((target, args, kwargs))
                self.assertTrue((project / 'CMakeLists.txt').exists())
                self.assertIsInstance(kwargs['_offline_plan'], OfflinePlan)
                return {'success': True, 'stdout': 'EXPLICIT INNER DOUBLE, NOT REAL BUILD'}
            service = SimpleNamespace(available=True, idf_path=tmp, _idf_target=lambda _: 'esp32',
                _arduino_supports_target=lambda _: False, _use_idf5=lambda *a: False, _idf_root=lambda _: tmp,
                _detect_managed_components=lambda _: {}, _normalize_options=lambda *a: {'flashSize': '4MB'},
                _compile_in_dir=inner, compile=forbidden, _sync_managed_components=forbidden,
                _warm_replica_in_background=forbidden, _prepare_persistent_project_dir=forbidden, ensure_core_for_board=forbidden,
                _locate_mkspiffs=lambda: None)
            files = [{'name': 'main.c', 'content': 'void app_main(){}'}]
            kwargs = dict(offline_evidence=evidence, library_proofs={}, allowed_libraries=set(), pure_idf=True)
            result = await namespace['compile_offline'](service, files, 'esp32:esp32:esp32', **kwargs)
            self.assertTrue(result['success']); self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], 'esp32')
            result = await namespace['compile_offline'](service, files, 'esp32:esp32:esp32', spiffs_files=[{'name': 'x'}], **kwargs)
            self.assertEqual(result['error_kind'], 'dependency_unavailable')
            (root / 'tools/idf.py').write_text('changed')
            result = await namespace['compile_offline'](service, files, 'esp32:esp32:esp32', **kwargs)
            self.assertEqual(result['error_kind'], 'dependency_unavailable')
            self.assertEqual(len(calls), 1); forbidden.assert_not_awaited()

    def test_inner_acquisition_calls_are_offline_guarded(self):
        method = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_compile_in_dir')
        parents = {}
        for node in ast.walk(method):
            for child in ast.iter_child_nodes(node): parents[child] = node
        names = {'_sync_managed_components', '_heal_corrupt_managed_components', '_override_esp_hosted_with_race_fix', '_ninja_failure_wants_configure'}
        found = set()
        for node in ast.walk(method):
            if not isinstance(node, ast.Call): continue
            name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
            if name not in names: continue
            found.add(name); ancestor = node
            while ancestor in parents:
                ancestor = parents[ancestor]
                if isinstance(ancestor, ast.If) and '_offline_plan is None' in ast.unparse(ancestor.test): break
            else: self.fail('Unguarded acquisition/retry: ' + name)
        self.assertEqual(found, names)
