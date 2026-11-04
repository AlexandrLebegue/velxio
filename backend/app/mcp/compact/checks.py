"""Bounded structural checks of exact snapshots. Never compiles or simulates."""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from .projects import DIR_FLAGS, VERSION, ProjectStore, canonical, fail, filename, validate_document
from .contracts import MAX_RESPONSE_BYTES
from .sketches import sketch_issues


class LibraryInventory:
    """Trusted injected inventory; verify local manifest bytes on every check."""

    def __init__(self, root, entries, *, complete=False):
        self.root, self.entries, self.complete = os.fspath(root), entries, complete

    def verify(self):
        if not os.path.isabs(self.root) or self.root != "/" and any(p in ("", ".", "..") for p in self.root.split("/")[1:]):
            fail("inventory_invalid", "Inventory root must be an absolute directory")
        fd = os.open("/", DIR_FLAGS)
        try:
            for part in ([] if self.root == "/" else self.root.split("/")[1:]):
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            evidence = {}
            if not isinstance(self.entries, dict) or len(self.entries) > 128 or type(self.complete) is not bool:
                fail("inventory_invalid", "Invalid inventory entries")
            for name, entry in self.entries.items():
                if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(entry, dict):
                    fail("inventory_invalid", "Invalid inventory library")
                filename(entry["path"])
                if not isinstance(entry["sha256"], str) or not VERSION.fullmatch(entry["sha256"]):
                    fail("inventory_invalid", "Invalid inventory hash")
                parent = os.dup(fd)
                try:
                    parts = entry["path"].split("/")
                    for part in parts[:-1]:
                        child = os.open(part, DIR_FLAGS, dir_fd=parent)
                        os.close(parent)
                        parent = child
                    file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if ProjectStore._regular(file).st_size > 1024 * 1024:
                            fail("inventory_invalid", "Inventory proof exceeds 1 MiB")
                        with os.fdopen(file, "rb", closefd=False) as stream:
                            raw = stream.read(1024 * 1024 + 1)
                    finally:
                        os.close(file)
                finally:
                    os.close(parent)
                if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    fail("inventory_invalid", "Inventory proof hash mismatch")
                evidence[name] = {"path": entry["path"], "sha256": entry["sha256"]}
            return {"entries": evidence, "complete": self.complete,
                    "sha256": hashlib.sha256(canonical({"entries": evidence, "complete": self.complete})).hexdigest()}
        finally:
            os.close(fd)


def legacy_file_behavior(node):
    """Project the new optional offline guards to their explicit None default.

    Compare to the ORIGINAL approved AST hash, not a new wildcard/fingerprint.
    Every unguarded change (including source naming/writing) still fails.
    """
    class DefaultProjection(ast.NodeTransformer):
        def visit_Name(self, n):
            return ast.copy_location(ast.Constant(None), n) if n.id == '_offline_plan' else n
        def visit_Compare(self, n):
            n = self.generic_visit(n)
            if isinstance(n.left, ast.Constant) and len(n.ops) == 1 and isinstance(n.comparators[0], ast.Constant):
                if isinstance(n.ops[0], ast.Is):
                    return ast.Constant(n.left.value is n.comparators[0].value)
                if isinstance(n.ops[0], ast.IsNot):
                    return ast.Constant(n.left.value is not n.comparators[0].value)
            return n
        def visit_BoolOp(self, n):
            n = self.generic_visit(n)
            if isinstance(n.op, ast.And):
                if any(isinstance(v, ast.Constant) and v.value is False for v in n.values):
                    return ast.Constant(False)
                n.values = [v for v in n.values if not (isinstance(v, ast.Constant) and v.value is True)]
                if len(n.values) == 1:
                    return n.values[0]
            return n
        def visit_If(self, n):
            n = self.generic_visit(n)
            if isinstance(n.test, ast.Constant):
                return n.body if n.test.value else n.orelse
            return n
    result = copy.deepcopy(node)
    if result.args.args and result.args.args[-1].arg == '_offline_plan':
        result.args.args.pop()
        result.args.defaults.pop()
    return DefaultProjection().visit(result)


