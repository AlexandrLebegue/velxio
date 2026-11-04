"""Native project snapshots and bounded artifact reads; POSIX, stdlib only."""

from __future__ import annotations

import base64
import copy
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import unicodedata
import uuid
from pathlib import Path

from .catalog import CatalogError, bounded
from .contracts import MAX_PROJECT_BYTES, MAX_RESPONSE_BYTES

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
ID = re.compile(r"^[pab]_[0-9a-f]{32}$")
VERSION = re.compile(r"^[0-9a-f]{64}$")
PATCH_ROOTS = {"name", "boards", "fileGroups", "folderGroups", "components", "wires", "activeBoardId"}


def fail(code, message):
    raise CatalogError(code, message)


MISSING = object()


def pointer(path, key):
    token = str(key).encode('utf-8', 'backslashreplace').decode('utf-8')
    return path + '/' + token.replace('~', '~0').replace('/', '~1')


def validation_error(path, received, expected, code='invalid_argument'):
    if received is MISSING:
        preview = '<missing>'
    else:
        try:
            # Stream the JSON preview, avoiding a full copy of large containers.
            chunks = json.JSONEncoder(ensure_ascii=True, allow_nan=True).iterencode(received)
            preview = ''
            for chunk in chunks:
                preview += chunk[:201]
                if len(preview) > 200:
                    break
        except (ValueError, TypeError, RecursionError):
            preview = repr(type(received))
        if len(preview) > 200:
            preview = preview[:197] + '...'
    error = CatalogError(code, f'{path or "(root)"}: expected {expected}; received {preview}'[:500])
    error.details = {'path': path, 'received': preview, 'expected': expected[:500]}
    return error


def invalid(path, received, expected, code='invalid_argument'):
    raise validation_error(path, received, expected, code)


def canonical(value, path=''):
    def check(item, current):
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    invalid(current, key, 'JSON object keys must be strings')
                try:
                    key.encode('utf-8')
                except UnicodeError:
                    invalid(pointer(current, key), key, 'valid UTF-8 object key')
                check(child, pointer(current, key))
        elif isinstance(item, list):
            for i, child in enumerate(item):
                check(child, pointer(current, i))
        elif type(item) not in (str, int, float, bool, type(None)):
            invalid(current, item, 'native JSON value')
        elif type(item) is float and not math.isfinite(item):
            invalid(current, item, 'finite JSON number')
        elif isinstance(item, str):
            try:
                item.encode('utf-8')
            except UnicodeError:
                invalid(current, item, 'valid UTF-8 string')
    try:
        check(value, path)
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, CatalogError):
            raise
        invalid(path, value, 'finite UTF-8 JSON within recursion limits')


def text(value, maximum=200, path=''):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or re.search(r'[\x00-\x1f\x7f]', value):
        invalid(path, value, f'string of 1..{maximum} characters without control characters')
    try:
        value.encode('utf-8')
    except UnicodeError:
        invalid(path, value, 'valid UTF-8 string')


def filename(value, path=''):
    text(value, 240, path)
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        invalid(path, value, 'valid UTF-8 file path')
    if size > 240 or '\\' in value or value.startswith('/') or re.search(r'[:*?"<>|]', value):
        invalid(path, value, 'portable relative POSIX file path, at most 240 UTF-8 bytes')
    for part in value.split('/'):
        if part in ('', '.', '..') or part.endswith(('.', ' ')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part):
            invalid(path, value, 'relative file path without empty, traversal, reserved or ambiguous segments')
    return unicodedata.normalize('NFC', value).casefold()


def finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def validate_document(doc):
    if not isinstance(doc, dict):
        invalid('', doc, 'native project object')
    required = {'format': '"velxio-project"', 'version': 'integer 1',
                'boards': 'array of native board objects', 'fileGroups': 'object mapping group IDs to file arrays',
                'components': 'array of native component objects', 'wires': 'array of native wire objects',
                'activeBoardId': 'existing board instance ID or null'}
    for field in sorted(required.keys() - doc.keys()):
        invalid(pointer('', field), MISSING, required[field])
    for field in doc.keys() - required - {'name', 'exportedAt', 'folderGroups'}:
        invalid(pointer('', field), doc[field], 'known native document field')
    if doc['format'] != 'velxio-project':
        invalid('/format', doc['format'], '"velxio-project"')
    if type(doc['version']) is not int or doc['version'] != 1:
        invalid('/version', doc['version'], 'integer 1')
    for key, maximum in (('name', 200), ('exportedAt', 80)):
        if key in doc:
            text(doc[key], maximum, pointer('', key))
    for key, maximum in (('boards', 8), ('components', 512), ('wires', 1024)):
        if not isinstance(doc[key], list):
            invalid(pointer('', key), doc[key], 'array')
        if len(doc[key]) > maximum:
            invalid(pointer('', key), doc[key], f'at most {maximum} items', 'quota_exceeded')
    groups = doc['fileGroups']
    if not isinstance(groups, dict) or len(groups) > 128:
        invalid('/fileGroups', groups, 'object with at most 128 file groups')
    count = total = 0
    basenames = {}

    def file_set(items, path, binary=False, content_key='content', embedded=False):
        nonlocal count, total
        if not isinstance(items, list):
            invalid(path, items, 'array of file objects')
        seen, bases = set(), set()
        collision = None
        for i, item in enumerate(items):
            current = pointer(path, i)
            if not isinstance(item, dict):
                invalid(current, item, 'file object with name and ' + content_key)
            for field in ('name', content_key):
                if field not in item:
                    expected = 'portable relative POSIX file path' if field == 'name' else ('base64 string' if binary else 'UTF-8 source string')
                    invalid(pointer(current, field), MISSING, expected)
            normalized = filename(item['name'], pointer(current, 'name'))
            if normalized in seen:
                invalid(pointer(current, 'name'), item['name'], 'unique file path after normalization/casefold')
            if any(normalized.startswith(other + '/') or other.startswith(normalized + '/') for other in seen):
                invalid(pointer(current, 'name'), item['name'], 'file path without file/directory collision')
            seen.add(normalized)
            base = normalized.rsplit('/', 1)[-1]
            if base in bases and collision is None:
                collision = (pointer(current, 'name'), item['name'])
            bases.add(base)
            content = item[content_key]
            content_path = path if embedded else pointer(current, content_key)
            if not isinstance(content, str):
                invalid(content_path, content, 'base64 string' if binary else 'UTF-8 source string')
            try:
                raw = base64.b64decode(content, validate=True) if binary else content.encode('utf-8')
            except (ValueError, UnicodeError):
                invalid(content_path, content, 'valid base64' if binary else 'valid UTF-8 string')
            if not binary and len(raw) > 256 * 1024:
                invalid(content_path, content, 'source at most 256 KiB', 'quota_exceeded')
            count += 1
            total += len(raw)
            if count > 128 or total > MAX_PROJECT_BYTES:
                invalid(content_path, content, 'at most 128 files and 2 MiB decoded data per project', 'quota_exceeded')
        return collision

    for group, items in groups.items():
        current = pointer('/fileGroups', group)
        text(group, path=current)
        basenames[group] = file_set(items, current)
    ids, board_ids = set(), set()
    for kind in ('boards', 'components'):
        for i, item in enumerate(doc[kind]):
            current = pointer('/' + kind, i)
            if not isinstance(item, dict):
                invalid(current, item, 'native board object' if kind == 'boards' else 'native component object')
            fields = ('id', 'boardKind', 'activeFileGroupId') if kind == 'boards' else ('id', 'metadataId')
            for field in fields:
                text(item.get(field, MISSING), path=pointer(current, field))
            if item['id'] in ids:
                invalid(pointer(current, 'id'), item['id'], 'unique board/component instance ID')
            ids.add(item['id'])
            for axis in ('x', 'y'):
                value = item.get(axis, MISSING)
                if not finite_number(value):
                    invalid(pointer(current, axis), value, 'finite canvas coordinate number')
            if kind == 'boards':
                board_ids.add(item['id'])
                group = item['activeFileGroupId']
                if group not in groups:
                    invalid(pointer(current, 'activeFileGroupId'), group, 'existing key in fileGroups')
                mode = item.get('languageMode', 'arduino')
                if mode not in ('arduino', 'micropython', 'espidf'):
                    invalid(pointer(current, 'languageMode'), mode, 'one of arduino, micropython, espidf')
                if item['boardKind'].startswith(('esp32', 'xiao-esp32', 'arduino-nano-esp32', 'wemos-lolin32', 'aitewinrobot-esp32')) or mode == 'espidf':
                    if basenames[group]:
                        path, name = basenames[group]
                        invalid(path, name, 'unique basename within the board file group for ESP-IDF source mapping')
                for key in ('spiffsFiles', 'sdFiles'):
                    if key in item:
                        file_set(item[key], pointer(current, key), True, 'contentB64')
            else:
                properties = item.get('properties', MISSING)
                prop_path = pointer(current, 'properties')
                if not isinstance(properties, dict):
                    invalid(prop_path, properties, 'properties object; use get_reference(section=project) defaults or {}')
                if 'sdFiles' in properties:
                    file_set(properties['sdFiles'], pointer(prop_path, 'sdFiles'), True, 'contentB64')
                if 'sourceC' in properties:
                    content = properties['sourceC']
                    if not isinstance(content, str):
                        invalid(pointer(prop_path, 'sourceC'), content, 'UTF-8 source string')
                    if content:
                        file_set([{'name': 'embedded-source.c', 'content': content}], pointer(prop_path, 'sourceC'), embedded=True)
    wire_ids = set()
    for i, wire in enumerate(doc['wires']):
        current = pointer('/wires', i)
        if not isinstance(wire, dict):
            invalid(current, wire, 'native wire object with id, start, end')
        text(wire.get('id', MISSING), path=pointer(current, 'id'))
        if wire['id'] in wire_ids:
            invalid(pointer(current, 'id'), wire['id'], 'unique wire ID')
        wire_ids.add(wire['id'])
        for key in ('start', 'end'):
            endpoint = wire.get(key, MISSING)
            ep_path = pointer(current, key)
            if not isinstance(endpoint, dict):
                invalid(ep_path, endpoint, 'endpoint object with componentId and pinName')
            for field in ('componentId', 'pinName'):
                text(endpoint.get(field, MISSING), path=pointer(ep_path, field))
            if endpoint['componentId'] not in ids:
                invalid(pointer(ep_path, 'componentId'), endpoint['componentId'], 'existing board or component instance ID')
            for axis in ('x', 'y'):
                if axis in endpoint and not finite_number(endpoint[axis]):
                    invalid(pointer(ep_path, axis), endpoint[axis], 'finite coordinate number')
        if 'color' in wire:
            text(wire['color'], 100, pointer(current, 'color'))
        if 'waypoints' in wire:
            waypoints = wire['waypoints']
            wp_path = pointer(current, 'waypoints')
            if not isinstance(waypoints, list):
                invalid(wp_path, waypoints, 'array of {x:number,y:number}')
            for j, point in enumerate(waypoints):
                point_path = pointer(wp_path, j)
                if not isinstance(point, dict):
                    invalid(point_path, point, 'waypoint object with x and y')
                for axis in ('x', 'y'):
                    value = point.get(axis, MISSING)
                    if not finite_number(value):
                        invalid(pointer(point_path, axis), value, 'finite coordinate number')
    active = doc['activeBoardId']
    if active is not None and (not isinstance(active, str) or active not in board_ids):
        invalid('/activeBoardId', active, 'existing board instance ID or null')
    folders = doc.get('folderGroups', {})
    if not isinstance(folders, dict):
        invalid('/folderGroups', folders, 'object mapping existing file group IDs to folder arrays')
    for group, names in folders.items():
        current = pointer('/folderGroups', group)
        if group not in groups or not isinstance(names, list):
            invalid(current, names, 'folder array under an existing fileGroups key')
        for i, name in enumerate(names):
            filename(name, pointer(current, i))
    raw = canonical(doc)
    if len(raw) > MAX_PROJECT_BYTES:
        invalid('', doc, 'serialized native project at most 2 MiB', 'quota_exceeded')
    return raw


