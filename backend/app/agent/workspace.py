from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from app.mcp.compact.projects import validate_document, patch
from .settings import AgentError, private_json


def normalize_document(document):
    value = copy.deepcopy(document)
    for wire in value.get("wires", []):
        if isinstance(wire, dict):
            wire.setdefault("color", "#00c853")
            wire.setdefault("waypoints", [])
    return value


def project_revision(document):
    value = normalize_document({key: item for key, item in document.items() if key not in ("exportedAt", "name")})
    for board in value.get("boards", []):
        board.pop("serialBaudRate", None)
    for wire in value.get("wires", []):
        wire.pop("signalType", None)
        for endpoint in (wire.get("start", {}), wire.get("end", {})):
            endpoint.pop("x", None)
            endpoint.pop("y", None)
    for component in value.get("components", []):
        if component.get("metadataId") in ("led", "rgb-led", "buzzer", "relay-module"):
            component.get("properties", {}).pop("state", None)
            if isinstance(component.get("properties", {}).get("value"), bool):
                component["properties"].pop("value")
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def checked_document(document):
    document = copy.deepcopy(document)
    if len(json.dumps(document, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise AgentError("quota_exceeded", "Project exceeds 2 MiB")
    try:
        validate_document(document)
    except ValueError as exc:
        raise AgentError("invalid_project", str(exc)) from exc
    return normalize_document(document)


class Workspace:
    """A staging directory plus immutable .vlx revisions; no arbitrary client paths."""
    def __init__(self, root: Path, document):
        self.root = root
        self.work = root / "work"
        self.document = checked_document(document)
        self.revision = project_revision(self.document)
        self.groups = {group: f"group-{index + 1}" for index, group in enumerate(self.document["fileGroups"])}
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.materialize()
        self.persist()

    def persist(self):
        revisions = self.root / "revisions"
        target = revisions / f"{self.revision}.vlx"
        if not target.exists():
            if revisions.exists() and sum(p.stat().st_size for p in revisions.iterdir()) > 32 * 1024 * 1024:
                raise AgentError("quota_exceeded", "Workspace snapshot quota reached; export the project before starting a new session")
            private_json(target, self.document)
        private_json(self.root / ".velxio.json", {"id": self.root.name, "revision": self.revision, "groups": self.groups})

    def materialize(self):
        expected = set()
        for group, files in self.document["fileGroups"].items():
            directory = self.work / self.groups[group]
            directory.mkdir(exist_ok=True)
            for item in files:
                relative = self.safe_name(item["name"])
                target = directory / relative
                expected.add(target)
                self.no_links(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(item["content"])
        for target in self.work.rglob("*"):
            if target.is_symlink():
                raise AgentError("invalid_path", "Workspace symlinks are not supported")
            if target.is_file() and target not in expected:
                target.unlink()
        # A rejected starter can roll back to zero groups. Do not leave an
        # empty generated group behind: capture would treat it as an unknown path.
        group_dirs = {self.work / name for name in self.groups.values()}
        for target in sorted(self.work.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if target.is_dir() and target not in group_dirs and not any(target.iterdir()):
                target.rmdir()

    @staticmethod
    def safe_name(name):
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or any(p in ("..", ".") or p.startswith(".") for p in name.split("/")):
            raise AgentError("invalid_path", "Source filenames must be relative, without hidden or parent segments")
        return path

    def no_links(self, target):
        current = target
        while current != self.work:
            if current.is_symlink():
                raise AgentError("invalid_path", "Workspace symlinks are not supported")
            current = current.parent

    def capture(self):
        document = copy.deepcopy(self.document)
        for entry in self.work.iterdir():
            if entry.name not in self.groups.values() or not entry.is_dir() or entry.is_symlink():
                raise AgentError("invalid_path", "Keep project files inside the generated group directories")
        total = 0
        count = 0
        for group, directory in self.groups.items():
            files = []
            base = self.work / directory
            self.no_links(base)
            for target in sorted(base.rglob("*")):
                self.no_links(target)
                if not target.is_file():
                    continue
                name = target.relative_to(base).as_posix()
                self.safe_name(name)
                size = target.stat().st_size
                count += 1
                total += size
                if size > 262144 or count > 128 or total > 2 * 1024 * 1024:
                    raise AgentError("quota_exceeded", "Sources exceed the workspace limits")
                with os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW), "r", encoding="utf-8") as stream:
                    content = stream.read(262145)
                files.append({"name": name, "content": content})
            document["fileGroups"][group] = files
        return checked_document(document)

    def commit(self, document=None):
        value = checked_document(document) if document is not None else self.capture()
        previous = self.document, self.revision
        self.document, self.revision = value, project_revision(value)
        try:
            self.persist()
        except Exception:
            self.document, self.revision = previous
            raise
        return self.revision

    def sync(self, document, expected_revision):
        if expected_revision != self.revision:
            raise AgentError("revision_conflict", "The project changed; keep your local edits and reconnect the conversation", 409)
        value = checked_document(document)
        if set(value["fileGroups"]) != set(self.groups):
            self.groups = {group: f"group-{index + 1}" for index, group in enumerate(value["fileGroups"])}
        self.commit(value)
        self.materialize()

    def update_circuit(self, changes):
        self.commit(self.circuit_candidate(changes))

    def circuit_candidate(self, changes):
        if not changes or len(changes) > 128 or any(not change.get("path", "").startswith(("/components/", "/wires/")) and change.get("path") not in ("/components", "/wires") for change in changes):
            raise AgentError("invalid_argument", "Circuit changes must address components or wires")
        return checked_document(patch(self.capture(), changes))

    def describe(self):
        return {"revision": self.revision, "groups": self.groups, "document": self.document}
