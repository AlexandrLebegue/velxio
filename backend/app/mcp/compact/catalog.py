"""Read-only catalog with bounded JSON responses; Python standard library only."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from pathlib import Path
import subprocess

from .contracts import MAX_RESPONSE_BYTES, MAX_SEARCH_OFFSET


class CatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def bounded(value):
    if len(encoded(value)) > MAX_RESPONSE_BYTES:
        return {"ok": False, "error": {"code": "quota_exceeded", "message": "Reference exceeds 24 KiB; request a smaller section. No data was silently truncated."}}
    return value


class Catalog:
    def __init__(self, snapshot):
        self._snapshot = copy.deepcopy(snapshot)
        if snapshot.get("schema_version") != 1:
            raise CatalogError("invalid_catalog", "Unsupported catalog schema")
        self.revision = snapshot["revision"]
        self._entries = {e["id"]: e for e in self._snapshot["entries"]}
        if len(self._entries) != len(snapshot["entries"]):
            raise CatalogError("invalid_catalog", "Duplicate catalog IDs")
        if not isinstance(self.revision, str) or len(self.revision) != 64:
            raise CatalogError("invalid_catalog", "Missing catalog revision")
        self._aliases = {}
        for entry in self._entries.values():
            for alias in [entry["key"], *entry.get("aliases", [])]:
                self._aliases.setdefault(alias, set()).add(entry["id"])

    @classmethod
    def from_snapshot(cls, path):
        path = Path(path)
        with path.open('rb') as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise CatalogError('quota_exceeded', 'Catalog snapshot exceeds 32 MiB')
        expected = path.with_suffix(path.suffix + '.sha256').read_text().strip()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise CatalogError('invalid_catalog', 'Snapshot SHA256 differs from packaged manifest')
        return cls(json.loads(raw))

    @classmethod
    def from_repository(cls, root: str | Path):
        root = Path(root).resolve()
        try:
            result = subprocess.run(["node", str(root / "scripts/generate-mcp-compact-catalog.cjs"), str(root)],
                                    capture_output=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            raise CatalogError("extraction_failed", "Local AST extractor failed: " + detail.decode("utf-8", "replace")[:300]) from exc
        if len(result.stdout) > 32 * 1024 * 1024:
            raise CatalogError("quota_exceeded", "Catalog snapshot exceeds 32 MiB")
        return cls(json.loads(result.stdout))

    def _guard(self, operation):
        try:
            return bounded(operation())
        except CatalogError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": str(exc)[:500]}}

    def search_catalog(self, **arguments):
        # Legacy model-generated cursors are ignored, never decoded or reused.
        arguments.pop("cursor", None)
        def run():
            from .examples import recipe_metadata
            if set(arguments) - {"query", "kind", "limit", "offset"}:
                raise CatalogError("invalid_argument", "Unknown search argument")
            query, kind, limit = arguments.get("query", ""), arguments.get("kind", "all"), arguments.get("limit", 5)
            offset = arguments.get("offset", 0)
            if not isinstance(query, str) or len(query) > 256 or kind not in ("all", "board", "component", "example"):
                raise CatalogError("invalid_argument", "Invalid query or kind")
            try:
                query.encode("utf-8")
            except UnicodeError:
                raise CatalogError("invalid_argument", "Query must be valid UTF-8 text")
            if type(limit) is not int or not 1 <= limit <= 50:
                raise CatalogError("invalid_argument", "limit must be an integer in 1..50")
            if type(offset) is not int or not 0 <= offset <= MAX_SEARCH_OFFSET:
                raise CatalogError("invalid_argument", f"offset must be an integer in 0..{MAX_SEARCH_OFFSET}")
            # Ignore separators within each indexed field: e-paper == e_paper
            # == e paper == epaper. Do not concatenate unrelated fields.
            def normalize(value):
                return re.sub(r"[-_\s]+", "", value.casefold())
            normalized = normalize(query)
            indexed = [(e, [normalize(field) for field in [e["id"], e["name"], e["summary"],
                        *e.get("aliases", []), *e.get("tags", []), *e.get("keywords", [])]])
                       for e in self._entries.values() if kind == "all" or e["kind"] == kind]
            matches = [e for e, fields in indexed if any(normalized in field for field in fields)]
            matches.sort(key=lambda e: e["id"])
            if kind == 'example' and query.strip():
                matches.sort(key=lambda entry: not recipe_metadata(entry['id'])['supported'])
            used = [query] if query.strip() else []
            # Expand only a genuinely empty result set, never an empty page.
            # Score the union by matching terms, then ID: stable across pages.
            if not matches and len(query.split()) > 1:
                terms = {}
                for word in query.split():
                    if len(normalize(word)) >= 2:
                        terms.setdefault(normalize(word), word)
                scored, matched_terms = [], set()
                for entry, fields in indexed:
                    hits = {term for term in terms if any(term in field for field in fields)}
                    if hits:
                        scored.append((len(hits), entry))
                        matched_terms.update(hits)
                matches = [entry for _, entry in sorted(scored, key=lambda item: (-item[0], not recipe_metadata(item[1]['id'])['supported'] if kind == 'example' else False, item[1]["id"]))]
                used = [word for term, word in terms.items() if term in matched_terms]
            page = matches[offset:offset + limit]
            return {"ok": True, "revision": self.revision, "items": [
                {"id": e["id"], "kind": e["kind"], "name": e["name"], "summary": e["summary"][:300],
                 **({'from_example': recipe_metadata(e['id'])} if e['kind'] == 'example' else {}),
                 **({"metadataId" if e["kind"] == "component" else "boardKind": e["key"]} if e["kind"] in ("component", "board") else {})} for e in page],
                "query_original": query, "query_used": used,
                "total": len(matches), "has_more": offset + len(page) < len(matches),
                "next_offset": offset + len(page) if offset + len(page) < len(matches) else None}
        return self._guard(run)

    def get_reference(self, **arguments):
        def run():
            from .examples import recipe_metadata
            if set(arguments) - {"id", "section"}:
                raise CatalogError("invalid_argument", "Unknown reference argument")
            key, section = arguments.get("id"), arguments.get("section", "overview")
            if not isinstance(key, str) or not 1 <= len(key) <= 240:
                raise CatalogError("invalid_argument", "id is required (max 240 characters)")
            sections = ("overview", "pins", "attrs", "protocol", "libraries", "init", "limitations", "sources", "files", "project", "code")
            if section not in sections:
                raise CatalogError("invalid_argument", "Unknown reference section")
            entry = self._entries.get(key)
            if entry is None:
                ids = self._aliases.get(key, set())
                if len(ids) > 1:
                    raise CatalogError("ambiguous_id", "Use a namespaced ID: " + ", ".join(sorted(ids)))
                if not ids:
                    raise CatalogError("not_found", "Catalog ID not found")
                entry = self._entries[next(iter(ids))]
            e = copy.deepcopy(entry)
            project = e.get("project")
            related = [x for x in self._entries.values() if x["kind"] == "example" and self._uses(x["project"], e)]
            libraries = [{"names": x["project"]["libraries"], "example_id": x["id"], "sources": x.get("library_sources") or x["sources"]}
                         for x in related if "libraries" in x["project"]]
            if project:
                libraries = [{"names": project.get("libraries", "unknown"), "sources": e.get("library_sources") or e["sources"]}]
            overview = {k: e[k] for k in ("name", "summary", "pins", "attrs", "protocol", "limitations", "sources")}
            overview["limitations"] += self._snapshot.get("limitations", [])
            # Overview summarizes declared dependencies; full evidence is an
            # explicit section. Missing manifests are not inferred from code.
            summary_libraries = {}
            for group in libraries:
                if isinstance(group["names"], list):
                    for name in group["names"]:
                        if name not in summary_libraries:
                            summary_libraries[name] = {"name": name, "sources": group["sources"], "evidence_count": 0}
                        summary_libraries[name]["evidence_count"] += 1
            overview.update({"libraries": list(summary_libraries.values()) or "unknown", "init": "unknown"})
            examples = self.related_examples(e["id"], limit=8)
            overview["example_references"] = [item["id"] for item in examples]
            overview['example_options'] = [{'id': item['id'], 'from_example': recipe_metadata(item['id'])} for item in examples]
            if e['kind'] == 'example':
                overview['from_example'] = recipe_metadata(e['id'])
            if "panel" in e and e["panel"]:
                overview["panel"] = e["panel"]
            if "fqbn" in e:
                overview.update({"fqbn": e["fqbn"], "languages": e["languages"]})
            files = self._files(project) if project else []
            if project:
                overview["files"] = [{k: v for k, v in f.items() if k != "content"} for f in files]
                overview["dependencies"] = project.get("libraries", "unknown")
            values = {**overview, "overview": overview, "libraries": libraries or "unknown",
                      "files": [{k: v for k, v in f.items() if k != "content"} for f in files],
                      "project": self._native_fragment(e) if e["kind"] != "example" else self._without_code(project),
                      "code": {"files": files, "raw_inputs": [
                          raw for raw in self._snapshot.get("raw_inputs", [])
                          if raw["decoded_sha256"] in {f["sha256"] for f in files}
                      ]} if project else "unknown"}
            if e["kind"] == "component":
                values["project"]["example_references"] = overview["example_references"]
                values['project']['example_options'] = overview['example_options']
            result = {"ok": True, "id": e["id"], "revision": self.revision, "section": section, "data": values[section]}
            if e['kind'] == 'example':
                result['from_example'] = recipe_metadata(e['id'])
            if section == "project" and e["kind"] in ("component", "board"):
                # Keep board data directly saveable; metadata belongs outside
                # that native document. Component data remains an append fragment.
                result["instance_template"] = copy.deepcopy(values["project"]["boards"][0] if e["kind"] == "board"
                                                            else values["project"]["instance_template"])
                result["example_references"] = overview["example_references"]
                result['example_options'] = overview['example_options']
            if e["kind"] == "board":
                result["execution"] = {"supported": False, "state": "unsupported",
                    "message": "The six-tool MCP compiles projects; it does not run a simulator. Do not poll for simulation startup."}
            return result
        return self._guard(run)

    @staticmethod
    def _native_fragment(entry):
        if entry["kind"] == "board":
            mode = "arduino" if "arduino" in entry.get("languages", []) else next(iter(entry.get("languages", [])), "arduino")
            instance_id = "esp" if entry["key"] == "esp32" else entry["key"] + "-1"
            return {"format": "velxio-project", "version": 1,
                    "boards": [{"id": instance_id, "boardKind": entry["key"], "x": 0, "y": 0,
                                "activeFileGroupId": "sketch", "languageMode": mode}],
                    "fileGroups": {"sketch": [{"name": "main.py" if mode == "micropython" else "sketch.ino", "content": ""}]},
                    "components": [], "wires": [], "activeBoardId": instance_id}
        if entry["kind"] == "component":
            template = {"id": "epd" if entry["key"] == "epaper-1in54-bw" else entry["key"] + "-1",
                        "metadataId": entry["key"], "x": 300, "y": 0, "properties": copy.deepcopy(entry.get("defaults", {}))}
            return {"components": [copy.deepcopy(template)], "instance_template": template,
                    "pinNames": [pin["name"] for pin in entry["pins"]] if isinstance(entry["pins"], list) else "unknown"}
        return "unknown"

    @staticmethod
    def _uses(project, entry):
        from .examples import uses_component
        if entry["kind"] == "component":
            return uses_component('example:' + project.get('id', ''), entry['key']) or any(c["type"].removeprefix("wokwi-").removeprefix("velxio-") == entry["key"] for c in project["components"])
        return entry["kind"] == "board" and (project.get("boardType") == entry["key"] or any(b["boardKind"] == entry["key"] for b in project.get("boards", [])))

    def _example_summary(self, entry, board_kind=None):
        from .examples import recipe_metadata
        project = entry["project"]
        recipe = recipe_metadata(entry['id'])
        boards = list(dict.fromkeys([
            *([project["boardType"]] if project.get("boardType") else []),
            *(board["boardKind"] for board in project.get("boards", [])),
        ]))
        if not boards and recipe['supported']:
            boards = [recipe['parameters']['properties']['board']['default']]
        return {"id": entry["id"], "title": entry["name"], "board_kinds": boards,
                "libraries": project.get("libraries", []),
                "code_available": bool(self._files(project)),
                "matches_active_board": board_kind in boards if board_kind else False, 'from_example': recipe}

    def related_examples(self, reference_id, board_kind=None, limit=5):
        """Metadata only, from actual matching examples; no code or compatibility invented."""
        entry = self._entries.get(reference_id)
        if entry is None or entry["kind"] not in ("component", "board"):
            return []
        examples = [self._example_summary(item, board_kind) for item in self._entries.values()
                    if item["kind"] == "example" and self._uses(item["project"], entry)]
        examples.sort(key=lambda item: (not item["matches_active_board"], not item['from_example']['supported'], not item["code_available"], item["id"]))
        return examples[:limit]

    def suggest_references(self, reference_id, limit=3):
        """Suggest existing IDs of the requested kind after a failed lookup."""
        kind, _, key = reference_id.partition(":")
        candidates = [item for item in self._entries.values() if item["kind"] == kind]
        words = set(key.replace("_", "-").casefold().split("-"))
        def score(item):
            overlap = len(words & set(item["key"].casefold().split("-"))) / max(1, len(words))
            return overlap + difflib.SequenceMatcher(None, key.casefold(), item["key"].casefold()).ratio()
        candidates.sort(key=lambda item: (-score(item), item["id"]))
        return [self._example_summary(item) if kind == "example" else {"id": item["id"], "title": item["name"]}
                for item in candidates[:limit] if score(item) >= .4]

    @staticmethod
    def _without_code(value):
        if isinstance(value, dict):
            return {k: Catalog._without_code(v) for k, v in value.items()
                    if k not in ("code", "content", "sourceC", "wasmBase64", "romBytes", "contentB64", "content_b64", "vfsFiles")}
        if isinstance(value, list):
            return [Catalog._without_code(v) for v in value]
        return value

    @staticmethod
    def _files(project):
        out = []
        groups = list(project.get("boards") or [project])
        if project.get("boards") and project.get("files"):
            groups.append(project)
        for index, group in enumerate(groups):
            for f in group.get("files") or ([{"name": "(inline code)", "content": group["code"]}] if group.get("code") else []):
                content = f["content"]
                out.append({"group": index, "name": f["name"], "content": content,
                            "size_bytes": len(content.encode()), "sha256": hashlib.sha256(content.encode()).hexdigest()})
            for name, content in group.get("vfsFiles", {}).items():
                out.append({"group": index, "name": name, "content": content,
                            "size_bytes": len(content.encode()), "sha256": hashlib.sha256(content.encode()).hexdigest()})
        for component in project.get("components", []):
            content = component.get("properties", {}).get("sourceC")
            if content:
                out.append({"group": "component:" + component["id"], "name": "(embedded sourceC)", "content": content,
                            "size_bytes": len(content.encode()), "sha256": hashlib.sha256(content.encode()).hexdigest()})
        return out