def validate_changes(changes):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 128:
        invalid('/changes', changes, 'array of 1..128 set/remove operations')
    operations = []
    for index, change in enumerate(changes):
        current = pointer('/changes', index)
        if not isinstance(change, dict):
            invalid(current, change, 'operation object with op, path and optional value')
        for field in change.keys() - {'op', 'path', 'value'}:
            invalid(pointer(current, field), change[field], 'known operation field: op, path, value')
        op, path = change.get('op', MISSING), change.get('path', MISSING)
        if op not in ('set', 'remove'):
            invalid(pointer(current, 'op'), op, 'one of set, remove')
        if (op == 'set') != ('value' in change):
            invalid(pointer(current, 'value'), change.get('value', MISSING), 'required value for set; absent for remove')
        path_field = pointer(current, 'path')
        if not isinstance(path, str) or not path.startswith('/') or len(path) > 512 or re.search(r'~(?![01])', path):
            invalid(path_field, path, 'RFC 6901 pointer of at most 512 characters')
        tokens = [part.replace('~1', '/').replace('~0', '~') for part in path[1:].split('/')]
        if tokens[0] not in PATCH_ROOTS:
            invalid(path_field, path, 'pointer below ' + ', '.join(sorted(PATCH_ROOTS)))
        operations.append((change, op, path, path_field, tokens))
    return operations