def _policy_ast_dump_v1(node):
    """Frozen policy serialization: annotated Python 3.13-style compact dump.

    Keep field order and semantic values (including Constant(value=None)); omit
    empty list fields and optional None defaults. No attributes, ast.dump or
    3.13-only _field_types are used, so 3.12 emits the same fingerprint bytes.
    Versioning lives in this function's name, not the existing hash payload.
    """
    if not isinstance(node, ast.AST):
        raise TypeError('Policy serialization requires an AST node')

    def render(value):
        if isinstance(value, ast.AST):
            fields = []
            for name, child in ast.iter_fields(value):
                if isinstance(child, list) and not child:
                    continue
                if child is None and getattr(type(value), name, ...) is None:
                    continue
                fields.append(name + '=' + render(child))
            return type(value).__name__ + '(' + ', '.join(fields) + ')'
        if isinstance(value, list):
            return '[' + ', '.join(render(child) for child in value) + ']'
        return repr(value)

    return render(node)


class CompilerPolicy:
    """Extract constants and verify the pure basename helper AST, without imports."""

    def __init__(self, root):
        root = Path(root)
        name = "backend/app/services/espidf_compiler.py"
        raw = (root / name).read_bytes()
        tree = ast.parse(raw)
        fingerprints = {"_write_arduino_user_files": "3af9f3fc8c905d28a83933bfb4bba6ebe95053bef8a22c986cc66bbfc4d913b3",
                        "_compile_in_dir": "39faa596be9d697da91d5bb066db672ea64dcc430f767d070f9b8189569ec3fd"}
        for function, expected_hash in fingerprints.items():
            node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
            if function == '_compile_in_dir':
                node = legacy_file_behavior(node)
            if hashlib.sha256(_policy_ast_dump_v1(node).encode()).hexdigest() != expected_hash:
                raise ValueError("Compiler file-writing behavior changed; review required")
        assigns = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
        reserved = assigns["_MAIN_RESERVED_NAMES"].value
        if not isinstance(reserved, ast.Call) or not isinstance(reserved.args[0], ast.GeneratorExp):
            raise ValueError("Unsupported template reserved-name AST")
        self.reserved = {n.casefold() for n in ast.literal_eval(reserved.args[0].generators[0].iter)}
        self.prefix = ast.literal_eval(assigns["_USER_FILE_PREFIX"].value)
        self.suffixes = ast.literal_eval(assigns["_COMPILED_SUFFIXES"].value)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_user_main_name")
        expected = ast.parse('''
def expected(name):
    base = PurePosixPath(str(name or '').replace('\\\\', '/')).name
    if base in ('', '.', '..'):
        return None
    if base.casefold() in _MAIN_RESERVED_NAMES:
        return _USER_FILE_PREFIX + base
    return base
''').body[0]
        body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) and isinstance(fn.body[0].value.value, str) else fn.body
        if ast.dump(ast.Module(body=body, type_ignores=[])) != ast.dump(ast.Module(body=expected.body, type_ignores=[])):
            raise ValueError("User-file mapping changed; review required")
        source = raw.decode()
        if "entry_file = files[0]" not in source or "ino_files[0]" not in source or "f['name'] == 'sketch.ino'" not in source:
            raise ValueError("Sketch entry selection changed")
        self.sources = [{"path": name, "line": fn.lineno, "sha256": hashlib.sha256(raw).hexdigest()}]
        template = root / "backend/app/services/esp-idf-template/main"
        self.template_names = {p.name.casefold() for p in template.iterdir() if p.is_file()}
        for p in sorted(template.iterdir()):
            if p.is_file():
                self.sources.append({"path": p.relative_to(root).as_posix(), "line": 1, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        cli = root / "backend/app/services/arduino_cli.py"
        cli_raw = cli.read_bytes()
        cli_fn = next(n for n in ast.walk(ast.parse(cli_raw)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "compile")
        if hashlib.sha256(_policy_ast_dump_v1(cli_fn).encode()).hexdigest() != "58c4fd9f87d4aedfe6ef19e2a907075ae52bb5cea73ae3db6ff986025ff562e9":
            raise ValueError("Arduino sketch promotion changed")
        self.sources.append({"path": cli.relative_to(root).as_posix(), "line": cli_fn.lineno, "sha256": hashlib.sha256(cli_raw).hexdigest()})


def pointer(*parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class ProjectChecker:
    def __init__(self, store, catalog, *, source_root=None, inventory=None):
        self.store, self.catalog, self.inventory = store, catalog, inventory
        self.source_root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[4]

    def check_project(self, **arguments):
        def run():
            if set(arguments) != {"project_id", "version"}:
                fail("invalid_argument", "check_project requires project_id and an exact version")
            pid, version = arguments["project_id"], arguments["version"]
            with self.store._locked(False) as root:
                doc = self.store._load_version(root, pid, version)
            validate_document(doc)
            report = self._check(doc, pid, version)
            meta = self.store._store_report(pid, version, report)
            issues = []
            ordered = sorted(report['issues'], key=lambda issue: issue['severity'] != 'error')
            for issue in ordered[:20]:
                small = dict(issue)
                if len(small["path"]) > 512:
                    small.update(path=small["path"][:512], path_truncated=True)
                issues.append(small)
            result = {"ok": True, "status": report["status"], "structure_status": report["structure_status"],
                    "project_id": pid, "version": version, "catalog_revision": self.catalog.revision,
                    "checks_performed": report["checks_performed"], "checks_unavailable": report["checks_unavailable"],
                    "diagnostic_summary": f'{report["counts"]["error"]} structural errors; {len(report["issues"])} diagnostics; no electrical or functional validation',
                    "diagnostic_artifact_id": meta["artifact_id"], "diagnostic_artifact_sha256": meta["sha256"],
                    "issues": issues, "issue_count": len(report["issues"]), "issues_truncated": len(report["issues"]) > len(issues)}
            error = next((issue for issue in ordered if issue['severity'] == 'error'), None)
            result['next_action'] = (error.get('next_action', 'Repair the reported error, save a new version and call check_project again.') if error else
                                     'Review unavailable checks; request a build only with verified dependency and toolchain evidence.')
            while len(canonical(result)) > MAX_RESPONSE_BYTES and issues:
                issues.pop()
                result["issues_truncated"] = True
            return result
        return self.store._response(run)

    def _check(self, doc, pid, version):
        issues = []
        unavailable = {"electrical_validation", "functional_simulation", "compiler_execution"}
        performed = ["snapshot_integrity", "object_ids", "catalog_ids", "known_attributes", "endpoints", "documented_pins", "duplicate_connections", "gpio_role_overlap", "declared_dependencies", "board_language"]

        def emit(code, path, severity, message, **details):
            if len(issues) >= 4096:
                fail("quota_exceeded", "Check exceeds 4096 diagnostics; complete report was not truncated")
            issues.append({"code": code, "path": path, "severity": severity, "message": message[:240], **details})

        entries = self.catalog._entries
        known_libraries = {name for item in entries.values() if item["kind"] == "example"
                           for name in item["project"].get("libraries", []) if isinstance(name, str)}
        def component_entry(key):
            return entries.get("component:" + key) or entries.get("component:" + key.removeprefix("wokwi-").removeprefix("velxio-"))

        try:
            policy = CompilerPolicy(self.source_root)
            performed.append("compiler_file_layout")
        except (OSError, ValueError, KeyError, StopIteration, TypeError, IndexError, SyntaxError):
            policy = None
            unavailable.add("compiler_file_layout")
            emit("template_policy_unknown", "/fileGroups", "unknown", "Compiler/template policy could not be verified from the local sources")
        inventory = None
        if self.inventory is not None:
            try:
                inventory = self.inventory.verify()
            except (OSError, ValueError, KeyError, TypeError):
                emit("inventory_unverified", "/boards", "unknown", "Injected dependency inventory could not be verified")
        if inventory is None:
            unavailable.add("installed_dependencies")

        objects = {}
        for index, board in enumerate(doc["boards"]):
            path = pointer("boards", index)
            entry = entries.get("board:" + board["boardKind"])
            objects[board["id"]] = (entry, board, path, True)
            if entry is None:
                emit("board_unknown", path + "/boardKind", "error", "Board kind does not exist in this catalog revision")
            else:
                languages = entry.get("languages", [])
                mode = board.get("languageMode", "arduino")
                if languages and mode not in languages:
                    emit("language_unsupported", path + "/languageMode", "error", "Language is not supported by the documented board capabilities")
                if not languages:
                    unavailable.add("board_language_support")
                    emit("language_support_unknown", path + "/languageMode", "unknown", "Board language support is not documented by this catalog")
            libraries = board.get("libraries")
            if libraries is None:
                emit("dependencies_undeclared", path + "/libraries", "unknown", "No dependency manifest; requirements cannot be inferred")
                unavailable.add("dependency_requirements")
            elif not isinstance(libraries, list) or any(not isinstance(n, str) or not 1 <= len(n) <= 200 for n in libraries):
                emit("dependencies_invalid", path + "/libraries", "error", "Dependency manifest must contain nonempty names")
            else:
                for li, name in enumerate(libraries):
                    lp = path + f"/libraries/{li}"
                    emit("dependency_declared", lp, "info", name)
                    if name not in known_libraries:
                        emit("dependency_name_unknown", lp, "unknown", "Library name has no declaration evidence in this catalog; not a claim that it is absent")
                        unavailable.add("dependency_catalog_coverage")
                    if inventory is None or (name not in inventory["entries"] and not inventory["complete"]):
                        emit("dependency_availability_unknown", lp, "unknown", "Declared dependency availability has no verified inventory evidence")
                        unavailable.add("installed_dependencies")
                    elif name not in inventory["entries"]:
                        emit("dependency_absent", lp, "error", "Dependency is absent from the verified, caller-declared complete inventory")
                    else:
                        emit("dependency_manifest_verified", lp, "info", "Manifest bytes match injected inventory; compilation compatibility remains unchecked")
            if board.get('languageMode', 'arduino') == 'arduino':
                if 'arduino_sketch_sanity' not in performed:
                    performed.append('arduino_sketch_sanity')
                for issue in sketch_issues(doc['fileGroups'][board['activeFileGroupId']], pointer('fileGroups', board['activeFileGroupId'])):
                    emit(**issue)
            if policy is not None:
                self._files(board, doc["fileGroups"][board["activeFileGroupId"]], policy, emit)

        for index, component in enumerate(doc["components"]):
            path = pointer("components", index)
            entry = component_entry(component["metadataId"])
            objects[component["id"]] = (entry, component, path, False)
            if entry is None:
                emit("component_unknown", path + "/metadataId", "error", "Component ID does not exist in this catalog revision")
                continue
            attrs = {a["name"]: a for a in entry.get("attrs", [])}
            for name, value in component["properties"].items():
                ap = path + pointer("properties", name)
                attr = attrs.get(name)
                if attr is None:
                    emit("attribute_unknown", ap, "unknown", "Attribute is not documented; preserved without inventing validation rules")
                    unavailable.add("undocumented_attributes")
                    continue
                kind = attr["type"]
                valid = (kind in ("string", "color", "select") and isinstance(value, str) or
                         kind == "number" and type(value) in (int, float) or kind == "boolean" and type(value) is bool)
                default = entry.get("defaults", {}).get(name)
                if (not valid and name in entry.get("defaults", {})
                    and type(value) is type(default) and value == default):
                    # Some authored UI defaults contradict their declared
                    # property type (e.g. LED brightness=1, type=string).
                    # Preserve the exact native default, but do not certify it.
                    emit("attribute_default_type_unknown", ap, "unknown", "Native default contradicts the documented type; preserved as authored")
                    unavailable.add("attribute_type_consistency")
                    continue
                if not valid:
                    emit("attribute_type", ap, "error", "Attribute value does not match its documented type")
                elif ("options" in attr and value not in attr["options"]) or (kind == "number" and (value < attr.get("min", value) or value > attr.get("max", value))):
                    emit("attribute_range", ap, "error", "Attribute value is outside its documented options/range")
            if entry.get("panel"):
                panel = component["properties"].get("panelKind", entry["key"])
                if not isinstance(panel, str) or not entries.get("component:" + panel, {}).get("panel"):
                    emit("panel_kind_unknown", path + "/properties/panelKind", "error", "panelKind is not a documented e-paper panel")

        physical = {}
        def endpoint(ep, path):
            entry, obj, _, is_board = objects[ep["componentId"]]
            pins = entry.get("pins", "unknown") if entry else "unknown"
            if pins == "unknown":
                unavailable.add("undocumented_pins")
                emit("pins_unknown", path, "unknown", "Pin list is not documented for this object")
                return (ep["componentId"], ep["pinName"])
            pin = next((p for p in pins if p["name"] == ep["pinName"]), None)
            if pin is None:
                emit("pin_invalid", path, "error", "Pin does not exist in the documented physical pin list")
                return (ep["componentId"], ep["pinName"])
            key = (ep["componentId"], str((pin["x"], pin["y"]))) if "x" in pin and "y" in pin else (ep["componentId"], pin["name"])
            gpio = is_board and (pin["name"].isdigit() or any(p["name"].isdigit() and p.get("x") == pin.get("x") and p.get("y") == pin.get("y") for p in pins))
            physical[key] = (is_board, gpio, bool(entry.get("panel")), pin["name"])
            return key

        parents = {}
        def find(key):
            parents.setdefault(key, key)
            while parents[key] != key:
                parents[key] = parents[parents[key]]
                key = parents[key]
            return key
        connections = set()
        for index, wire in enumerate(doc["wires"]):
            path = pointer("wires", index)
            start, end = endpoint(wire["start"], path + "/start/pinName"), endpoint(wire["end"], path + "/end/pinName")
            pair = tuple(sorted((start, end)))
            if pair in connections:
                emit("connection_duplicate", path, "warning", "An equivalent undirected physical connection already exists")
            connections.add(pair)
            parents[find(start)] = find(end)
        nets = {}
        for key in physical:
            nets.setdefault(find(key), []).append(key)
        for members in nets.values():
            gpio = [k for k in members if physical[k][1]]
            roles = {}
            for key in members:
                if physical[key][2] and physical[key][3] in ("SCK", "SDI", "CS", "DC", "RST"):
                    roles.setdefault(key[0], set()).add(physical[key][3])
            if gpio and any(len(r) > 1 for r in roles.values()):
                emit("gpio_role_conflict", "/wires", "error", "One GPIO net connects distinct documented signal roles of the same e-paper panel; structural overlap only")
            if len(gpio) > 1:
                emit("gpio_directions_unknown", "/wires", "unknown", "Multiple board GPIOs share a net; directions and electrical behavior are not established")
                unavailable.add("gpio_directions")
        errors = sum(i["severity"] == "error" for i in issues)
        return {"format": "velxio-check-report", "schema_version": 1, "project_id": pid, "version": version,
                "catalog_revision": self.catalog.revision, "status": "invalid" if errors else "partial",
                "structure_status": "invalid" if errors else "valid", "issues": issues,
                "counts": {s: sum(i["severity"] == s for i in issues) for s in ("error", "warning", "unknown", "info")},
                "checks_performed": performed, "checks_unavailable": sorted(unavailable),
                "compiler_policy_sources": policy.sources if policy else [], "inventory": inventory,
                "limits": {"max_diagnostics": 4096, "max_report_bytes": 2 * 1024 * 1024}}

    @staticmethod
    def _files(board, files, policy, emit):
        group = board["activeFileGroupId"]
        path = pointer("fileGroups", group)
        mode = board.get("languageMode", "arduino")
        if mode == "micropython":
            emit("compiler_layout_not_applicable", path, "info", "Arduino/ESP-IDF file mapping is not applied to MicroPython")
            return
        esp = board["boardKind"].startswith(("esp32", "xiao-esp32", "arduino-nano-esp32", "wemos-lolin32", "aitewinrobot-esp32")) or mode == "espidf"
        inos = [f for f in files if f["name"].endswith(".ino")]
        if mode != "espidf" and len(inos) > 1 and not any(f["name"] == "sketch.ino" for f in inos):
            emit("sketch_entry_ambiguous", path, "error", "Several .ino files without literal sketch.ino; primary depends on file order")
        entry = next((f for f in inos if f["name"] == "sketch.ino"), inos[0] if inos else files[0] if files and esp else None)
        if mode != "espidf":
            emit("sketch_entry", path + (f"/{files.index(entry)}/name" if entry else ""), "info", "Primary: " + (entry["name"] if entry else "none; compiler may synthesize an empty sketch"))
            if not inos:
                emit("sketch_fallback", path, "warning", "No .ino; first-file fallback or empty sketch is not proof of a useful build")
        if not esp:
            return
        targets = {}
        for index, file in enumerate(files):
            name = file["name"]
            base = PurePosixPath(name).name
            if mode != "espidf" and (name.endswith(".ino") or file is entry and name.endswith(policy.suffixes)):
                continue
            target = base
            if mode != "espidf" and base.casefold() in policy.reserved:
                target = policy.prefix + base
                emit("template_name_renamed", path + f"/{index}/name", "info", f"Compiler maps {base} to {target}")
            controls = (policy.template_names - {"main.c", "main.cpp"}) | {n for n in policy.reserved if n.endswith((".txt", ".yml"))}
            if mode == "espidf" and base.casefold() in controls:
                emit("template_control_collision", path + f"/{index}/name", "error", "Pure ESP-IDF input overlaps a template-owned configure/support file")
            key = target.casefold()
            if key in targets:
                emit("template_name_collision", path + f"/{index}/name", "error", "Distinct sources map to the same template filename: " + target)
            targets[key] = name
