"""Exact-version structural checks with real catalog and temporary stdlib store."""

import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))
from app.mcp.compact import Catalog, LibraryInventory, ProjectChecker, ProjectStore
from app.mcp.compact.projects import canonical
from app.mcp.compact.checks import CompilerPolicy, _policy_ast_dump_v1, legacy_file_behavior
from test_mcp_compact_projects import document


class CompilerPolicyCanonicalAstTests(unittest.TestCase):
    """Runs under either 3.12/3.13 without SDK, compiler, Node or network."""

    def test_original_source_fingerprints_are_preserved(self):
        cases = (
            ('espidf_compiler.py', '_write_arduino_user_files', '3af9f3fc8c905d28a83933bfb4bba6ebe95053bef8a22c986cc66bbfc4d913b3'),
            ('espidf_compiler.py', '_compile_in_dir', '39faa596be9d697da91d5bb066db672ea64dcc430f767d070f9b8189569ec3fd'),
            ('arduino_cli.py', 'compile', '58c4fd9f87d4aedfe6ef19e2a907075ae52bb5cea73ae3db6ff986025ff562e9'),
        )
        for filename, name, expected in cases:
            with self.subTest(function=name):
                tree = ast.parse((ROOT / 'backend/app/services' / filename).read_bytes())
                node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
                if name == '_compile_in_dir':
                    node = legacy_file_behavior(node)
                serialized = _policy_ast_dump_v1(node)
                self.assertEqual(hashlib.sha256(serialized.encode()).hexdigest(), expected)
        self.assertEqual(CompilerPolicy(ROOT).prefix, 'user_')

    def test_empty_fields_optional_none_and_semantic_none(self):
        self.assertEqual(_policy_ast_dump_v1(ast.parse('def f():\n    pass')),
                         "Module(body=[FunctionDef(name='f', args=arguments(), body=[Pass()])])")
        self.assertEqual(_policy_ast_dump_v1(ast.Constant(value=None)), 'Constant(value=None)')
        self.assertNotEqual(_policy_ast_dump_v1(ast.parse('x = None')),
                            _policy_ast_dump_v1(ast.parse('x = False')))
        with self.assertRaises(TypeError):
            _policy_ast_dump_v1('not an AST')

    def copy_policy(self, root):
        service = root / 'backend/app/services'
        service.mkdir(parents=True)
        actual = ROOT / 'backend/app/services'
        for name in ('espidf_compiler.py', 'arduino_cli.py'):
            shutil.copyfile(actual / name, service / name)
        shutil.copytree(actual / 'esp-idf-template', service / 'esp-idf-template')
        return service

    def test_semantic_file_write_and_mapping_mutations_remain_refused(self):
        mutations = (
            ("(main_dir / target).write_text(content, encoding='utf-8')",
             "(main_dir / target).write_text('changed content', encoding='utf-8')",
             'Compiler file-writing behavior changed'),
            ('return _USER_FILE_PREFIX + base', "return 'changed_' + base", 'User-file mapping changed'),
        )
        for before, after, error in mutations:
            with self.subTest(mutation=before), tempfile.TemporaryDirectory(prefix='policy-ast-mutation-') as temporary:
                root = Path(temporary)
                service = self.copy_policy(root)
                source = service / 'espidf_compiler.py'
                raw = source.read_text()
                self.assertIn(before, raw)
                source.write_text(raw.replace(before, after, 1))
                with self.assertRaisesRegex(ValueError, error):
                    CompilerPolicy(root)

    def test_missing_policy_sources_remain_refused(self):
        for missing in ('espidf_compiler.py', 'arduino_cli.py', 'esp-idf-template/main'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(prefix='policy-ast-missing-') as temporary:
                root = Path(temporary)
                source = self.copy_policy(root) / missing
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
                with self.assertRaises(FileNotFoundError):
                    CompilerPolicy(root)


class ProjectCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.from_repository(ROOT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compact-check-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "store")
        self.checker = ProjectChecker(self.store, self.catalog)

    def saved(self, doc=None):
        result = self.store.save_project(document=document() if doc is None else doc)
        self.assertTrue(result["ok"], result)
        return result

    def check(self, saved, checker=None):
        result = (checker or self.checker).check_project(project_id=saved["project_id"], version=saved["version"])
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(len(canonical(result)), 24 * 1024)
        return result

    def report(self, result):
        offset, raw = 0, bytearray()
        while True:
            page = self.store.read_artifact(artifact_id=result["diagnostic_artifact_id"], offset=offset, length=4096, encoding="base64")
            self.assertTrue(page["ok"], page)
            self.assertLessEqual(len(canonical(page)), 24 * 1024)
            raw.extend(base64.b64decode(page["data"]))
            if page["eof"]:
                break
            offset = page["next_offset"]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["diagnostic_artifact_sha256"])
        self.assertEqual(page["sha256"], result["diagnostic_artifact_sha256"])
        return json.loads(raw)

    def codes(self, result):
        return {issue["code"] for issue in self.report(result)["issues"]}

    def test_esp32_epaper_structurally_valid_and_explicit_partial(self):
        result = self.check(self.saved())
        report = self.report(result)
        self.assertEqual(result["structure_status"], "valid")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(report["counts"]["error"], 0)
        self.assertIn("electrical_validation", result["checks_unavailable"])
        self.assertIn("functional_simulation", result["checks_unavailable"])
        self.assertIn("dependency_availability_unknown", self.codes(result))
        self.assertTrue(report["compiler_policy_sources"])
        self.assertEqual(report["version"], result["version"])

    def test_invalid_esp32_and_epaper_pins(self):
        for side in ("start", "end"):
            doc = document()
            doc["wires"][0][side]["pinName"] = "made-up-pin"
            result = self.check(self.saved(doc))
            self.assertIn("pin_invalid", self.codes(result))
            self.assertEqual(result["structure_status"], "invalid")

    def test_undocumented_pins_are_unknown_not_invalid(self):
        doc = document()
        doc["components"][0]["metadataId"] = "led"
        doc["components"][0]["properties"] = {}
        doc["wires"][0]["end"]["pinName"] = "unverified-pin"
        result = self.check(self.saved(doc))
        self.assertIn("pins_unknown", self.codes(result))
        self.assertNotIn("pin_invalid", self.codes(result))
        self.assertEqual(result["status"], "partial")

    def test_native_defaults_do_not_become_false_attribute_errors(self):
        doc = document()
        doc['components'] = [self.catalog.get_reference(id='component:led', section='project')['data']['instance_template']]
        doc['wires'] = []
        result = self.check(self.saved(doc))
        self.assertEqual(result['structure_status'], 'valid')
        self.assertIn('attribute_default_type_unknown', self.codes(result))
        self.assertIn('attribute_type_consistency', result['checks_unavailable'])
        self.assertEqual(result['status'], 'partial')
        # Only the exact typed authored default is preserved as unknown.
        doc['components'][0]['properties']['brightness'] = False
        self.assertIn('attribute_type', self.codes(self.check(self.saved(doc))))

    def test_unknown_board_component_and_attributes(self):
        for field in ("board", "component"):
            doc = document()
            if field == "board":
                doc["boards"][0]["boardKind"] = "invented-board"
            else:
                doc["components"][0]["metadataId"] = "invented-component"
            result = self.check(self.saved(doc))
            self.assertIn(field + "_unknown", self.codes(result))
        doc = document()
        doc["components"][0]["properties"]["refreshMs"] = "bad type"
        self.assertIn("attribute_type", self.codes(self.check(self.saved(doc))))
        doc["components"][0]["properties"]["refreshMs"] = 50
        doc["components"][0]["properties"]["panelKind"] = "invented-panel"
        self.assertIn("panel_kind_unknown", self.codes(self.check(self.saved(doc))))

    def test_gpio_role_overlap_and_duplicate_connections(self):
        doc = document()
        second = copy.deepcopy(doc["wires"][0])
        second["id"] = "second"
        second["end"]["pinName"] = "SDI"
        doc["wires"].append(second)
        self.assertIn("gpio_role_conflict", self.codes(self.check(self.saved(doc))))
        doc = document()
        second = copy.deepcopy(doc["wires"][0])
        second.update(id="duplicate", start=doc["wires"][0]["end"], end=doc["wires"][0]["start"])
        doc["wires"].append(second)
        self.assertIn("connection_duplicate", self.codes(self.check(self.saved(doc))))

    def inventory(self, complete=True):
        inventory_root = self.root / "inventory"
        inventory_root.mkdir()
        proof = inventory_root / "library.properties"
        proof.write_text("name=GxEPD2\nversion=1.6.0\n")
        entry = {"path": proof.name, "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}
        return LibraryInventory(inventory_root, {"GxEPD2": entry}, complete=complete), proof

    def test_dependency_absent_versus_unknown_and_verified(self):
        doc = document()
        doc["boards"][0]["libraries"] = ["GxEPD2", "Adafruit GFX Library"]
        saved = self.saved(doc)
        self.assertNotIn("dependency_absent", self.codes(self.check(saved)))
        inventory, _ = self.inventory()
        checker = ProjectChecker(self.store, self.catalog, inventory=inventory)
        codes = self.codes(self.check(saved, checker))
        self.assertIn("dependency_absent", codes)
        self.assertIn("dependency_manifest_verified", codes)
        inventory.complete = False
        self.assertNotIn("dependency_absent", self.codes(self.check(saved, checker)))

    def test_inventory_modified_or_symlink_is_not_verified(self):
        inventory, proof = self.inventory()
        saved = self.saved()
        checker = ProjectChecker(self.store, self.catalog, inventory=inventory)
        original = proof.read_bytes()
        proof.write_text("changed")
        self.assertIn("inventory_unverified", self.codes(self.check(saved, checker)))
        proof.unlink()
        target = proof.with_name("target")
        target.write_bytes(original)
        proof.symlink_to(target)
        self.assertIn("inventory_unverified", self.codes(self.check(saved, checker)))

    def test_exact_old_version_after_update_and_never_latest(self):
        first = self.saved()
        doc = document()
        doc["wires"][0]["end"]["pinName"] = "INVALID"
        second = self.store.save_project(project_id=first["project_id"], expected_version=first["version"], document=doc)
        self.assertTrue(second["ok"])
        # An unreadable-as-JSON head proves check never loads latest.
        (Path(self.store.root) / "projects" / first["project_id"] / "head.json").write_text("head must not be read")
        self.assertNotIn("pin_invalid", self.codes(self.check(first)))
        self.assertIn("pin_invalid", self.codes(self.check(second)))
        for version in ("latest", None, "../escape", first["version"][:-1]):
            self.assertFalse(self.checker.check_project(project_id=first["project_id"], version=version)["ok"])
        self.assertFalse(self.checker.check_project(project_id=first["project_id"])["ok"])

    def test_report_bounded_complete_readable_and_repeat_immutable(self):
        doc = document()
        doc["components"][0]["properties"].update({"unknown_" + str(i): True for i in range(300)})
        saved = self.saved(doc)
        result = self.check(saved)
        self.assertTrue(result["issues_truncated"])
        self.assertEqual(len(result["issues"]), 20)
        report = self.report(result)
        self.assertEqual(len(report["issues"]), result["issue_count"])
        self.assertGreater(result["issue_count"], 300)
        repeated = self.check(saved)
        self.assertEqual(repeated["diagnostic_artifact_id"], result["diagnostic_artifact_id"])

    def test_escaped_paths_cannot_overflow_compact_response(self):
        doc = document()
        doc["components"][0]["properties"].update({"\x01" * 400 + str(i): 0 for i in range(20)})
        result = self.check(self.saved(doc))
        self.assertTrue(result["issues_truncated"])
        self.assertGreater(result["issue_count"], len(result["issues"]))
        self.assertEqual(len(self.report(result)["issues"]), result["issue_count"])

    def test_known_language_unsupported_vs_unknown_support_and_dependency_name(self):
        doc = document()
        doc["boards"][0]["boardKind"] = "arduino-uno"
        result = self.check(self.saved(doc))
        self.assertIn("language_unsupported", self.codes(result))
        doc["boards"][0]["boardKind"] = "raspberry-pi-3"
        doc["boards"][0]["libraries"] = ["undocumented-library-name"]
        result = self.check(self.saved(doc))
        self.assertIn("language_support_unknown", self.codes(result))
        self.assertIn("dependency_name_unknown", self.codes(result))
        self.assertNotIn("dependency_absent", self.codes(result))

    def test_report_directory_symlink_and_exact_snapshot_corruption(self):
        saved = self.saved()
        outside = self.root / "external"
        outside.mkdir()
        reports = Path(self.store.root) / "projects" / saved["project_id"] / "reports"
        reports.symlink_to(outside, target_is_directory=True)
        result = self.checker.check_project(project_id=saved["project_id"], version=saved["version"])
        self.assertFalse(result["ok"])
        self.assertFalse(list(outside.iterdir()))
        reports.unlink()
        snapshot = reports.parent / "versions" / (saved["version"] + ".vlx")
        snapshot.write_bytes(b"{}")
        result = self.checker.check_project(project_id=saved["project_id"], version=saved["version"])
        self.assertEqual(result["error"]["code"], "integrity_error")

    def test_report_quota_and_diagnostic_limit_do_not_drop_data(self):
        saved = self.saved()
        limited = ProjectStore(self.store.root, max_storage_bytes=1)
        result = ProjectChecker(limited, self.catalog).check_project(project_id=saved["project_id"], version=saved["version"])
        self.assertEqual(result["error"]["code"], "quota_exceeded")
        self.assertTrue(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])
        doc = document()
        doc["components"][0]["properties"].update({"attr_" + str(i): 0 for i in range(4100)})
        saved = self.saved(doc)
        result = self.checker.check_project(project_id=saved["project_id"], version=saved["version"])
        self.assertEqual(result["error"]["code"], "quota_exceeded")

    def test_report_and_snapshot_symlinks_hashes_and_isolation(self):
        saved = self.saved()
        result = self.check(saved)
        reports = Path(self.store.root) / "projects" / saved["project_id"] / "reports"
        report = reports / (result["diagnostic_artifact_sha256"] + ".json")
        original = report.read_bytes()
        report.write_bytes(b"{}")
        self.assertEqual(self.store.read_artifact(artifact_id=result["diagnostic_artifact_id"])["error"]["code"], "integrity_error")
        report.unlink()
        outside = self.root / "outside"
        outside.write_bytes(original)
        report.symlink_to(outside)
        self.assertFalse(self.store.read_artifact(artifact_id=result["diagnostic_artifact_id"])["ok"])
        self.assertFalse(self.checker.check_project(project_id=saved["project_id"], version=saved["version"])["ok"])
        self.assertEqual(outside.read_bytes(), original)

    def test_template_reserved_renames_and_primary_sketch(self):
        doc = document()
        doc["boards"][0]["languageMode"] = "arduino"
        doc["fileGroups"]["g/a~b"] = [{"name": name, "content": ""} for name in ("sketch.ino", "main.cpp", "user_main.cpp")]
        report = self.report(self.check(self.saved(doc)))
        self.assertIn("template_name_collision", {i["code"] for i in report["issues"]})
        self.assertTrue(any(i["code"] == "sketch_entry" and "sketch.ino" in i["message"] for i in report["issues"]))
        doc["fileGroups"]["g/a~b"] = [{"name": n, "content": ""} for n in ("a.ino", "b.ino")]
        self.assertIn("sketch_entry_ambiguous", self.codes(self.check(self.saved(doc))))
        doc["fileGroups"]["g/a~b"][0]["name"] = "sketch.ino"
        self.assertNotIn("sketch_entry_ambiguous", self.codes(self.check(self.saved(doc))))

    def test_rename_prefix_is_extracted_from_actual_policy_sources(self):
        policy_root = self.root / "policy"
        service = policy_root / "backend/app/services"
        service.mkdir(parents=True)
        actual = ROOT / "backend/app/services"
        (service / "espidf_compiler.py").write_text((actual / "espidf_compiler.py").read_text().replace("_USER_FILE_PREFIX = 'user_'", "_USER_FILE_PREFIX = 'alternate_'", 1))
        shutil.copyfile(actual / "arduino_cli.py", service / "arduino_cli.py")
        shutil.copytree(actual / "esp-idf-template", service / "esp-idf-template")
        doc = document()
        doc["boards"][0]["languageMode"] = "arduino"
        doc["fileGroups"]["g/a~b"] = [{"name": name, "content": ""} for name in ("sketch.ino", "main.cpp", "alternate_main.cpp")]
        result = self.check(self.saved(doc), ProjectChecker(self.store, self.catalog, source_root=policy_root))
        self.assertIn("template_name_collision", self.codes(result))
        self.assertNotIn("template_policy_unknown", self.codes(result))

    def test_pure_idf_control_files_and_source_policy_changes_fail_unknown(self):
        doc = document()
        doc["fileGroups"]["g/a~b"].append({"name": "CMakeLists.txt", "content": ""})
        saved = self.saved(doc)
        self.assertIn("template_control_collision", self.codes(self.check(saved)))
        policy_root = self.root / "sources"
        service = policy_root / "backend/app/services"
        service.mkdir(parents=True)
        original = ROOT / "backend/app/services/espidf_compiler.py"
        (service / original.name).write_text(original.read_text().replace("return _USER_FILE_PREFIX + base", "return 'changed_' + base", 1))
        result = self.check(saved, ProjectChecker(self.store, self.catalog, source_root=policy_root))
        self.assertIn("template_policy_unknown", self.codes(result))
        self.assertIn("compiler_file_layout", result["checks_unavailable"])

    def test_exported_at_changes_version_by_accepted_rule(self):
        first = self.saved()
        doc = document()
        doc["exportedAt"] = "2026-11-03T01:00:00Z"
        second = self.store.save_project(project_id=first["project_id"], expected_version=first["version"], document=doc)
        self.assertTrue(second["ok"])
        self.assertNotEqual(first["version"], second["version"])
        self.assertEqual(second["version"], hashlib.sha256(canonical(doc)).hexdigest())


if __name__ == "__main__":
    unittest.main()