def patch(doc, changes):
    operations = validate_changes(changes)
    result = copy.deepcopy(doc)
    for change, op, path, path_field, tokens in operations:
        parent = result
        for i, token in enumerate(tokens):
            last = i == len(tokens) - 1
            if isinstance(parent, list):
                if not re.fullmatch(r'0|[1-9][0-9]*', token) or int(token) >= len(parent):
                    invalid(path_field, path, 'existing array index (no implicit insertion)')
                key = int(token)
            elif isinstance(parent, dict):
                key = token
                if (not last or op == 'remove') and key not in parent:
                    invalid(path_field, path, 'existing path for traversal/remove')
            else:
                invalid(path_field, path, 'path traversing objects/arrays, not scalars')
            if last:
                if op == 'remove':
                    del parent[key]
                else:
                    parent[key] = copy.deepcopy(change['value'])
            else:
                parent = parent[key]
    return result


def validate_save_arguments(arguments):
    if not isinstance(arguments, dict):
        invalid('', arguments, 'save_project argument object')
    for field in arguments.keys() - {'document', 'changes', 'project_id', 'expected_version', 'sketch', 'board', 'board_id', 'libraries'}:
        invalid(pointer('', field), arguments[field], 'known save argument: document, changes, project_id, expected_version')
    updating = 'project_id' in arguments
    if ('expected_version' in arguments) != updating:
        field = 'expected_version' if updating else 'project_id'
        invalid('/' + field, MISSING, 'required together: project_id and expected_version for updates')
    if sum(field in arguments for field in ('document', 'changes', 'sketch')) != 1:
        invalid('/changes' if 'changes' in arguments else '/document', arguments.get('changes', MISSING), 'exactly one of document, changes or sketch')
    if 'sketch' in arguments:
        if not isinstance(arguments['sketch'], str):
            invalid('/sketch', arguments['sketch'], 'plain source text')
        if len(arguments['sketch'].encode('utf-8')) > 262144:
            invalid('/sketch', '<oversized source>', 'at most 262144 UTF-8 bytes', 'quota_exceeded')
        if updating and 'board' in arguments:
            invalid('/board', arguments['board'], 'board is creation-only; use board_id for updates')
        if not updating and 'board_id' in arguments:
            invalid('/board_id', arguments['board_id'], 'board_id selects an existing board during updates')
        for field in ('board', 'board_id'):
            if field in arguments:
                text(arguments[field], path='/' + field)
        if 'libraries' in arguments and (not isinstance(arguments['libraries'], list) or len(arguments['libraries']) > 128
                or any(not isinstance(item, str) or not 1 <= len(item) <= 200 for item in arguments['libraries'])):
            invalid('/libraries', arguments['libraries'], 'array of up to 128 declared library names')
    elif arguments.keys() & {'board', 'board_id', 'libraries'}:
        invalid('', arguments, 'board, board_id and libraries are options of the sketch form only')
    if 'changes' in arguments and not updating:
        invalid('/project_id', MISSING, 'existing project_id plus expected_version for changes')
    if updating:
        project_id = arguments['project_id']
        if not isinstance(project_id, str) or not ID.fullmatch(project_id) or not project_id.startswith('p_'):
            invalid('/project_id', project_id, 'opaque project ID: p_ followed by 32 lowercase hex characters')
        version = arguments['expected_version']
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            invalid('/expected_version', version, '64 lowercase hex characters from the last save_project version')
    # Validate native snapshots first, so their pointers are document-relative.
    raw = validate_document(arguments['document']) if 'document' in arguments else None
    if 'changes' in arguments:
        validate_changes(arguments['changes'])
    if len(canonical(arguments)) > MAX_PROJECT_BYTES + 16384:
        invalid('', arguments, 'save request at most 2 MiB + 16 KiB', 'quota_exceeded')
    return raw


