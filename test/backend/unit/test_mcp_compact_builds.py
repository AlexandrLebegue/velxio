"""CONTROLLED TEST DOUBLES ONLY. Never invokes a compiler, installer or HTTP."""

import asyncio
import base64
from contextlib import asynccontextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))
from app.mcp.compact import BuildService, Catalog, LibraryInventory, OwnerQueueAdapter, ProjectChecker, ProjectStore, ToolchainInventory
from app.mcp.compact.projects import canonical
from test_mcp_compact_projects import document


class ControlledGate:
    def __init__(self):
        self.entered = 0
        self.open = asyncio.Event()
        self.open.set()

    @asynccontextmanager
    async def slot(self, **arguments):
        await self.open.wait()
        self.entered += 1
        yield


class BuildTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.from_repository(ROOT)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compact-build-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "store")
        self.proofs = self.root / "proofs"
        self.proofs.mkdir()
        library = self.proofs / "library.properties"
        library.write_text("name=GxEPD2\nversion=1.6.0\n")
        self.libs = LibraryInventory(str(self.proofs), {"GxEPD2": {"path": library.name, "sha256": hashlib.sha256(library.read_bytes()).hexdigest()}}, complete=True)
        binary = self.proofs / "CONTROLLED_FAKE_COMPILER.txt"
        binary.write_text("This is not executable and not a compiler")
        self.toolchain_doc = {"kind": "toolchain", "name": "esp32:esp32:esp32|espidf", "version": "CONTROLLED-TEST-1",
                              "test_only": True, "members": [{"path": binary.name, "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}]}
        manifest = self.proofs / "toolchain.json"
        manifest.write_bytes(canonical(self.toolchain_doc))
        self.tools = ToolchainInventory(str(self.proofs), {self.toolchain_doc["name"]: {"path": manifest.name, "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}}, complete=True)
        self.checker = ProjectChecker(self.store, self.catalog, inventory=self.libs)
        self.gate = ControlledGate()
        self.requests = []
        self.output = {"success": True, "firmware": b"\x00\xffCONTROLLED FAKE FIRMWARE\x01", "firmware_type": "bin"}
        self.log = "main.c:12:3: warning: CONTROLLED TEST diagnostic\n"
        self.release = None

        async def compile_double(request, log):
            self.requests.append(request)
            self.assertFalse(request["allow_install"])
            self.assertTrue(request["offline"])
            log(self.log)
            if self.release:
                await self.release.wait()
            if isinstance(self.output, Exception):
                raise self.output
            return self.output
        self.adapter = OwnerQueueAdapter(lambda heavy: self.gate, compile_double, test_only=True, name="CONTROLLED_TEST_DOUBLE")
        self.service = BuildService(self.store, self.checker, adapter=self.adapter, toolchains=self.tools)
        self.addAsyncCleanup(self.service.close)

    def save(self, doc=None):
        result = self.store.save_project(document=document() if doc is None else doc)
        self.assertTrue(result["ok"], result)
        return result

    async def start(self, saved=None, service=None, board_id="esp"):
        saved = saved or self.save()
        return await (service or self.service).build_project(action="start", project_id=saved["project_id"], version=saved["version"], board_id=board_id)

    async def done(self, result, service=None):
        service = service or self.service
        self.assertTrue(result["ok"], result)
        for _ in range(100):
            result = await service.build_project(action="status", build_id=result["build_id"])
            self.assertTrue(result["ok"], result)
            self.assertLessEqual(len(canonical(result)), 24 * 1024)
            if result["state"] in ("done", "error", "interrupted"):
                return result
            await asyncio.sleep(0)
        self.fail("Controlled test job did not finish")

    def read(self, artifact, encoding="base64"):
        raw, offset = bytearray(), 0
        while True:
            page = self.store.read_artifact(artifact_id=artifact["id"], offset=offset, length=12288, encoding=encoding)
            self.assertTrue(page["ok"], page)
            self.assertLessEqual(len(canonical(page)), 24 * 1024)
            raw.extend(base64.b64decode(page["data"]) if encoding == "base64" else page["data"].encode())
            if page["eof"]:
                break
            offset = page["next_offset"]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])
        self.assertEqual(len(raw), artifact["size_bytes"])
        return bytes(raw)

    async def test_action_requirements_and_mixed_fields_are_refused_before_admission(self):
        start = {'action':'start', 'project_id':'p_'+'0'*32, 'version':'a'*64, 'board_id':'esp'}
        status = {'action':'status', 'build_id':'b_'+'1'*32}
        cases = [{}, {'action':'start'}, {'action':'status'},
                 *[{k:v for k,v in start.items() if k != missing}
                   for missing in ('project_id','version','board_id')],
                 {**start, 'build_id':status['build_id']},
                 *[{**status, key:start[key]} for key in ('project_id','version','board_id')]]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = await self.service.build_project(**arguments)
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], 'invalid_argument')
                self.assertIn('start(project_id,version,board_id)', result['error']['message'])
                self.assertIn('status(build_id)', result['error']['message'])
        self.assertEqual(self.gate.entered, 0)
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.service.lease)

    async def test_exact_v1_native_subset_after_v2_and_no_payload_in_status(self):
        original = document()
        first = self.save(original)
        second = copy.deepcopy(original)
        second["fileGroups"]["g/a~b"][0]["content"] = "different source"
        saved2 = self.store.save_project(document=second, project_id=first["project_id"], expected_version=first["version"])
        self.assertTrue(saved2["ok"])
        result = await self.done(await self.start(first))
        self.assertEqual(result["state"], "done")
        self.assertTrue(result["test_only"])
        self.assertIn("no real compiler", result["diagnostic_summary"])
        request = self.requests[0]
        self.assertEqual(request["version"], first["version"])
        self.assertEqual(request["files"], original["fileGroups"]["g/a~b"])
        self.assertEqual(request["native_subset"]["board"], original["boards"][0])
        self.assertEqual(request["board_options"], original["boards"][0]["boardOptions"])
        self.assertEqual(request["spiffs_files"][0]["content_b64"], "AQID")
        self.assertNotIn("firmware", {k: v for k, v in result.items() if k != "artifacts"})
        self.assertNotIn("content_b64", json.dumps(result))
        firmware = next(a for a in result["artifacts"] if a["kind"] == "firmware")
        self.assertEqual(self.read(firmware), self.output["firmware"])
        self.assertFalse(self.store.read_artifact(artifact_id=firmware["id"], encoding="utf8")["ok"])
        provenance = json.loads((Path(self.store.root) / "builds" / result["build_id"] / "provenance.json").read_bytes())
        self.assertEqual(provenance["libraries"]["GxEPD2"]["version"], "1.6.0")
        self.assertEqual(hashlib.sha256(canonical(provenance)).hexdigest(), result["provenance_sha256"])
        self.assertFalse(result["shared_cache_allowed"])

    async def test_concurrent_start_is_idempotent_and_single_admission(self):
        saved = self.save()
        first, second = await asyncio.gather(self.start(saved), self.start(saved))
        self.assertEqual(first["build_id"], second["build_id"])
        final = await self.done(first)
        repeated = await self.start(saved)
        self.assertEqual(repeated["build_id"], final["build_id"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.gate.entered, 1)

    async def test_selected_board_group_only_and_structural_error_refused(self):
        doc = document()
        other = copy.deepcopy(doc["boards"][0])
        other.update(id="other", activeFileGroupId="other-group", boardOptions={"flashSize": "16MB"})
        doc["boards"].append(other)
        doc["fileGroups"]["other-group"] = [{"name": "other.c", "content": "CONTROLLED OTHER BOARD"}]
        result = await self.done(await self.start(self.save(doc), board_id="other"))
        self.assertEqual(result["board_id"], "other")
        self.assertEqual(self.requests[0]["files"], doc["fileGroups"]["other-group"])
        self.assertEqual(self.requests[0]["native_subset"]["board"], other)
        doc["wires"][0]["end"]["pinName"] = "invalid"
        refused = await self.start(self.save(doc))
        self.assertEqual(refused["error"]["code"], "project_invalid")
        self.assertEqual(len(self.requests), 1)

    async def test_restart_recovers_running_as_interrupted_without_rerun(self):
        self.release = asyncio.Event()
        saved = self.save()
        result = await self.start(saved)
        await asyncio.sleep(0)
        running = await self.service.build_project(action="status", build_id=result["build_id"])
        self.assertEqual(running["state"], "running")
        await self.service.close()
        restarted = BuildService(self.store, self.checker, adapter=self.adapter, toolchains=self.tools)
        self.addAsyncCleanup(restarted.close)
        recovered = await restarted.build_project(action="status", build_id=result["build_id"])
        self.assertEqual(recovered["state"], "interrupted")
        self.assertFalse(recovered["success"])
        self.assertEqual((await self.start(saved, restarted))["build_id"], result["build_id"])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(any(a["kind"] == "build_log" for a in recovered["artifacts"]))

    async def test_failed_adapter_and_compiler_diagnostics_are_log_sourced(self):
        self.output = {"success": False, "error_kind": "syntax_error"}
        self.log = "main.c:9:2: error: CONTROLLED parse failure\n"
        result = await self.done(await self.start())
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["error_kind"], "syntax_error")
        diagnostic = result["diagnostics"][0]
        self.assertEqual((diagnostic["file"], diagnostic["line"], diagnostic["severity"]), ("main.c", 9, "error"))
        self.assertEqual(diagnostic["source"], "compiler_log")
        log = next(a for a in result["artifacts"] if a["kind"] == "build_log")
        self.assertEqual(diagnostic["log_sha256"], log["sha256"])
        self.assertIn(b"CONTROLLED parse failure", self.read(log, "utf8"))
        self.output = RuntimeError("CONTROLLED adapter exception")
        failed = await self.done(await self.start())
        self.assertEqual(failed["error_kind"], "adapter_error")
        self.assertFalse(failed["success"])

    async def test_log_tail_truncation_utf8_and_diagnostic_limits(self):
        self.log = "é" * 600000 + "\n" + "main.c:2: warning: CONTROLLED repeated\n" * 120
        result = await self.done(await self.start())
        self.assertTrue(result["log_truncated"])
        self.assertTrue(result["diagnostics_truncated"])
        self.assertEqual(len(result["diagnostics"]), 10)
        log = next(a for a in result["artifacts"] if a["kind"] == "build_log")
        self.assertLessEqual(log["size_bytes"], 1024 * 1024)
        self.read(log, "utf8").decode("utf8")

    async def test_default_owner_integration_blocker_and_no_auto_install(self):
        service = BuildService(self.store, self.checker, toolchains=self.tools)
        self.addAsyncCleanup(service.close)
        result = await self.start(service=service)
        self.assertEqual(result["error"]["code"], "owner_integration_required")
        self.assertIn("ensure_core_for_board", result["error"]["message"])
        self.assertFalse(self.requests)
        self.assertFalse((Path(self.store.root) / "builds").exists())

    async def test_dependencies_absent_unknown_and_toolchain_tampering_refused(self):
        self.checker.inventory = None
        result = await self.start()
        self.assertEqual(result["error"]["code"], "dependencies_unknown")
        self.checker.inventory = LibraryInventory(str(self.proofs), {}, complete=True)
        result = await self.start()
        self.assertEqual(result["error"]["code"], "dependency_unavailable")
        self.checker.inventory = self.libs
        (self.proofs / "CONTROLLED_FAKE_COMPILER.txt").write_text("tampered")
        result = await self.start()
        self.assertEqual(result["error"]["code"], "toolchain_unknown")
        self.assertFalse(self.requests)

    async def test_unsupported_and_unknown_policy_never_admitted(self):
        doc = document()
        doc["boards"][0]["languageMode"] = "micropython"
        result = await self.start(self.save(doc))
        self.assertEqual(result["error"]["code"], "unsupported")
        self.checker.source_root = self.root / "no-policy-sources"
        result = await self.start()
        self.assertEqual(result["error"]["code"], "compiler_policy_unknown")
        self.assertFalse(self.requests)

    async def test_firmware_and_global_quotas_do_not_publish_false_success(self):
        self.output = {"success": True, "firmware": b"x" * (32 * 1024 * 1024 + 1)}
        result = await self.done(await self.start())
        self.assertEqual(result["error_kind"], "quota_exceeded")
        self.assertFalse(any(a["kind"] == "firmware" for a in result["artifacts"]))
        saved = self.save()
        self.store.max_storage_bytes = 1
        result = await self.start(saved)
        self.assertEqual(result["error"]["code"], "quota_exceeded")
        self.assertTrue(self.store.read_artifact(artifact_id=saved["project_artifact_id"])["ok"])

    async def test_owner_exclusivity_and_queued_state(self):
        self.gate.open.clear()
        result = await self.start()
        await asyncio.sleep(0)
        status = await self.service.build_project(action="status", build_id=result["build_id"])
        self.assertEqual(status["state"], "pending")
        other = BuildService(self.store, self.checker, adapter=self.adapter, toolchains=self.tools)
        self.addAsyncCleanup(other.close)
        refused = await self.start(service=other)
        self.assertEqual(refused["error"]["code"], "owner_conflict")
        self.gate.open.set()
        self.assertEqual((await self.done(result))["state"], "done")

    async def test_restart_pending_and_incomplete_admission_files_preserved(self):
        self.gate.open.clear()
        result = await self.start()
        await asyncio.sleep(0)
        await self.service.close()
        orphan = Path(self.store.root) / "builds" / ("b_" + "f" * 32)
        orphan.mkdir()
        (orphan / "input.json").write_text("unacknowledged partial admission")
        restarted = BuildService(self.store, self.checker, adapter=self.adapter, toolchains=self.tools)
        self.addAsyncCleanup(restarted.close)
        status = await restarted.build_project(action="status", build_id=result["build_id"])
        self.assertEqual(status["state"], "interrupted")
        self.assertFalse(self.requests)
        self.assertTrue((orphan / "input.json").exists())

    async def test_existing_shared_queue_gate_with_controlled_fake_compile(self):
        from app.services import build_queue
        gate = build_queue.lane_for(True)
        release, ready = asyncio.Event(), asyncio.Event()
        count = 0
        async def pretend_rest_admission():
            nonlocal count
            async with gate.slot(priority=20):
                count += 1
                if count == gate.capacity:
                    ready.set()
                await release.wait()
        holders = [asyncio.create_task(pretend_rest_admission()) for _ in range(gate.capacity)]
        await ready.wait()
        self.adapter.lane_for = build_queue.lane_for
        result = await self.start()
        await asyncio.sleep(0)
        self.assertFalse(self.requests)
        self.assertEqual((await self.service.build_project(action="status", build_id=result["build_id"]))["state"], "pending")
        release.set()
        await asyncio.gather(*holders)
        self.assertEqual((await self.done(result))["state"], "done")

    async def test_firmware_hash_symlinks_and_build_paths(self):
        result = await self.done(await self.start())
        firmware = next(a for a in result["artifacts"] if a["kind"] == "firmware")
        blob = Path(self.store.root) / "builds" / result["build_id"] / "artifacts" / (firmware["sha256"] + ".firmware")
        original = blob.read_bytes()
        blob.write_bytes(b"tampered")
        self.assertEqual(self.store.read_artifact(artifact_id=firmware["id"])["error"]["code"], "integrity_error")
        blob.unlink()
        target = self.root / "outside"
        target.write_bytes(original)
        blob.symlink_to(target)
        self.assertFalse(self.store.read_artifact(artifact_id=firmware["id"])["ok"])
        self.assertEqual(target.read_bytes(), original)
        for value in ("latest", "../escape", result["project_id"]):
            self.assertFalse((await self.service.build_project(action="status", build_id=value))["ok"])
        self.assertFalse((await self.service.build_project(action="cancel", build_id=result["build_id"]))["ok"])

    async def test_large_firmware_and_valid_utf8_slice(self):
        self.output = {"success": True, "firmware": ("é" * (2 * 1024 * 1024)).encode(), "firmware_type": "hex"}
        result = await self.done(await self.start())
        self.assertEqual(result["firmware_type"], "hex")
        artifact = next(a for a in result["artifacts"] if a["kind"] == "firmware")
        page = self.store.read_artifact(artifact_id=artifact["id"], offset=2 * 1024 * 1024, length=17, encoding="utf8")
        self.assertTrue(page["ok"], page)
        self.assertEqual(page["data"], "é" * 8)
        self.assertEqual(page["sha256"], hashlib.sha256(self.output["firmware"]).hexdigest())

    async def test_symlink_output_directory_records_error_without_writing_outside(self):
        self.release = asyncio.Event()
        started = await self.start()
        await asyncio.sleep(0)
        target = self.root / "outside-dir"
        target.mkdir()
        artifacts = Path(self.store.root) / "builds" / started["build_id"] / "artifacts"
        artifacts.symlink_to(target, target_is_directory=True)
        self.release.set()
        result = await self.done(started)
        self.assertEqual(result["state"], "error")
        self.assertFalse(result["success"])
        self.assertFalse(list(target.iterdir()))

    async def test_toolchain_member_symlink_and_foreign_adapter_blocked(self):
        member = self.proofs / "CONTROLLED_FAKE_COMPILER.txt"
        original = member.read_bytes()
        member.unlink()
        target = self.root / "external-member"
        target.write_bytes(original)
        member.symlink_to(target)
        result = await self.start()
        self.assertEqual(result["error"]["code"], "toolchain_unknown")
        self.assertFalse(self.requests)
        member.unlink()
        member.write_bytes(original)
        self.adapter.pid = -1
        result = await self.done(await self.start())
        self.assertEqual(result["error_kind"], "owner_conflict")
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
