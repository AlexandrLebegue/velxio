"""Lossless bounded catalog continuations, including UTF-8 and raw source bytes."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from jsonschema import validate
from app.mcp.compact import Catalog, TOOL_SCHEMAS
from app.mcp.compact.catalog import encoded
from app.mcp.compact.contracts import MAX_RESPONSE_BYTES

ROOT = Path(__file__).resolve().parents[3]


class CatalogPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')

    def pages(self, catalog, name, **arguments):
        seen = set()
        while True:
            validate(arguments, TOOL_SCHEMAS[name]['inputSchema'])
            result = getattr(catalog, name)(**arguments)
            self.assertTrue(result['ok'], result)
            validate(result, TOOL_SCHEMAS[name]['outputSchema'])
            self.assertLessEqual(len(encoded(result)), MAX_RESPONSE_BYTES)
            self.assertEqual(result['max_response_bytes'], MAX_RESPONSE_BYTES)
            self.assertEqual(result['has_more'], result['next_offset'] is not None)
            yield result
            if not result['has_more']:
                break
            self.assertTrue(result['truncated'])
            self.assertGreater(result['next_offset'], arguments.get('offset', 0))
            self.assertNotIn(result['next_offset'], seen)
            seen.add(result['next_offset'])
            self.assertEqual(result['next_request']['tool'], name)
            arguments = result['next_request']['arguments']

    def test_search_byte_budget_shrinks_page_without_losing_or_reordering_items(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        for item in snapshot['entries']:
            item['name'] = '🧪' * 500
            item['summary'] = '🧪' * 300
        catalog = Catalog(snapshot)
        ids = []
        for page in self.pages(catalog, 'search_catalog', limit=50):
            self.assertLess(len(page['items']), 50)
            self.assertEqual(page['next_section'], 'project')
            ids.extend(item['id'] for item in page['items'])
        self.assertEqual(ids, sorted(catalog._entries))
        self.assertEqual(len(ids), len(set(ids)))

    def test_pin_pages_have_stable_totals_default_limits_and_reproducible_continuations(self):
        pages = list(self.pages(self.catalog, 'get_reference', id='board:esp32', section='pins', limit=3))
        values = [value for page in pages for value in page['data']]
        self.assertEqual(values, self.catalog._entries['board:esp32']['pins'])
        self.assertTrue(all(page['total'] == len(values) for page in pages))
        self.assertEqual(pages[-1]['next_section'], 'libraries')
        self.assertFalse(pages[0]['data_complete'])
        default = self.catalog.get_reference(id='board:esp32', section='pins')
        self.assertEqual(default['limit'], 20)
        self.assertEqual(len(default['data']), 20)
        first = self.catalog.get_reference(id='board:esp32', section='project')
        self.assertTrue(first['data_complete'])
        self.assertEqual(first['data']['format'], 'velxio-project')
        self.assertFalse(first['truncated'])
        for args in ({'offset': -1}, {'offset': True}, {'offset': 1000001}, {'limit': False}, {'limit': 51}):
            self.assertFalse(self.catalog.get_reference(id='board:esp32', **args)['ok'])
        empty = self.catalog.get_reference(id='board:esp32', section='pins', offset=1000000)
        self.assertEqual(empty['data'], [])
        self.assertIsNone(empty['next_offset'])

    def test_long_code_and_raw_inputs_roundtrip_exact_bytes_and_offsets(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        entry = next(item for item in snapshot['entries'] if item['id'] == 'example:epaper-1in54-uno-hello')
        source = '// 🧪 é "quotes" \\ literal\r\n' * 1400 + 'void setup(){}\nvoid loop(){}\n'
        entry['project']['code'] = source
        original = b'\xff\xfeRAW' * 1200
        snapshot['raw_inputs'] = [{'path': 'fixture.c', 'decoded_sha256': hashlib.sha256(source.encode()).hexdigest(),
                                   'content_b64': base64.b64encode(original).decode(), 'sha256': hashlib.sha256(original).hexdigest()}]
        catalog = Catalog(snapshot)
        source_parts, raw_parts = [], []
        pages = list(self.pages(catalog, 'get_reference', id=entry['id'], section='code', limit=4))
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertFalse(page['data_complete'])
            source_parts.extend(page['data']['files'])
            raw_parts.extend(page['data']['raw_inputs'])
        actual = b''
        for part in source_parts:
            self.assertEqual(part['content_offset'], len(actual))
            actual += part['content'].encode()
            self.assertEqual(part['sha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(actual, source.encode())
        self.assertEqual(source_parts[-1]['content_next_offset'], None)
        self.assertEqual(base64.b64decode(''.join(part['content_b64'] for part in raw_parts)), original)
        self.assertIsNone(pages[-1]['next_section'])
        self.assertIsNone(pages[-1]['next_request'])

    def test_large_nested_fields_are_explicit_fragments_never_half_native_documents(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        entry = next(item for item in snapshot['entries'] if item['id'] == 'component:epaper-1in54-bw')
        source = '🧪\n"\\\t' * 8000
        entry['defaults']['large'] = source
        catalog = Catalog(snapshot)
        parts = []
        for page in self.pages(catalog, 'get_reference', id=entry['id'], section='project', limit=3):
            self.assertFalse(page['data_complete'])
            self.assertTrue(page['truncated'])
            if 'fragments' in page:
                self.assertIsNone(page['data'])
                parts.extend(item for item in page['fragments'] if item['path'] == '/instance_template/properties/large')
            self.assertIn('instance_template', page['metadata_omitted'])
        self.assertEqual(''.join(part['value'] for part in parts), source)

    def test_fragment_format_stays_consistent_through_small_tail_values(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        entry = next(item for item in snapshot['entries'] if item['id'] == 'component:epaper-1in54-bw')
        entry['limitations'] = ['🧪' * 8000, 'tail']
        catalog = Catalog(snapshot)
        fragments = []
        for page in self.pages(catalog, 'get_reference', id=entry['id'], section='limitations', limit=1):
            self.assertIsNone(page['data'])
            self.assertFalse(page['data_complete'])
            fragments.extend(page['fragments'])
        self.assertEqual(''.join(f['value'] for f in fragments if f['path'] == '/0'), entry['limitations'][0])
        self.assertTrue(any(f['path'] == '/1' and f['value'] == 'tail' for f in fragments))

    def test_next_section_hints_terminate_instead_of_forming_navigation_loops(self):
        sections = TOOL_SCHEMAS['get_reference']['inputSchema']['properties']['section']['enum']
        for key in ('board:esp32', 'component:epaper-1in54-bw', 'example:blink-led'):
            for start in sections:
                section, visited = start, set()
                while section is not None:
                    self.assertNotIn(section, visited)
                    visited.add(section)
                    section = self.catalog.get_reference(id=key, section=section)['next_section']
                self.assertLessEqual(len(visited), len(sections))

    def test_invalid_catalog_requests_also_have_bounded_uniform_errors(self):
        for name, arguments in [('search_catalog', {'X' * 30000: True}),
                                ('get_reference', {'id': 'component:led', 'X' * 30000: True})]:
            result = getattr(self.catalog, name)(**arguments)
            self.assertFalse(result['ok'])
            validate(result, TOOL_SCHEMAS[name]['outputSchema'])
            self.assertLessEqual(len(encoded(result)), MAX_RESPONSE_BYTES)
            self.assertTrue(result['error']['path_truncated'])
            self.assertLessEqual(len(result['error']['path']), 512)

    def test_every_actual_section_first_page_is_bounded_with_explicit_navigation(self):
        # Cover every section on representative catalog entries, including the
        # largest multifile example and raw source example, without executing it.
        keys = ['board:esp32', 'component:epaper-1in54-bw', 'example:robot-desktop-eyes']
        keys += [entry['id'] for entry in self.catalog._entries.values() if entry['kind'] == 'example' and any('sourceC' in p.get('properties', {}) for p in entry['project']['components'])][:2]
        for key in keys:
            for section in TOOL_SCHEMAS['get_reference']['inputSchema']['properties']['section']['enum']:
                with self.subTest(key=key, section=section):
                    result = next(self.pages(self.catalog, 'get_reference', id=key, section=section))
                    self.assertIn('next_section', result)
                    self.assertIn('next_action', result)
