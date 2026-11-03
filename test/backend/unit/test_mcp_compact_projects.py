"""Temporary-root stdlib tests; no services, compiler, network or /app/data."""

import base64
import copy
import errno
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.mcp.compact import ProjectStore
from app.mcp.compact.projects import canonical


def document():
    return {"format": "velxio-project", "version": 1, "exportedAt": "2026-11-03T00:00:00Z", "name": "é🧪",
            "boards": [{"id": "esp", "boardKind": "esp32", "x": 2, "y": -3, "rotation": 90,
                        "activeFileGroupId": "g/a~b", "languageMode": "espidf", "libraries": ["GxEPD2"],
                        "boardOptions": {"flashSize": "8MB", "future": {"keep": True}},
                        "spiffsFiles": [{"name": "image.bin", "contentB64": "AQID", "size": 3}],
                        "sdFiles": [{"name": "sd.bin", "contentB64": "AA=="}]}],
            "fileGroups": {"g/a~b": [{"name": "main.c", "content": "void app_main() {}\n"}]},
            "folderGroups": {"g/a~b": ["empty/folder"]},
            "components": [{"id": "epd", "metadataId": "epaper-1in54-bw", "x": 30, "y": 70,
                            "properties": {"panelKind": "epaper-1in54-bw", "refreshMs": 50, "future": [1, 2]}}],
            "wires": [{"id": "w", "start": {"componentId": "esp", "pinName": "18", "x": 2, "y": 3},
                       "end": {"componentId": "epd", "pinName": "SCK", "x": 30, "y": 70},
                       "color": "#abcdef", "waypoints": [{"x": 12, "y": 15}], "bb": False}],
            "activeBoardId": "esp"}


