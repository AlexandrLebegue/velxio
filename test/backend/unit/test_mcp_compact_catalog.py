"""Local contract/catalog tests: no backend, browser, compiler or network."""

import copy
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.mcp.compact import BuildService, Catalog, ProjectChecker, ProjectStore, TOOL_SCHEMAS
from app.mcp.compact.catalog import encoded
from app.mcp.compact.contracts import MAX_RESPONSE_BYTES


class CompactCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.from_repository(ROOT)

    def test_reproducible_generation_and_input_provenance(self):
        other = Catalog.from_repository(ROOT)
        self.assertEqual(self.catalog._snapshot, other._snapshot)
        for item in self.catalog._snapshot["inputs"]:
            self.assertEqual(item["sha256"], hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest())
        for entry in self.catalog._entries.values():
            for source in entry["sources"]:
                self.assertGreater(source["line"], 0)
                self.assertEqual(source["sha256"], hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest())

    def test_full_catalog_including_registry_and_aggregated_examples(self):
        counts = {kind: sum(e["kind"] == kind for e in self.catalog._entries.values())
                  for kind in ("component", "board", "example")}
        self.assertEqual(counts, {"component": 166, "board": 30, "example": 328})
        self.assertIn("component:custom-chip", self.catalog._entries)
        self.assertIn("component:raspberry-pi-5", self.catalog._entries)
        self.assertIn("example:robot-desktop-eyes", self.catalog._entries)
        self.assertEqual(len([e for e in self.catalog._entries.values() if e.get("panel")]), 8)

    def test_default_five_and_pagination_no_loss_or_duplicates(self):
        page = self.catalog.search_catalog()
        self.assertEqual(len(page["items"]), 5)
        self.assertEqual(page["total"], len(self.catalog._entries))
        ids = [x["id"] for x in page["items"]]
        while page["has_more"]:
            page = self.catalog.search_catalog(offset=len(ids))
            self.assertEqual(page["total"], len(self.catalog._entries))
            ids.extend(x["id"] for x in page["items"])
        self.assertEqual(ids, sorted(self.catalog._entries))
        self.assertNotIn("next_cursor", page)

    def test_compound_query_merges_all_terms_without_duplicates_and_paginates_stably(self):
        query = 'e-ink epaper 1.54'
        combined = self.catalog.search_catalog(query=query, kind='component', limit=50)
        expected = set()
        for term in query.split():
            expected.update(item['id'] for item in self.catalog.search_catalog(query=term, kind='component', limit=50)['items'])
        ids, offset = [], 0
        while True:
            page = self.catalog.search_catalog(query=query, kind='component', limit=1, offset=offset)
            self.assertTrue(page['ok'])
            self.assertEqual(page['total'], len(expected))
            self.assertEqual(page['query_used'], combined['query_used'])
            ids.extend(item['id'] for item in page['items'])
            if page['next_offset'] is None:
                self.assertFalse(page['has_more'])
                break
            self.assertGreater(page['next_offset'], offset)
            offset = page['next_offset']
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('component:epaper-1in54-bw', ids)
        empty_page = self.catalog.search_catalog(query='servo', kind='component', offset=100)
        self.assertEqual(empty_page['query_used'], ['servo'])
        self.assertEqual(empty_page['items'], [])
        self.assertIsNone(empty_page['next_offset'])

    def test_offset_boundaries_maximum_limit_and_filtered_totals(self):
        first = self.catalog.search_catalog(kind="example", limit=50)
        self.assertEqual(len(first["items"]), 50)
        self.assertEqual(first["total"], 328)
        last = self.catalog.search_catalog(kind="example", offset=325, limit=50)
        self.assertEqual(len(last["items"]), 3)
        self.assertFalse(last["has_more"])
        for offset in (328, 329, 1_000_000):
            page = self.catalog.search_catalog(kind="example", offset=offset)
            self.assertEqual(page["items"], [])
            self.assertEqual(page["total"], 328)
            self.assertFalse(page["has_more"])
        empty = self.catalog.search_catalog(query="nonexistentcatalogentry")
        self.assertEqual((empty["total"], empty["has_more"], empty["items"]), (0, False, []))

    def test_offset_normalizes_query_and_allows_page_size_change(self):
        first = self.catalog.search_catalog(query="  ESP32 ", kind="example", limit=1)
        rest = self.catalog.search_catalog(query="esp32", kind="example", limit=3, offset=1)
        together = self.catalog.search_catalog(query="esp32", kind="example", limit=4)
        self.assertEqual(first["items"] + rest["items"], together["items"])
        self.assertEqual(first["total"], rest["total"])

    def test_multibyte_search_stays_bounded_and_large_page_refuses_cleanly(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        query = "🧪" * 256
        for entry in snapshot["entries"]:
            entry["summary"] = query
        catalog = Catalog(snapshot)
        for offset in (0, 5):
            page = catalog.search_catalog(query=query, offset=offset)
            self.assertTrue(page["ok"])
            self.assertLessEqual(len(encoded(page)), MAX_RESPONSE_BYTES)
        self.assertEqual(catalog.search_catalog(query=query, limit=50)["error"]["code"], "quota_exceeded")

    def test_legacy_cursor_ignored_without_changing_offset_or_query(self):
        expected = self.catalog.search_catalog(query="esp32", kind="example", limit=3, offset=5)
        for cursor in (None, "!", "stale-from-another-revision", "x" * 10000, 17, True, [], {}):
            with self.subTest(cursor=type(cursor).__name__):
                result = self.catalog.search_catalog(query="esp32", kind="example", limit=3, offset=5, cursor=cursor)
                self.assertEqual(result, expected)
                self.assertFalse(set(result) & {"cursor", "next_cursor"})
        self.assertEqual(self.catalog.search_catalog(cursor="stale"), self.catalog.search_catalog())
        self.assertFalse(self.catalog.search_catalog(cursor="stale", other=1)["ok"])

    def test_invalid_search_arguments(self):
        for args in ({"limit": True}, {"limit": 0}, {"limit": 51}, {"limit": 1.5},
                     {"query": None}, {"query": "x" * 257}, {"query": "\ud800"}, {"kind": "alligator"},
                     {"offset": None}, {"offset": True}, {"offset": -1}, {"offset": 1.5},
                     {"offset": "5"}, {"offset": 1_000_001}, {"ref": "led"}):
            with self.subTest(args=args):
                self.assertFalse(self.catalog.search_catalog(**args)["ok"])

    def test_invalid_reference_arguments(self):
        for args in ({}, {"id": None}, {"id": ""}, {"id": "x" * 241},
                     {"id": "component:led", "section": "raw"}, {"id": "component:led", "other": 1}):
            self.assertEqual(self.catalog.get_reference(**args)["error"]["code"], "invalid_argument")
        self.assertEqual(self.catalog.get_reference(id="absent")["error"]["code"], "not_found")

    def test_aliases_and_ambiguity(self):
        self.assertEqual(self.catalog.get_reference(id="wokwi-led")["id"], "component:led")
        self.assertEqual(self.catalog.get_reference(id="velxio-led")["id"], "component:led")
        self.assertEqual(self.catalog.get_reference(id="board-velxio-esp32")["id"], "board:esp32")
        self.assertEqual(self.catalog.get_reference(id="arduino-uno")["error"]["code"], "ambiguous_id")

    def test_real_esp32_pins_and_epaper_attrs_protocol(self):
        pins = self.catalog.get_reference(id="board:esp32", section="pins")["data"]
        self.assertTrue({"16", "17", "GND2", "VN", "VP"} <= {p["name"] for p in pins})
        component = self.catalog.get_reference(id="component:esp32-devkit-v1", section="pins")["data"]
        self.assertEqual(component, pins)
        epaper = self.catalog.get_reference(id="component:epaper-1in54-bw")["data"]
        self.assertEqual({p["name"] for p in epaper["pins"]}, {"GND", "VCC", "SCK", "SDI", "CS", "DC", "RST", "BUSY"})
        self.assertEqual(epaper["protocol"]["name"], "SPI")
        self.assertEqual(next(a for a in epaper["attrs"] if a["name"] == "panelKind")["defaultValue"], "epaper-1in54-bw")
        self.assertEqual(epaper["init"], "unknown")

    def test_unknown_pins_protocol_and_honest_limitations(self):
        item = self.catalog.get_reference(id="component:led")["data"]
        self.assertEqual(item["pins"], "unknown")
        self.assertEqual(item["protocol"], "unknown")
        self.assertTrue(any("pinCount" in line for line in item["limitations"]))
        self.assertTrue(any("overlay" in line for line in item["limitations"]))

    def test_real_search_keywords(self):
        self.assertIn("component:dht22", [x["id"] for x in self.catalog.search_catalog(query="humidity", kind="component", limit=20)["items"]])

    def test_example_files_dependencies_and_explicit_code_only(self):
        key = "example:epaper-1in54-uno-hello"
        default = self.catalog.get_reference(id=key)
        self.assertNotIn("void setup()", json.dumps(default))
        self.assertIn("GxEPD2", default["data"]["dependencies"])
        self.assertGreater(default["data"]["files"][0]["size_bytes"], 100)
        code = self.catalog.get_reference(id=key, section="code")
        self.assertIn("void setup()", code["data"]["files"][0]["content"])
        deps = self.catalog.get_reference(id=key, section="libraries")["data"]
        self.assertTrue(any(s["line"] == 16 for group in deps for s in group["sources"]))
        for section in ("files", "project"):
            self.assertNotIn("void setup()", json.dumps(self.catalog.get_reference(id=key, section=section)))

    def test_default_all_references_bounded_and_without_embedded_sources(self):
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & {"content", "code", "sourceC", "contentB64", "vfsFiles"})
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        for key in self.catalog._entries:
            response = self.catalog.get_reference(id=key)
            self.assertTrue(response["ok"], key)
            self.assertLessEqual(len(encoded(response)), MAX_RESPONSE_BYTES)
            inspect(response)

    def test_quotas_count_utf8_bytes_and_refuse_without_truncating(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        entry = next(e for e in snapshot["entries"] if e["id"] == "example:epaper-1in54-uno-hello")
        entry["project"]["code"] = "é" * (MAX_RESPONSE_BYTES // 2)
        catalog = Catalog(snapshot)
        result = catalog.get_reference(id=entry["id"], section="code")
        self.assertEqual(result["error"]["code"], "quota_exceeded")
        self.assertTrue(catalog.get_reference(id=entry["id"])["ok"])
        self.assertLessEqual(len(encoded(result)), MAX_RESPONSE_BYTES)

    def test_all_six_input_schema_roots_are_client_compatible_objects(self):
        self.assertEqual(len(TOOL_SCHEMAS), 6)
        for name, tool in TOOL_SCHEMAS.items():
            with self.subTest(tool=name):
                schema = tool['inputSchema']
                self.assertEqual(schema['type'], 'object')
                self.assertIsInstance(schema['properties'], dict)
                self.assertFalse(schema['additionalProperties'])
                self.assertFalse(set(schema) & {'oneOf', 'anyOf', 'allOf'})

    def test_search_schema_has_no_cursors_and_documents_offset_limits(self):
        for tool in TOOL_SCHEMAS.values():
            self.assertNotIn('cursor', tool['inputSchema']['properties'])
        spec = TOOL_SCHEMAS['search_catalog']
        props = spec['inputSchema']['properties']
        self.assertEqual(props['limit'], {'type':'integer','minimum':1,'maximum':50,'default':5})
        self.assertEqual(props['offset'], {'type':'integer','minimum':0,'maximum':1_000_000,'default':0})
        success = spec['outputSchema']['oneOf'][0]
        self.assertFalse(set(success['properties']) & {'cursor','next_cursor'})
        self.assertTrue({'total','has_more'} <= set(success['required']))

    def test_flat_build_schema_preserves_action_and_field_constraints(self):
        schema = TOOL_SCHEMAS['build_project']['inputSchema']
        self.assertEqual(schema['required'], ['action'])
        self.assertEqual(schema['properties']['action'], {'type':'string', 'enum':['start','status']})
        self.assertEqual(set(schema['properties']), {'action','project_id','version','board_id','build_id'})
        for name in ('project_id','board_id','build_id'):
            self.assertEqual(schema['properties'][name], {'type':'string','minLength':1,'maxLength':200})
        self.assertEqual(schema['properties']['version'], {'type':'string','pattern':'^[0-9a-f]{64}$'})

    def test_no_fake_handlers_and_exactly_six_schemas(self):
        self.assertEqual(set(TOOL_SCHEMAS), {"search_catalog", "get_reference", "save_project", "check_project", "build_project", "read_artifact"})
        for name, spec in TOOL_SCHEMAS.items():
            self.assertEqual(hasattr(self.catalog, name) or hasattr(ProjectStore, name) or hasattr(ProjectChecker, name) or hasattr(BuildService, name), spec["implemented"])

    def test_raw_input_original_bytes_are_preserved(self):
        for raw in self.catalog._snapshot["raw_inputs"]:
            original = (ROOT / raw["path"]).read_bytes()
            self.assertEqual(base64.b64decode(raw["content_b64"]), original)
            self.assertEqual(hashlib.sha256(original).hexdigest(), raw["sha256"])
            self.assertTrue(any("UTF-8" in line for line in self.catalog._snapshot["limitations"]))

    def test_multifile_example_and_vfs_code_sections_do_not_leak(self):
        reference = self.catalog.get_reference(id="example:robot-desktop-eyes")
        self.assertGreaterEqual(len(reference["data"]["files"]), 30)
        self.assertIn("U8g2", reference["data"]["dependencies"])
        project = {"code": "print('main')", "vfsFiles": {"helper.py": "print('helper')"},
                   "components": [], "wires": []}
        files = self.catalog._files(project)
        self.assertTrue(any(f["name"] == "helper.py" for f in files))
        self.assertNotIn("print(", json.dumps(self.catalog._without_code(project)))

    def test_all_json_schemas_validate_inputs_and_actual_outputs(self):
        version = "a" * 64
        doc = {"format": "velxio-project", "version": 1, "boards": [], "fileGroups": {}, "components": [], "wires": [], "activeBoardId": None}
        cases = [
            ("search_catalog", {}, True), ("search_catalog", {"limit": True}, False),
            ("search_catalog", {"limit": 50, "offset": 1_000_000}, True),
            ("search_catalog", {"offset": True}, False), ("search_catalog", {"offset": -1}, False),
            ("search_catalog", {"offset": 1_000_001}, False), ("search_catalog", {"other": 1}, False),
            ("get_reference", {"id": "component:led"}, True), ("get_reference", {"ref": "led"}, False),
            ("save_project", {"document": doc}, True),
            ("save_project", {"document": doc, "project_id": "p", "expected_version": version}, True),
            ("save_project", {"project_id": "p", "expected_version": version, "changes": [{"op": "set", "path": "/name", "value": "new"}]}, True),
            ("save_project", {"changes": [{"op": "remove", "path": "/boards/0"}]}, False),
            ("save_project", {"document": doc, "project_id": "p"}, False),
            ("save_project", {"document": doc, "expected_version": version}, False),
            ("save_project", {"project_id": "p", "expected_version": version}, False),
            ("save_project", {"project_id": "p", "expected_version": version, "changes": [{"op": "remove", "path": "/name"}]}, True),
            ("save_project", {"document": doc, "project_id": "p", "expected_version": version,
                              "changes": [{"op": "remove", "path": "/name"}]}, False),
            ("save_project", {"document": doc, "project_id": "p", "expected_version": version, "changes": []}, False),
            ("build_project", {"action": "start", "project_id": "p", "version": version, "board_id": "b"}, True),
            ("build_project", {"action": "status", "build_id": "b"}, True),
            ("build_project", {"action": "cancel", "build_id": "b"}, False),
            ("check_project", {"project_id": "p", "version": version}, True),
            ("read_artifact", {"artifact_id": "a", "length": 12289}, False),
        ]
        outputs = [("search_catalog", self.catalog.search_catalog()), ("get_reference", self.catalog.get_reference(id="component:led")),
                   ("get_reference", self.catalog.get_reference(id="missing"))]
        script = """const fs=require('fs'),Ajv=require('ajv');
const {schemas,cases,outputs}=JSON.parse(fs.readFileSync(0,'utf8'));const ajv=new Ajv({strict:false});
for(const s of Object.values(schemas)){ajv.compile(s.inputSchema);ajv.compile(s.outputSchema);}
for(const [n,v,want] of cases){const check=ajv.compile(schemas[n].inputSchema);if(check(v)!==want)throw Error(n+JSON.stringify(check.errors));}
for(const [n,v] of outputs){const check=ajv.compile(schemas[n].outputSchema);if(!check(v))throw Error(n+JSON.stringify(check.errors));}
"""
        subprocess.run(["node", "-e", script], input=json.dumps({"schemas": TOOL_SCHEMAS, "cases": cases, "outputs": outputs}).encode(), check=True, timeout=10)

    def test_source_change_changes_revision_and_unsupported_dependency_fails(self):
        with tempfile.TemporaryDirectory(prefix="compact-catalog-test-") as temp:
            root = Path(temp)
            for source in self.catalog._snapshot["inputs"]:
                dst = root / source["path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / source["path"], dst)
            metadata = root / "frontend/public/components-metadata.json"
            metadata.write_text(metadata.read_text() + "\n")
            self.assertNotEqual(Catalog.from_repository(root).revision, self.catalog.revision)
            data = root / "frontend/src/data/examples.ts"
            data.write_text(data.read_text().replace("...legacyExamples,", "...window.examples,", 1))
            with self.assertRaisesRegex(ValueError, "unsupported/unresolved data dependency window"):
                Catalog.from_repository(root)
            data.write_text(data.read_text().replace("...window.examples,", "...legacyExamples.map(e => ({...e, unsupported: () => 1})),", 1))
            with self.assertRaisesRegex(ValueError, "Non-JSON data"):
                Catalog.from_repository(root)


if __name__ == "__main__":
    unittest.main()