class ProjectStore:
    def __init__(self, root="/app/data/mcp-compact", *, max_storage_bytes=256 * 1024 * 1024, catalog=None):
        self.catalog = catalog
        self.root = os.fspath(root)
        if not os.path.isabs(self.root) or "\\" in self.root or any(p in (".", "..", "") for p in self.root.split("/")[1:]):
            fail("unsafe_path", "Storage root must be an absolute, unambiguous path")
        if type(max_storage_bytes) is not int or max_storage_bytes < 0:
            fail("invalid_argument", "Invalid storage quota")
        self.max_storage_bytes = max_storage_bytes
        fd = self._root(create=True)
        try:
            self._identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
        finally:
            os.close(fd)

    def _root(self, create=False):
        fd = os.open("/", DIR_FLAGS)
        try:
            for part in self.root.split("/")[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            if hasattr(self, "_identity") and (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != self._identity:
                fail("unsafe_path", "Storage root was replaced")
            return fd
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                fail("quota_exceeded", "Storage allocation failed; existing files retained")
            fail("unsafe_path", "Storage root or parent is not a safe directory")
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def _directory(self, parent, name, create=False):
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
        fd = os.open(name, DIR_FLAGS, dir_fd=parent)
        try:
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _locked(self, exclusive):
        root = self._root()
        lock = None
        try:
            lock = os.open(".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
            self._regular(lock)
            fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            current = os.stat(".lock", dir_fd=root, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (os.fstat(lock).st_dev, os.fstat(lock).st_ino):
                fail("unsafe_path", "Storage lock was replaced")
            yield root
        finally:
            if lock is not None:
                os.close(lock)
            os.close(root)

    @staticmethod
    def _regular(fd):
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            fail("unsafe_path", "Expected a regular file without hardlinks")
        return st

    def _read(self, parent, name, maximum=MAX_PROJECT_BYTES):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            if self._regular(fd).st_size > maximum:
                fail("quota_exceeded", "Stored file exceeds read quota")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                fail("quota_exceeded", "Stored file exceeds read quota")
            return raw
        finally:
            os.close(fd)

    def _publish(self, parent, name, raw, replace=False):
        try:
            old = self._read(parent, name, max(MAX_PROJECT_BYTES, len(raw)))
        except FileNotFoundError:
            old = None
        if old is not None and not replace:
            if old != raw:
                fail("integrity_error", "Refusing to replace an immutable file")
            return
        temp = ".tmp-" + uuid.uuid4().hex
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
            os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(fd)
            try:
                os.unlink(temp, dir_fd=parent)
            except FileNotFoundError:
                pass

    def _usage(self, directory):
        total = 0
        for name in os.listdir(directory):
            st = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                with self._directory(directory, name) as child:
                    total += self._usage(child)
            elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
                total += st.st_size
            else:
                fail("unsafe_path", "Unexpected link or special file in storage")
        return total

    @staticmethod
    def _id(value, prefix):
        if not isinstance(value, str) or not ID.fullmatch(value) or not value.startswith(prefix + "_"):
            fail("invalid_argument", "Invalid opaque ID")

    def _response(self, operation):
        try:
            return bounded(operation())
        except CatalogError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": str(exc)[:500], **getattr(exc, "details", {})}}
        except FileNotFoundError:
            return {"ok": False, "error": {"code": "not_found", "message": "Project or artifact not found"}}
        except OSError as exc:
            code = "quota_exceeded" if exc.errno in (errno.ENOSPC, errno.EDQUOT) else "unsafe_path" if exc.errno in (errno.ELOOP, errno.ENOTDIR) else "storage_error"
            return {"ok": False, "error": {"code": code, "message": "Storage operation failed; existing files retained. Publication may have completed if the failure occurred after rename."}}
        except (ValueError, KeyError, TypeError, RecursionError):
            return {"ok": False, "error": {"code": "invalid_argument", "message": "Invalid document or stored metadata"}}

    def save_project(self, **arguments):
        def run():
            raw = validate_save_arguments(arguments)
            sketch_info = None
            if 'sketch' in arguments:
                from .authoring import sketch_document
                if self.catalog is None:
                    from .catalog import Catalog
                    self.catalog = Catalog.from_snapshot(Path(__file__).with_name('catalog.snapshot.json'))
                if 'project_id' not in arguments:
                    doc, board_id, name = sketch_document(self.catalog, arguments)
                    raw = validate_document(doc)
                    sketch_info = (board_id, name)
            updating = "project_id" in arguments
            project_id = arguments.get("project_id")
            if not updating:
                project_id = "p_" + uuid.uuid4().hex
            with self._locked(True) as root:
                if not updating and self._usage(root) + len(raw) + 1024 > self.max_storage_bytes:
                    fail("quota_exceeded", "Storage quota reached; existing files retained")
                with self._directory(root, "projects", True) as projects, self._directory(root, "artifacts", True) as artifacts:
                    with self._directory(projects, project_id, not updating) as project, self._directory(project, "versions", not updating) as versions:
                        if updating:
                            head = json.loads(self._read(project, "head.json", 4096))
                            if not isinstance(head.get("version"), str) or not VERSION.fullmatch(head["version"]):
                                fail("integrity_error", "Invalid project head")
                            if head["version"] != arguments["expected_version"]:
                                fail("version_conflict", "Project head differs from expected_version")
                            if "changes" in arguments or 'sketch' in arguments:
                                old = self._read(versions, head["version"] + ".vlx")
                                if hashlib.sha256(old).hexdigest() != head["version"]:
                                    fail("integrity_error", "Snapshot hash mismatch")
                                if 'sketch' in arguments:
                                    doc, board_id, name = sketch_document(self.catalog, arguments, json.loads(old))
                                    raw = validate_document(doc)
                                    sketch_info = (board_id, name)
                                else:
                                    raw = validate_document(patch(json.loads(old), arguments["changes"]))
                        version = hashlib.sha256(raw).hexdigest()
                        try:
                            previous = self._read(versions, version + ".vlx")
                        except FileNotFoundError:
                            previous = None
                        if previous is not None:
                            if previous != raw:
                                fail("integrity_error", "Immutable version content differs")
                            try:
                                meta = json.loads(self._read(versions, version + ".json", 4096))
                            except FileNotFoundError:
                                meta = None
                        else:
                            meta = None
                        if meta is None:
                            meta = {"artifact_id": "a_" + uuid.uuid4().hex, "project_id": project_id, "version": version,
                                    "sha256": version, "size_bytes": len(raw)}
                            metadata = canonical(meta)
                            if self._usage(root) + (len(raw) if previous is None else 0) + 2 * len(metadata) + len(canonical({"version": version})) > self.max_storage_bytes:
                                fail("quota_exceeded", "Storage quota reached; existing files retained")
                            self._publish(versions, version + ".vlx", raw)
                            self._publish(versions, version + ".json", metadata)
                        self._id(meta["artifact_id"], "a")
                        if meta != {"artifact_id": meta["artifact_id"], "project_id": project_id, "version": version, "sha256": version, "size_bytes": len(raw)}:
                            fail("integrity_error", "Invalid version manifest")
                        index = canonical(meta)
                        try:
                            existing_index = self._read(artifacts, meta["artifact_id"] + ".json", 4096)
                        except FileNotFoundError:
                            existing_index = None
                        if existing_index is None and self._usage(root) + len(index) + 100 > self.max_storage_bytes:
                            fail("quota_exceeded", "Storage quota reached; existing files retained")
                        self._publish(artifacts, meta["artifact_id"] + ".json", index)
                        self._publish(project, "head.json", canonical({"version": version}), replace=True)
                        result = {"ok": True, "project_id": project_id, "version": version, "content_sha256": version,
                                "project_artifact_id": meta["artifact_id"], "summary": "Native project snapshot saved", "download_url": None}
                        if sketch_info:
                            from .authoring import sketch_warnings
                            result.update(board_id=sketch_info[0], sketch_file=sketch_info[1], warnings=sketch_warnings(arguments['sketch'], sketch_info[1]))
                        return result
        return self._response(run)

    def read_artifact(self, **arguments):
        def run():
            if arguments.keys() - {"artifact_id", "offset", "length", "encoding"}:
                fail("invalid_argument", "Unknown artifact argument")
            artifact_id = arguments.get("artifact_id")
            self._id(artifact_id, "a")
            offset, length, encoding = arguments.get("offset", 0), arguments.get("length", 4096), arguments.get("encoding", "utf8")
            if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 12288 or encoding not in ("utf8", "base64"):
                fail("invalid_argument", "Invalid artifact slice")
            with self._locked(False) as root:
                with self._directory(root, "artifacts") as artifacts:
                    meta = json.loads(self._read(artifacts, artifact_id + ".json", 4096))
                self._id(meta["project_id"], "p")
                if not isinstance(meta["version"], str) or not VERSION.fullmatch(meta["version"]) or meta["artifact_id"] != artifact_id:
                    fail("integrity_error", "Invalid artifact mapping")
                kind = meta.get("kind", "project")
                if kind not in ("project", "check_report", "firmware", "build_log"):
                    fail("integrity_error", "Unsupported artifact kind")
                digest = meta["version"] if kind == "project" else meta.get("report_hash") if kind == "check_report" else meta.get("blob_hash")
                if not isinstance(digest, str) or not VERSION.fullmatch(digest):
                    fail("integrity_error", "Invalid artifact digest")
                if kind in ("firmware", "build_log"):
                    self._id(meta["build_id"], "b")
                    with self._directory(root, "builds") as builds, self._directory(builds, meta["build_id"]) as build, self._directory(build, "artifacts") as blobs:
                        job = json.loads(self._read(build, "job.json"))
                        if job["project_id"] != meta["project_id"] or job["version"] != meta["version"] or not any(a["id"] == artifact_id for a in job.get("artifacts", [])):
                            fail("integrity_error", "Artifact does not belong to this build")
                        if json.loads(self._read(blobs, digest + "." + kind + ".meta.json", 4096)) != meta:
                            fail("integrity_error", "Build artifact manifest differs")
                        raw = self._read(blobs, digest + "." + kind, 32 * 1024 * 1024 if kind == "firmware" else 1024 * 1024)
                else:
                    with self._directory(root, "projects") as projects, self._directory(projects, meta["project_id"]) as project, self._directory(project, "versions" if kind == "project" else "reports") as versions:
                        if json.loads(self._read(versions, digest + (".json" if kind == "project" else ".meta.json"), 4096)) != meta:
                            fail("integrity_error", "Artifact does not belong to this project version")
                        raw = self._read(versions, digest + (".vlx" if kind == "project" else ".json"))
                if hashlib.sha256(raw).hexdigest() != meta["sha256"] or meta["sha256"] != digest or len(raw) != meta["size_bytes"]:
                    fail("integrity_error", "Artifact size/hash mismatch")
                if offset > len(raw):
                    fail("invalid_argument", "Offset exceeds artifact size")
                end = min(len(raw), offset + length)
                if encoding == "utf8":
                    if offset < len(raw) and raw[offset] & 0xc0 == 0x80:
                        fail("invalid_argument", "Offset splits a UTF-8 character")
                    while end < len(raw) and raw[end] & 0xc0 == 0x80:
                        end -= 1
                    if end == offset and offset != len(raw):
                        fail("invalid_argument", "length cannot hold the next UTF-8 character")
                    data = raw[offset:end].decode("utf-8")
                else:
                    data = base64.b64encode(raw[offset:end]).decode("ascii")
                result = {"ok": True, "data": data, "offset": offset, "next_offset": end if end < len(raw) else None,
                          "total_bytes": len(raw), "sha256": meta["sha256"], "eof": end == len(raw), "truncated": end < len(raw), "encoding": encoding}
                if len(canonical(result)) > MAX_RESPONSE_BYTES:
                    # JSON escapes can double a UTF-8 slice. Return less than
                    # the requested upper bound while always making progress.
                    end = offset + (end - offset) // 2
                    while end < len(raw) and raw[end] & 0xc0 == 0x80:
                        end -= 1
                    result.update(data=raw[offset:end].decode("utf-8"), next_offset=end, eof=False, truncated=True)
                return result
        return self._response(run)

    def _build_blob(self, root, build, job, kind, raw):
        if kind not in ("firmware", "build_log") or not isinstance(raw, bytes):
            fail("invalid_argument", "Invalid build artifact")
        if len(raw) > (32 * 1024 * 1024 if kind == "firmware" else 1024 * 1024):
            fail("quota_exceeded", "Build artifact exceeds its byte quota")
        digest = hashlib.sha256(raw).hexdigest()
        with self._directory(build, "artifacts", True) as blobs, self._directory(root, "artifacts") as artifacts:
            name = digest + "." + kind
            try:
                meta = json.loads(self._read(blobs, name + ".meta.json", 4096))
            except FileNotFoundError:
                meta = {"kind": kind, "artifact_id": "a_" + uuid.uuid4().hex, "project_id": job["project_id"],
                        "version": job["version"], "build_id": job["build_id"], "blob_hash": digest, "sha256": digest, "size_bytes": len(raw)}
            self._id(meta["artifact_id"], "a")
            if meta != {"kind": kind, "artifact_id": meta["artifact_id"], "project_id": job["project_id"], "version": job["version"], "build_id": job["build_id"], "blob_hash": digest, "sha256": digest, "size_bytes": len(raw)}:
                fail("integrity_error", "Build artifact metadata differs")
            metadata = canonical(meta)
            if self._usage(root) + len(raw) + 2 * len(metadata) > self.max_storage_bytes:
                fail("quota_exceeded", "Storage quota reached; existing files retained")
            self._publish(blobs, name, raw)
            self._publish(blobs, name + ".meta.json", metadata)
            self._publish(artifacts, meta["artifact_id"] + ".json", metadata)
        return {"id": meta["artifact_id"], "kind": kind, "sha256": digest, "size_bytes": len(raw)}

    def _load_version(self, root, project_id, version):
        """Exact immutable snapshot only; deliberately never reads head.json."""
        self._id(project_id, "p")
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            fail("invalid_argument", "An exact version hash is required")
        with self._directory(root, "projects") as projects, self._directory(projects, project_id) as project, self._directory(project, "versions") as versions:
            raw = self._read(versions, version + ".vlx")
            meta = json.loads(self._read(versions, version + ".json", 4096))
        self._id(meta["artifact_id"], "a")
        if meta != {"artifact_id": meta["artifact_id"], "project_id": project_id, "version": version, "sha256": version, "size_bytes": len(raw)} or hashlib.sha256(raw).hexdigest() != version:
            fail("integrity_error", "Snapshot manifest/hash mismatch")
        with self._directory(root, "artifacts") as artifacts:
            if json.loads(self._read(artifacts, meta["artifact_id"] + ".json", 4096)) != meta:
                fail("integrity_error", "Snapshot artifact mapping differs")
        return json.loads(raw)

    def _store_report(self, project_id, version, report):
        raw = canonical(report)
        if len(raw) > MAX_PROJECT_BYTES:
            fail("quota_exceeded", "Complete check report exceeds 2 MiB; nothing was truncated")
        digest = hashlib.sha256(raw).hexdigest()
        with self._locked(True) as root:
            self._load_version(root, project_id, version)
            with self._directory(root, "projects") as projects, self._directory(projects, project_id) as project, self._directory(project, "reports", True) as reports, self._directory(root, "artifacts") as artifacts:
                try:
                    existing = self._read(reports, digest + ".json")
                except FileNotFoundError:
                    existing = None
                if existing is not None and existing != raw:
                    fail("integrity_error", "Report hash collision")
                try:
                    meta = json.loads(self._read(reports, digest + ".meta.json", 4096))
                except FileNotFoundError:
                    meta = {"kind": "check_report", "artifact_id": "a_" + uuid.uuid4().hex, "project_id": project_id,
                            "version": version, "report_hash": digest, "sha256": digest, "size_bytes": len(raw)}
                self._id(meta["artifact_id"], "a")
                if meta != {"kind": "check_report", "artifact_id": meta["artifact_id"], "project_id": project_id,
                            "version": version, "report_hash": digest, "sha256": digest, "size_bytes": len(raw)}:
                    fail("integrity_error", "Report manifest differs")
                metadata = canonical(meta)
                index_exists = False
                try:
                    index_exists = self._read(artifacts, meta["artifact_id"] + ".json", 4096) == metadata
                except FileNotFoundError:
                    pass
                if self._usage(root) + (len(raw) if existing is None else 0) + (0 if index_exists else 2 * len(metadata)) > self.max_storage_bytes:
                    fail("quota_exceeded", "Storage quota reached; existing files retained")
                self._publish(reports, digest + ".json", raw)
                self._publish(reports, digest + ".meta.json", metadata)
                self._publish(artifacts, meta["artifact_id"] + ".json", metadata)
        return meta