def race_writer(root, project_id, expected, name, barrier, queue):
    store = ProjectStore(root)
    barrier.wait(timeout=10)
    queue.put(store.save_project(project_id=project_id, expected_version=expected,
                                changes=[{"op": "set", "path": "/name", "value": name}]))


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compact-project-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "store"
        self.store = ProjectStore(self.root)

    def save(self, doc=None):
        result = self.store.save_project(document=document() if doc is None else doc)
        self.assertTrue(result["ok"], result)
        return result

    def read_all(self, artifact, encoding="utf8", length=97):
        out, offset = bytearray(), 0
        while True:
            result = self.store.read_artifact(artifact_id=artifact, offset=offset, length=length, encoding=encoding)
            self.assertTrue(result["ok"], result)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 24 * 1024)
            out.extend(base64.b64decode(result["data"]) if encoding == "base64" else result["data"].encode())
            if result["eof"]:
                self.assertIsNone(result["next_offset"])
                break
            self.assertGreater(result["next_offset"], offset)
            offset = result["next_offset"]
        self.assertEqual(len(out), result["total_bytes"])
        self.assertEqual(hashlib.sha256(out).hexdigest(), result["sha256"])
        return bytes(out)

    def test_native_roundtrip_restart_and_all_ui_fields(self):
        original = document()
        saved = self.save(original)
        self.assertIsNone(saved["download_url"])
        self.store = ProjectStore(self.root)
        raw = self.read_all(saved["project_artifact_id"])
        self.assertEqual(json.loads(raw), original)
        self.assertEqual(saved["version"], hashlib.sha256(canonical(original)).hexdigest())
        self.assertEqual(original, document())

    def test_snapshot_cas_immutable_history_and_idempotence(self):
        first = self.save()
        same = self.store.save_project(document=dict(reversed(list(document().items()))), project_id=first["project_id"], expected_version=first["version"])
        self.assertEqual(same, first)
        changed = document()
        changed["components"][0]["properties"]["refreshMs"] = 80
        second = self.store.save_project(document=changed, project_id=first["project_id"], expected_version=first["version"])
        self.assertTrue(second["ok"])
        self.assertNotEqual(first["version"], second["version"])
        self.assertEqual(json.loads(self.read_all(first["project_artifact_id"])), document())
        self.assertEqual(json.loads(self.read_all(second["project_artifact_id"])), changed)
        stale = self.store.save_project(document=changed, project_id=first["project_id"], expected_version=first["version"])
        self.assertEqual(stale["error"]["code"], "version_conflict")

    def test_two_processes_cas_exactly_one_winner(self):
        saved = self.save()
        context = multiprocessing.get_context("fork")
        queue, barrier = context.Queue(), context.Barrier(2)
        processes = [context.Process(target=race_writer, args=(str(self.root), saved["project_id"], saved["version"], name, barrier, queue)) for name in ("one", "two")]
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
        results = [queue.get(timeout=2), queue.get(timeout=2)]
        self.assertEqual(sum(result["ok"] for result in results), 1)
        self.assertEqual(next(result for result in results if not result["ok"])["error"]["code"], "version_conflict")

    def test_rfc6901_escaped_paths_and_result_validation(self):
        saved = self.save()
        operations = [{"op": "set", "path": "/fileGroups/g~1a~0b/0/content", "value": "new code"},
                      {"op": "set", "path": "/components/0/properties/new~1key", "value": {"retain": True}},
                      {"op": "remove", "path": "/folderGroups"}]
        result = self.store.save_project(project_id=saved["project_id"], expected_version=saved["version"], changes=operations)
        self.assertTrue(result["ok"], result)
        restored = json.loads(self.read_all(result["project_artifact_id"]))
        self.assertEqual(restored["fileGroups"]["g/a~b"][0]["content"], "new code")
        self.assertEqual(restored["components"][0]["properties"]["new/key"], {"retain": True})
        self.assertNotIn("folderGroups", restored)
        bad = self.store.save_project(project_id=result["project_id"], expected_version=result["version"], changes=[{"op": "remove", "path": "/boards/0"}])
        self.assertFalse(bad["ok"])

    def test_patch_allowlist_and_invalid_operations(self):
        saved = self.save()
        for change in ({"op": "set", "path": "/version", "value": 2}, {"op": "set", "path": "/name~2", "value": "x"},
                       {"op": "set", "path": "/boards/-", "value": {}}, {"op": "set", "path": "/boards/01", "value": {}},
                       {"op": "remove", "path": "/missing"}, {"op": "remove", "path": "/name", "value": 1},
                       {"op": "set", "path": "/name"}, {"op": "add", "path": "/name", "value": "x"}):
            with self.subTest(change=change):
                result = self.store.save_project(project_id=saved["project_id"], expected_version=saved["version"], changes=[change])
                self.assertFalse(result["ok"])
        self.assertEqual(json.loads(self.read_all(saved["project_artifact_id"])), document())

    def test_atomic_failure_before_head_and_retry_recovery(self):
        saved = self.save()
        original_publish = self.store._publish
        for failed_name in ("head.json", "manifest"):
            old_document = json.loads(self.read_all(saved["project_artifact_id"]))
            changed = document()
            changed["name"] = failed_name
            def failing(fd, name, raw, **kwargs):
                if name == failed_name or (failed_name == "manifest" and name.endswith(".json") and name != "head.json"):
                    raise OSError("injected pre-publication failure")
                return original_publish(fd, name, raw, **kwargs)
            with patch.object(self.store, "_publish", side_effect=failing):
                failed = self.store.save_project(project_id=saved["project_id"], expected_version=saved["version"], document=changed)
            self.assertFalse(failed["ok"])
            head = json.loads((self.root / "projects" / saved["project_id"] / "head.json").read_bytes())
            self.assertEqual(head["version"], saved["version"])
            self.assertEqual(json.loads(self.read_all(saved["project_artifact_id"])), old_document)
            recovered = ProjectStore(self.root).save_project(project_id=saved["project_id"], expected_version=saved["version"], document=changed)
            self.assertTrue(recovered["ok"], recovered)
            self.assertEqual(json.loads(self.read_all(recovered["project_artifact_id"])), changed)
            saved = recovered

    def test_publication_fsync_and_no_temp_files_after_success(self):
        with patch("app.mcp.compact.projects.os.fsync", wraps=os.fsync) as fsync:
            self.save()
            self.assertGreaterEqual(fsync.call_count, 8)
        self.assertFalse(list(self.root.rglob(".tmp-*")))

    def test_disk_full_is_explicit_and_preserves_old_snapshot(self):
        saved = self.save()
        with patch.object(self.store, "_publish", side_effect=OSError(errno.ENOSPC, "full")):
            result = self.store.save_project(project_id=saved["project_id"], expected_version=saved["version"], changes=[{"op": "set", "path": "/name", "value": "new"}])
        self.assertEqual(result["error"]["code"], "quota_exceeded")
        self.assertEqual(json.loads(self.read_all(saved["project_artifact_id"])), document())

    def test_error_after_head_rename_never_leaves_partial_head(self):
        saved = self.save()
        publish = self.store._publish
        def after_commit(fd, name, raw, **kwargs):
            publish(fd, name, raw, **kwargs)
            if name == "head.json":
                raise OSError(errno.EIO, "directory durability uncertain")
        with patch.object(self.store, "_publish", side_effect=after_commit):
            result = self.store.save_project(project_id=saved["project_id"], expected_version=saved["version"], changes=[{"op": "set", "path": "/name", "value": "committed"}])
        self.assertEqual(result["error"]["code"], "storage_error")
        project = self.root / "projects" / saved["project_id"]
        head = json.loads((project / "head.json").read_bytes())
        meta = json.loads((project / "versions" / (head["version"] + ".json")).read_bytes())
        self.assertEqual(json.loads(self.read_all(meta["artifact_id"]))["name"], "committed")
        self.assertEqual(json.loads(self.read_all(saved["project_artifact_id"])), document())

    def test_source_file_names_and_collisions(self):
        for name in ("/etc/passwd", "C:/data.c", "C:data.c", "\\\\server\\share", "../x.c", "x/../a.c", "./a.c", "x//a.c", "x\\a.c", "a\x00.c", "a/", "CON.c", "x./a.c"):
            doc = document()
            doc["fileGroups"]["g/a~b"][0]["name"] = name
            with self.subTest(name=name):
                self.assertFalse(self.store.save_project(document=doc)["ok"])
        for names in (("A.c", "a.c"), ("src/a.c", "other/A.c"), ("é.c", "e\u0301.c")):
            doc = document()
            doc["fileGroups"]["g/a~b"] = [{"name": name, "content": "x"} for name in names]
            self.assertFalse(self.store.save_project(document=doc)["ok"])

    def test_document_quotas_and_no_loss_on_storage_quota(self):
        for count, size in ((129, 1), (1, 256 * 1024 + 1), (9, 256 * 1024)):
            doc = document()
            doc["fileGroups"]["g/a~b"] = [{"name": str(i) + ".c", "content": "x" * size} for i in range(count)]
            self.assertEqual(self.store.save_project(document=doc)["error"]["code"], "quota_exceeded")
        saved = self.save()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        limited = ProjectStore(self.root, max_storage_bytes=1)
        result = limited.save_project(project_id=saved["project_id"], expected_version=saved["version"], changes=[{"op": "set", "path": "/name", "value": "quota"}])
        self.assertEqual(result["error"]["code"], "quota_exceeded")
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_arguments_and_result_validation(self):
        for args in ({}, {"document": document(), "project_id": "p_" + "a" * 32},
                     {"changes": []}, {"document": document(), "changes": []},
                     {"document": document(), "path": "/tmp/x"}, {"document": {}}):
            self.assertFalse(self.store.save_project(**args)["ok"])
        for change in (lambda d: d.update(version=True), lambda d: d["boards"][0].update(x=float("nan")),
                       lambda d: d["components"].append(copy.deepcopy(d["components"][0])),
                       lambda d: d["wires"][0]["end"].update(componentId="missing")):
            doc = document()
            change(doc)
            self.assertFalse(self.store.save_project(document=doc)["ok"])

    def test_read_slices_utf8_base64_and_boundaries(self):
        saved = self.save()
        aid = saved["project_artifact_id"]
        raw = self.read_all(aid, "base64", 7)
        self.assertEqual(self.read_all(aid, "utf8", 7), raw)
        position = raw.index("🧪".encode())
        self.assertFalse(self.store.read_artifact(artifact_id=aid, offset=position + 1)["ok"])
        self.assertFalse(self.store.read_artifact(artifact_id=aid, offset=position, length=3)["ok"])
        full = self.store.read_artifact(artifact_id=aid, offset=position, length=4)
        self.assertEqual(full["data"], "🧪")
        eof = self.store.read_artifact(artifact_id=aid, offset=len(raw))
        self.assertTrue(eof["eof"])
        self.assertEqual(eof["data"], "")
        for args in ({"length": 12289}, {"length": 0}, {"offset": -1}, {"offset": len(raw) + 1}, {"length": True}, {"encoding": "hex"}, {"path": "/etc/passwd"}):
            self.assertFalse(self.store.read_artifact(artifact_id=aid, **args)["ok"])

    def test_maximum_slice_is_bounded(self):
        doc = document()
        doc["fileGroups"]["g/a~b"][0]["content"] = "é" * 20000
        saved = self.save(doc)
        for encoding in ("utf8", "base64"):
            result = self.store.read_artifact(artifact_id=saved["project_artifact_id"], length=12288, encoding=encoding)
            self.assertTrue(result["ok"])
            self.assertTrue(result["truncated"])
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 24 * 1024)

    def test_json_escape_expansion_still_returns_progress_under_24k(self):
        doc = document()
        doc["fileGroups"]["g/a~b"][0]["content"] = "\\" * 20000
        saved = self.save(doc)
        result = self.store.read_artifact(artifact_id=saved["project_artifact_id"], offset=2000, length=12288)
        self.assertTrue(result["ok"], result)
        self.assertGreater(result["next_offset"], 2000)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()), 24 * 1024)

    def test_embedded_sources_assets_and_json_values_are_validated(self):
        doc = document()
        doc["components"][0]["properties"]["sourceC"] = "x" * (256 * 1024 + 1)
        self.assertEqual(self.store.save_project(document=doc)["error"]["code"], "quota_exceeded")
        for bad in ("../asset", "C:/asset", "a\\b"):
            doc = document()
            doc["boards"][0]["spiffsFiles"][0]["name"] = bad
            self.assertFalse(self.store.save_project(document=doc)["ok"])
        doc = document()
        doc["boards"][0]["sdFiles"][0]["contentB64"] = "!!!!"
        self.assertFalse(self.store.save_project(document=doc)["ok"])
        doc = document()
        doc["components"][0]["properties"] = {1: "would lose key type"}
        self.assertFalse(self.store.save_project(document=doc)["ok"])

    def test_root_replacement_and_symlink_lock_or_index_rejected(self):
        saved = self.save()
        old = self.root.with_name("original")
        self.root.rename(old)
        self.root.mkdir()
        self.assertFalse(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])
        self.root.rmdir()
        old.rename(self.root)
        sentinel = Path(self.temp.name) / "sentinel"
        sentinel.write_text("retained")
        for target in (self.root / ".lock", self.root / "artifacts" / (saved["project_artifact_id"] + ".json")):
            original = target.read_bytes()
            target.unlink()
            target.symlink_to(sentinel)
            self.assertFalse(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])
            self.assertEqual(sentinel.read_text(), "retained")
            target.unlink()
            target.write_bytes(original)

    def test_project_and_artifact_isolation_and_traversal(self):
        first, second = self.save(), self.save()
        self.assertNotEqual(first["project_id"], second["project_id"])
        self.assertNotEqual(first["project_artifact_id"], second["project_artifact_id"])
        for bad in ("../x", "/etc/passwd", "C:/x", "a_" + "a" * 31, first["project_id"]):
            self.assertEqual(self.store.read_artifact(artifact_id=bad)["error"]["code"], "invalid_argument")
        index = self.root / "artifacts" / (first["project_artifact_id"] + ".json")
        meta = json.loads(index.read_bytes())
        meta["project_id"] = second["project_id"]
        index.write_bytes(canonical(meta))
        self.assertEqual(self.store.read_artifact(artifact_id=first["project_artifact_id"])["error"]["code"], "integrity_error")

    def test_symlink_root_and_ancestors_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = Path(self.temp.name) / "link"
        link.symlink_to(outside, target_is_directory=True)
        for root in (link, link / "child"):
            with self.assertRaisesRegex(ValueError, "safe directory"):
                ProjectStore(root)
        self.assertFalse((outside / "child").exists())

    def test_symlink_internal_file_and_parent_rejected_without_touching_target(self):
        saved = self.save()
        outside = Path(self.temp.name) / "outside"
        outside.write_text("untouched")
        snapshot = self.root / "projects" / saved["project_id"] / "versions" / (saved["version"] + ".vlx")
        original = snapshot.read_bytes()
        snapshot.unlink()
        snapshot.symlink_to(outside)
        self.assertFalse(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])
        self.assertFalse(self.store.save_project(document=document(), project_id=saved["project_id"], expected_version=saved["version"])["ok"])
        self.assertEqual(outside.read_text(), "untouched")
        snapshot.unlink()
        snapshot.write_bytes(original)
        project = snapshot.parent.parent
        moved = project.with_name("moved")
        project.rename(moved)
        project.symlink_to(moved, target_is_directory=True)
        self.assertFalse(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])

    def test_hardlinks_and_corrupt_snapshot_rejected(self):
        saved = self.save()
        snapshot = self.root / "projects" / saved["project_id"] / "versions" / (saved["version"] + ".vlx")
        link = Path(self.temp.name) / "hardlink"
        os.link(snapshot, link)
        self.assertFalse(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])
        link.unlink()
        snapshot.write_bytes(b"{}")
        self.assertEqual(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["error"]["code"], "integrity_error")


if __name__ == "__main__":
    unittest.main()
