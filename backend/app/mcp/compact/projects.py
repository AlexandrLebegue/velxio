"""Native project snapshots and bounded artifact reads; POSIX, stdlib only."""

from __future__ import annotations

import base64
import copy
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid

from .catalog import CatalogError, bounded
from .contracts import MAX_PROJECT_BYTES, MAX_RESPONSE_BYTES

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
ID = re.compile(r"^[pa]_[0-9a-f]{32}$")
VERSION = re.compile(r"^[0-9a-f]{64}$")
PATCH_ROOTS = {"name", "boards", "fileGroups", "folderGroups", "components", "wires", "activeBoardId"}


def fail(code, message):
    raise CatalogError(code, message)


def canonical(value):
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                fail("invalid_argument", "JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            fail("invalid_argument", "Only native JSON values are accepted")
    try:
        check(value)
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail("invalid_argument", "Document must contain finite, UTF-8 JSON values")


def text(value, maximum=200):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or re.search(r"[\x00-\x1f\x7f]", value):
        fail("invalid_argument", "Invalid string field")


def filename(value):
    text(value, 240)
    if len(value.encode("utf-8")) > 240 or "\\" in value or value.startswith("/") or re.search(r'[:*?"<>|]', value):
        fail("invalid_argument", "File names must be portable relative POSIX paths")
    for part in value.split("/"):
        if part in ("", ".", "..") or part.endswith((".", " ")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            fail("invalid_argument", "Unsafe or ambiguous file path")
    return unicodedata.normalize("NFC", value).casefold()


def validate_document(doc):
    if not isinstance(doc, dict):
        fail("invalid_argument", "document must be an object")
    required = {"format", "version", "boards", "fileGroups", "components", "wires", "activeBoardId"}
    if not required <= doc.keys() or doc.keys() - required - {"name", "exportedAt", "folderGroups"}:
        fail("invalid_argument", "Missing or unknown document fields")
    if doc["format"] != "velxio-project" or type(doc["version"]) is not int or doc["version"] != 1:
        fail("invalid_argument", "Expected native velxio-project format version 1")
    for key, maximum in (("name", 200), ("exportedAt", 80)):
        if key in doc:
            text(doc[key], maximum)
    for key, maximum in (("boards", 8), ("components", 512), ("wires", 1024)):
        if not isinstance(doc[key], list):
            fail("invalid_argument", key + " must be an array")
        if len(doc[key]) > maximum:
            fail("quota_exceeded", key + " count exceeds quota")
    groups = doc["fileGroups"]
    if not isinstance(groups, dict) or len(groups) > 128:
        fail("invalid_argument", "Invalid fileGroups")
    count = total = 0
    basenames = {}

    def file_set(items, binary=False, content_key="content"):
        nonlocal count, total
        if not isinstance(items, list):
            fail("invalid_argument", "File collection must be an array")
        seen, bases = set(), set()
        collision = False
        for item in items:
            if not isinstance(item, dict) or not {"name", content_key} <= item.keys():
                fail("invalid_argument", "Invalid file entry")
            normalized = filename(item["name"])
            if normalized in seen:
                fail("invalid_argument", "File path collision after normalization/casefold")
            if any(normalized.startswith(other + "/") or other.startswith(normalized + "/") for other in seen):
                fail("invalid_argument", "File and directory paths collide")
            seen.add(normalized)
            base = normalized.rsplit("/", 1)[-1]
            collision |= base in bases
            bases.add(base)
            content = item[content_key]
            if not isinstance(content, str):
                fail("invalid_argument", "File content must be a string")
            try:
                raw = base64.b64decode(content, validate=True) if binary else content.encode("utf-8")
            except (ValueError, UnicodeError):
                fail("invalid_argument", "Invalid file encoding")
            if not binary and len(raw) > 256 * 1024:
                fail("quota_exceeded", "Source file exceeds 256 KiB")
            count += 1
            total += len(raw)
            if count > 128 or total > MAX_PROJECT_BYTES:
                fail("quota_exceeded", "Project exceeds 128 files or 2 MiB decoded data")
        return collision

    for group, items in groups.items():
        text(group)
        basenames[group] = file_set(items)
    ids, board_ids = set(), set()
    for board in doc["boards"]:
        if not isinstance(board, dict):
            fail("invalid_argument", "Invalid board")
        for field in ("id", "boardKind", "activeFileGroupId"):
            text(board.get(field))
        if board["activeFileGroupId"] not in groups:
            fail("invalid_argument", "Board file group does not exist")
        if board.get("languageMode", "arduino") not in ("arduino", "micropython", "espidf"):
            fail("invalid_argument", "Unknown language mode")
        if board["boardKind"].startswith(("esp32", "xiao-esp32", "arduino-nano-esp32", "wemos-lolin32", "aitewinrobot-esp32")) or board.get("languageMode") == "espidf":
            if basenames[board["activeFileGroupId"]]:
                fail("invalid_argument", "ESP-IDF basename collision")
        for key, content_key in (("spiffsFiles", "contentB64"), ("sdFiles", "contentB64")):
            if key in board:
                file_set(board[key], True, content_key)
        if board["id"] in ids:
            fail("invalid_argument", "Duplicate object ID")
        ids.add(board["id"])
        board_ids.add(board["id"])
    for component in doc["components"]:
        if not isinstance(component, dict) or not isinstance(component.get("properties"), dict):
            fail("invalid_argument", "Invalid component")
        text(component.get("id"))
        text(component.get("metadataId"))
        if component["id"] in ids:
            fail("invalid_argument", "Duplicate object ID")
        ids.add(component["id"])
        if "sdFiles" in component["properties"]:
            file_set(component["properties"]["sdFiles"], True, "contentB64")
        if "sourceC" in component["properties"]:
            content = component["properties"]["sourceC"]
            if not isinstance(content, str):
                fail("invalid_argument", "Embedded sourceC must be text")
            if content:
                file_set([{"name": "embedded-source.c", "content": content}])
    for item in [*doc["boards"], *doc["components"]]:
        if any(type(item.get(axis)) not in (int, float) for axis in ("x", "y")):
            fail("invalid_argument", "Object coordinates must be numbers")
    wire_ids = set()
    for wire in doc["wires"]:
        if not isinstance(wire, dict):
            fail("invalid_argument", "Invalid wire")
        text(wire.get("id"))
        if wire["id"] in wire_ids:
            fail("invalid_argument", "Duplicate wire ID")
        wire_ids.add(wire["id"])
        for key in ("start", "end"):
            endpoint = wire.get(key)
            if not isinstance(endpoint, dict):
                fail("invalid_argument", "Invalid wire endpoint")
            text(endpoint.get("componentId"))
            text(endpoint.get("pinName"))
            if endpoint["componentId"] not in ids:
                fail("invalid_argument", "Wire references a missing object")
            for axis in ("x", "y"):
                if axis in endpoint and type(endpoint[axis]) not in (int, float):
                    fail("invalid_argument", "Wire coordinates must be numbers")
        if "color" in wire:
            text(wire["color"], 100)
        if "waypoints" in wire:
            if not isinstance(wire["waypoints"], list) or any(not isinstance(p, dict) or any(type(p.get(axis)) not in (int, float) for axis in ("x", "y")) for p in wire["waypoints"]):
                fail("invalid_argument", "Invalid wire waypoints")
    if doc["activeBoardId"] is not None and doc["activeBoardId"] not in board_ids:
        fail("invalid_argument", "Active board does not exist")
    folders = doc.get("folderGroups", {})
    if not isinstance(folders, dict):
        fail("invalid_argument", "Invalid folderGroups")
    for group, names in folders.items():
        if group not in groups or not isinstance(names, list):
            fail("invalid_argument", "Invalid folder group")
        for name in names:
            filename(name)
    raw = canonical(doc)
    if len(raw) > MAX_PROJECT_BYTES:
        fail("quota_exceeded", "Serialized native project exceeds 2 MiB")
    return raw


def patch(doc, changes):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 128:
        fail("invalid_argument", "changes must contain 1..128 operations")
    result = copy.deepcopy(doc)
    for change in changes:
        if not isinstance(change, dict) or change.keys() - {"op", "path", "value"}:
            fail("invalid_argument", "Invalid patch operation")
        op, pointer = change.get("op"), change.get("path")
        if op not in ("set", "remove") or (op == "set") != ("value" in change):
            fail("invalid_argument", "set requires value; remove forbids value")
        if not isinstance(pointer, str) or not pointer.startswith("/") or len(pointer) > 512 or re.search(r"~(?![01])", pointer):
            fail("invalid_argument", "Invalid RFC6901 pointer")
        tokens = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
        if tokens[0] not in PATCH_ROOTS:
            fail("invalid_argument", "Patch root is not allowed")
        parent = result
        for i, token in enumerate(tokens):
            last = i == len(tokens) - 1
            if isinstance(parent, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", token) or int(token) >= len(parent):
                    fail("invalid_argument", "Patch array index must exist")
                key = int(token)
            elif isinstance(parent, dict):
                key = token
                if (not last or op == "remove") and key not in parent:
                    fail("invalid_argument", "Patch path does not exist")
            else:
                fail("invalid_argument", "Patch path traverses a scalar")
            if last:
                if op == "remove":
                    del parent[key]
                else:
                    parent[key] = copy.deepcopy(change["value"])
            else:
                parent = parent[key]
    return result


class ProjectStore:
    def __init__(self, root="/app/data/mcp-compact", *, max_storage_bytes=256 * 1024 * 1024):
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
            old = self._read(parent, name)
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
            return {"ok": False, "error": {"code": exc.code, "message": str(exc)[:500]}}
        except FileNotFoundError:
            return {"ok": False, "error": {"code": "not_found", "message": "Project or artifact not found"}}
        except OSError as exc:
            code = "quota_exceeded" if exc.errno in (errno.ENOSPC, errno.EDQUOT) else "unsafe_path" if exc.errno in (errno.ELOOP, errno.ENOTDIR) else "storage_error"
            return {"ok": False, "error": {"code": code, "message": "Storage operation failed; existing files retained. Publication may have completed if the failure occurred after rename."}}
        except (ValueError, KeyError, TypeError, RecursionError):
            return {"ok": False, "error": {"code": "invalid_argument", "message": "Invalid document or stored metadata"}}

    def save_project(self, **arguments):
        def run():
            if arguments.keys() - {"document", "changes", "project_id", "expected_version"}:
                fail("invalid_argument", "Unknown save argument")
            updating = "project_id" in arguments
            if ("expected_version" in arguments) != updating or ("document" in arguments) == ("changes" in arguments) or ("changes" in arguments and not updating):
                fail("invalid_argument", "Updates require project_id, expected_version and exactly one of document/changes")
            if len(canonical(arguments)) > MAX_PROJECT_BYTES + 16384:
                fail("quota_exceeded", "Save request exceeds quota")
            project_id = arguments.get("project_id")
            if updating:
                self._id(project_id, "p")
                if not isinstance(arguments["expected_version"], str) or not VERSION.fullmatch(arguments["expected_version"]):
                    fail("invalid_argument", "Invalid expected_version")
            else:
                project_id = "p_" + uuid.uuid4().hex
            # Validate snapshots before creating any project directory.
            if "document" in arguments:
                raw = validate_document(arguments["document"])
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
                            if "changes" in arguments:
                                old = self._read(versions, head["version"] + ".vlx")
                                if hashlib.sha256(old).hexdigest() != head["version"]:
                                    fail("integrity_error", "Snapshot hash mismatch")
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
                        return {"ok": True, "project_id": project_id, "version": version, "content_sha256": version,
                                "project_artifact_id": meta["artifact_id"], "summary": "Native project snapshot saved", "download_url": None}
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
                with self._directory(root, "projects") as projects, self._directory(projects, meta["project_id"]) as project, self._directory(project, "versions") as versions:
                    if json.loads(self._read(versions, meta["version"] + ".json", 4096)) != meta:
                        fail("integrity_error", "Artifact does not belong to this project version")
                    raw = self._read(versions, meta["version"] + ".vlx")
                if hashlib.sha256(raw).hexdigest() != meta["sha256"] or meta["sha256"] != meta["version"] or len(raw) != meta["size_bytes"]:
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
