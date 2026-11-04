"""Offline build orchestration. No real compiler/HTTP/import of REST routes."""

import asyncio
import copy
import fcntl
import hashlib
import json
import os
import re
import uuid

from .checks import LibraryInventory
from .errors import failure
from .projects import DIR_FLAGS, MAX_PROJECT_BYTES, ProjectStore, canonical, fail, filename
from .contracts import MAX_RESPONSE_BYTES
from .catalog import CatalogError
from .diagnostics import capture, diagnostics, first_error

OWNER_BLOCKER = ("REST owner bridge required: bind the existing build_queue.lane_for and an offline/no-install compile callback "
                 "in the route owner's event loop. _run_compile currently calls ensure_core_for_board; no such safe production hook is wired here.")


def proof_bytes(root, relative, maximum=32 * 1024 * 1024):
    filename(relative)
    if not os.path.isabs(root) or root != "/" and any(p in ("", ".", "..") for p in root.split("/")[1:]):
        fail("preflight_unknown", "Invalid proof root")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in ([] if root == "/" else root.split("/")[1:]) + relative.split("/")[:-1]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        source = os.open(relative.split("/")[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        try:
            if ProjectStore._regular(source).st_size > maximum:
                fail("quota_exceeded", "Inventory proof exceeds byte quota")
            with os.fdopen(source, "rb", closefd=False) as stream:
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                fail("quota_exceeded", "Inventory proof exceeds byte quota")
            return raw
        finally:
            os.close(source)
    finally:
        os.close(fd)


class ToolchainInventory(LibraryInventory):
    """Pinned manifest plus local member hashes; never executes version commands."""

    def verify(self):
        verified = super().verify()
        toolchains = {}
        total = 0
        for name, entry in self.entries.items():
            raw = proof_bytes(self.root, entry["path"], 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                fail("preflight_unknown", "Toolchain manifest changed")
            doc = json.loads(raw)
            if doc.get("kind") != "toolchain" or doc.get("name") != name or not isinstance(doc.get("version"), str) or not 1 <= len(doc["version"]) <= 200:
                fail("preflight_unknown", "Unverifiable toolchain identity/version")
            members = doc.get("members")
            if not isinstance(members, list) or not 1 <= len(members) <= 128:
                fail("preflight_unknown", "Toolchain requires pinned member evidence")
            for member in members:
                data = proof_bytes(self.root, member["path"])
                total += len(data)
                if total > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != member["sha256"]:
                    fail("preflight_unknown", "Toolchain member hash/size differs")
            toolchains[name] = {"version": doc["version"], "manifest_sha256": entry["sha256"], "members": members,
                                "test_only": doc.get("test_only") is True, "inventory_root": self.root}
            for field in ('idf_root', 'arduino_root', 'managed_components', 'avr'):
                if field in doc:
                    toolchains[name][field] = copy.deepcopy(doc[field])
            if 'arduino_core' in doc:
                core = doc['arduino_core']
                if not isinstance(core, dict) or core.get('id') != ':'.join(name.split('|')[0].split(':')[:2]) or not isinstance(core.get('version'), str) or not core['version']:
                    fail('preflight_unknown', 'Installed Arduino core identity/version is not proven')
                for label in ('platform', 'boards'):
                    path = core.get(label + '_path')
                    digest = core.get(label + '_sha256')
                    if not isinstance(path, str) or not path.endswith(label + '.txt') or not any(m['path'] == path and m['sha256'] == digest for m in members):
                        fail('preflight_unknown', 'Arduino platform/boards evidence must be among verified members')
                toolchains[name]['arduino_core'] = copy.deepcopy(core)
        return {**verified, "toolchains": toolchains}


class OwnerQueueAdapter:
    """Required owner interface. Stage 3c only permits explicitly test-only callbacks.

    lane_for must be the SAME callable/gates used by REST, bound in that process
    and event loop; no new queue, compiler, thread, process or HTTP fallback.
    """

    def __init__(self, lane_for=None, compile_offline=None, *, test_only=False, name="owner-bridge"):
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            fail("invalid_argument", "Adapter identity must be a bounded versioned name")
        self.lane_for, self.compile_offline, self.test_only, self.name = lane_for, compile_offline, test_only, name
        self.pid = os.getpid()
        self.loop = None

    @property
    def ready(self):
        return self.test_only is True and callable(self.lane_for) and callable(self.compile_offline)

    async def compile(self, request, running, log):
        if not self.ready:
            fail("owner_integration_required", OWNER_BLOCKER)
        loop = asyncio.get_running_loop()
        if self.pid != os.getpid() or self.loop is not None and self.loop is not loop:
            fail("owner_conflict", "Adapter is not in its owning process/event loop")
        self.loop = loop
        lane = self.lane_for(request["board_fqbn"].startswith("esp32:"))
        async with lane.slot(priority=20, key=request["request_key"]):
            running()
            return await self.compile_offline(copy.deepcopy(request), log)


class BuildService:
    def __init__(self, store, checker, *, adapter=None, toolchains=None):
        self.store, self.checker, self.adapter, self.toolchains = store, checker, adapter, toolchains
        self.owner = uuid.uuid4().hex
        self.lease = None
        self.tasks = {}
        self.closed = False
        self.pid = os.getpid()

    def _job(self, root, build_id):
        self.store._id(build_id, "b")
        with self.store._directory(root, "builds") as builds, self.store._directory(builds, build_id) as build:
            job = json.loads(self.store._read(build, "job.json"))
            if job["build_id"] != build_id:
                fail("integrity_error", "Build ID mismatch")
            return job

    def _write(self, root, build, job):
        raw = canonical(job)
        try:
            old = self.store._read(build, "job.json")
        except FileNotFoundError:
            old = b""
        if len(raw) > MAX_PROJECT_BYTES or (len(raw) > len(old) and self.store._usage(root) + len(raw) - len(old) > self.store.max_storage_bytes):
            fail("quota_exceeded", "Build metadata quota reached; files retained")
        self.store._publish(build, "job.json", raw, replace=True)

    def _ensure_owner(self):
        if os.getpid() != self.pid:
            fail("owner_conflict", "Build service belongs to a different process")
        if self.closed:
            fail("owner_conflict", "Build service is closed")
        if self.lease is not None:
            with self.store._locked(False) as root:
                current = os.stat(".build-owner.lock", dir_fd=root, follow_symlinks=False)
                held = os.fstat(self.lease)
                if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                    fail("owner_conflict", "Owner lease path was replaced")
            return True
        with self.store._locked(True) as root:
            fd = os.open(".build-owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
            try:
                self.store._regular(fd)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                current = os.stat(".build-owner.lock", dir_fd=root, follow_symlinks=False)
                held = os.fstat(fd)
                if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                    fail("owner_conflict", "Owner lease changed during acquisition")
            except BlockingIOError:
                os.close(fd)
                return False
            except BaseException:
                os.close(fd)
                raise
            self.lease = fd
            try:
                with self.store._directory(root, "builds", True) as builds:
                    for build_id in os.listdir(builds):
                        self.store._id(build_id, "b")
                        with self.store._directory(builds, build_id) as build:
                            try:
                                job = self._job(root, build_id)
                            except FileNotFoundError:
                                continue  # Incomplete, unacknowledged admission; retain files.
                            if job["state"] in ("pending", "running"):
                                job.update(state="interrupted", success=False, error_kind="owner_restarted", diagnostic_summary="Owner restarted; no successful compilation inferred")
                                job.pop("reservation_padding", None)
                                self._finish(root, build, job, None)
            except BaseException:
                os.close(self.lease)
                self.lease = None
                raise
        return True

    def _preflight(self, pid, version, board_id):
        checked = self.checker.check_project(project_id=pid, version=version)
        if not checked["ok"]:
            fail(checked["error"]["code"], checked["error"]["message"])
        with self.store._locked(False) as root:
            doc = self.store._load_version(root, pid, version)
            with self.store._directory(root, "projects") as projects, self.store._directory(projects, pid) as project, self.store._directory(project, "reports") as reports:
                report = json.loads(self.store._read(reports, checked["diagnostic_artifact_sha256"] + ".json"))
        if hashlib.sha256(canonical(report)).hexdigest() != checked["diagnostic_artifact_sha256"]:
            fail("integrity_error", "Preflight report hash differs")
        if "compiler_file_layout" in report["checks_unavailable"]:
            fail("compiler_policy_unknown", "Compiler policy is unverified; compilation refused")
        board = next((b for b in doc["boards"] if b["id"] == board_id), None)
        if board is None:
            fail("invalid_argument", "board_id does not exist in this exact snapshot")
        entry = self.checker.catalog._entries.get("board:" + board["boardKind"])
        mode = board.get("languageMode", "arduino")
        if entry is None or mode not in ("arduino", "espidf") or mode not in entry.get("languages", []) or not entry.get("fqbn"):
            fail("unsupported", "No documented offline compiler target for this board/language")
        bi = doc["boards"].index(board)
        if any(i["code"] == "dependency_absent" and i["path"].startswith(f"/boards/{bi}/") for i in report["issues"]):
            fail("dependency_unavailable", "Dependency is absent from the verified inventory; installation is forbidden")
        if report["structure_status"] != "valid":
            issue = next((item for item in report['issues'] if item['severity'] == 'error' and 'file' in item), None)
            if issue:
                error = CatalogError('project_invalid', issue['message'])
                error.details = {key: issue[key] for key in ('path', 'file', 'observed', 'expected', 'next_action')}
                raise error
            fail("project_invalid", "Structural preflight failed; report artifact: " + checked["diagnostic_artifact_id"])
        libraries = board.get("libraries")
        inventory = report.get("inventory")
        if not isinstance(libraries, list) or inventory is None or any(name not in inventory["entries"] for name in libraries):
            fail("dependencies_unknown", "Every declared dependency requires verified inventory evidence; no installation attempted")
        if any(i["code"] in ("dependency_name_unknown", "dependencies_undeclared", "language_support_unknown") and i["path"].startswith(f"/boards/{bi}/") for i in report["issues"]):
            fail("dependencies_unknown", "Target support/dependencies remain undocumented")
        if self.toolchains is None:
            fail("toolchain_unknown", "A verified toolchain manifest and pinned members are required")
        try:
            toolchains = self.toolchains.verify()
        except (OSError, ValueError, KeyError, TypeError):
            fail("toolchain_unknown", "Toolchain proof cannot be verified; no setup or installation attempted")
        key = entry["fqbn"] + "|" + mode
        toolchain = toolchains["toolchains"].get(key)
        if toolchain is None or toolchain["test_only"] is not self.adapter.test_only:
            fail("toolchain_unknown", "Toolchain execution mode must match the sealed adapter mode")
        lib_proof = {}
        for name in libraries:
            evidence = inventory["entries"][name]
            raw = proof_bytes(self.checker.inventory.root, evidence["path"], 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
                fail("dependencies_unknown", "Library proof changed after structural preflight")
            match = re.search(rb"(?m)^version\s*=\s*([^\r\n]+)", raw)
            lib_proof[name] = {**evidence, **{k: copy.deepcopy(v) for k, v in self.checker.inventory.entries[name].items() if k in ('source_root', 'tree_sha256')},
                               "version": match[1].decode("utf8")[:200] if match else "unknown"}
        provenance = {"project_id": pid, "version": version, "board_id": board_id, "catalog_revision": self.checker.catalog.revision,
                      "compiler_policy_sources": report["compiler_policy_sources"], "toolchain": toolchain, "libraries": lib_proof,
                      "adapter": {"name": self.adapter.name, "test_only": self.adapter.test_only},
                      "reproducibility_limited": True, "shared_cache_allowed": False, "test_only": self.adapter.test_only}
        request = {"project_id": pid, "version": version, "board_id": board_id, "board_fqbn": entry["fqbn"], "board_kind": board["boardKind"],
                   "files": copy.deepcopy(doc["fileGroups"][board["activeFileGroupId"]]), "language": mode,
                   "board_options": copy.deepcopy(board.get("boardOptions")), "libraries": copy.deepcopy(libraries),
                   "spiffs_files": [{**{k: v for k, v in f.items() if k != "contentB64"}, "content_b64": f["contentB64"]} for f in board.get("spiffsFiles", [])],
                   "native_subset": {"board": copy.deepcopy(board), "file_group": copy.deepcopy(doc["fileGroups"][board["activeFileGroupId"]])},
                   "toolchain": copy.deepcopy(toolchain), "library_proofs": copy.deepcopy(lib_proof),
                   "offline": True, "allow_install": False, "test_only": self.adapter.test_only}
        return request, provenance

    async def build_project(self, **arguments):
        from .arguments import normalize
        arguments = normalize('build_project', arguments)
        has_wait = 'wait_seconds' in arguments
        wait_seconds = arguments.pop('wait_seconds', 20)
        if (type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= 60
                or has_wait and arguments.get('action') != 'start'):
            return failure('invalid_argument', 'wait_seconds must be a finite number from 0 to 60, for start only', tool='build_project', arguments={**arguments, 'wait_seconds': wait_seconds}, path='/wait_seconds', received=repr(wait_seconds)[:200], expected='finite number 0..60 on action=start only')
        deadline = asyncio.get_running_loop().time() + wait_seconds
        def operation():
            action = arguments.get("action")
            if action == 'start' and set(arguments) == {'action','project_id','version'}:
                with self.store._locked(False) as root:
                    snapshot = self.store._load_version(root,arguments['project_id'],arguments['version'])
                arguments['board_id'] = snapshot['activeBoardId']
            if action == "status" and set(arguments) == {"action", "build_id"}:
                self._ensure_owner()
                with self.store._locked(False) as root:
                    return self._status(self._job(root, arguments["build_id"]))
            if action != "start" or set(arguments) != {"action", "project_id", "version", "board_id"}:
                fail("invalid_argument", "build_project supports only start(project_id,version,board_id) and status(build_id)")
            if self.adapter is None or not self.adapter.ready:
                fail(*getattr(self.adapter, "blocker", ("owner_integration_required", OWNER_BLOCKER)))
            if not self.adapter.test_only:
                from .offline_owner import BoundOfflineAdapter
                if not isinstance(self.adapter, BoundOfflineAdapter):
                    fail("owner_integration_required", "Production requires the sealed REST owner binding; arbitrary callbacks are forbidden")
            if not self._ensure_owner():
                fail("owner_conflict", "A different service/process already owns build admission")
            request, provenance = self._preflight(arguments["project_id"], arguments["version"], arguments["board_id"])
            request_key = hashlib.sha256(canonical({"request": request, "provenance": provenance, "adapter": self.adapter.name})).hexdigest()
            request["request_key"] = request_key
            if len(canonical(request)) > 8 * 1024 * 1024:
                fail("quota_exceeded", "Derived native/compiler input exceeds 8 MiB")
            with self.store._locked(True) as root:
                with self.store._directory(root, "build_keys", True) as keys, self.store._directory(root, "builds", True) as builds:
                    try:
                        record = json.loads(self.store._read(keys, request_key + ".json", 4096))
                    except FileNotFoundError:
                        record = None
                    if record is not None:
                        job = self._job(root, record["build_id"])
                        if job["request_key"] != request_key:
                            fail("integrity_error", "Build idempotence key differs")
                        return self._status(job)
                    build_id = "b_" + uuid.uuid4().hex
                    job = {"build_id": build_id, "project_id": request["project_id"], "version": request["version"], "board_id": request["board_id"],
                           "request_key": request_key, "owner": self.owner, "state": "pending", "success": None, "error_kind": None,
                           "test_only": self.adapter.test_only, "artifacts": [], "firmware_type": None, "diagnostics": [], "diagnostics_truncated": False, "log_truncated": False,
                           "diagnostic_summary": "TEST DOUBLE; pending owner admission; no real compiler" if self.adapter.test_only else "Pending offline REST-owner admission", "reservation_padding": " " * 8192,
                           "provenance_sha256": hashlib.sha256(canonical(provenance)).hexdigest(), "toolchain_version": provenance["toolchain"]["version"]}
                    required = sum(len(canonical(v)) for v in (request, provenance, job)) + 2048
                    if self.store._usage(root) + required > self.store.max_storage_bytes:
                        fail("quota_exceeded", "Build admission quota reached; existing files retained")
                    with self.store._directory(builds, build_id, True) as build:
                        self.store._publish(build, "input.json", canonical(request))
                        self.store._publish(build, "provenance.json", canonical(provenance))
                        self._write(root, build, job)
                    self.store._publish(keys, request_key + ".json", canonical({"build_id": build_id}))
            task = asyncio.create_task(self._run(build_id, request, adapter=self.adapter))
            self.tasks[build_id] = task
            return self._status(job)
        result = self.store._response(operation, tool='build_project', arguments=arguments)
        if result.get('ok') and arguments.get('action') == 'start':
            task = self.tasks.get(result['build_id'])
            if task is not None and not task.done() and wait_seconds:
                # asyncio.wait does not cancel the owner on timeout or caller
                # cancellation, and no filesystem lock is held across this wait.
                await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
            build_id = result['build_id']
            def refreshed():
                with self.store._locked(False) as root:
                    return self._status(self._job(root, build_id))
            result = self.store._response(refreshed, tool='build_project', arguments=arguments)
        return result

    def _event(self, build_id, *, running=False, log=None):
        self._ensure_owner()
        with self.store._locked(True) as root, self.store._directory(root, "builds") as builds, self.store._directory(builds, build_id) as build:
            job = self._job(root, build_id)
            if job["owner"] != self.owner or job["state"] not in ("pending", "running"):
                fail("owner_conflict", "Build callback no longer owns this job")
            if running:
                job["state"] = "running"
            if log is not None:
                if not isinstance(log, str):
                    fail("invalid_compiler_result", "Compiler logs must be UTF-8 text")
                capture(job, log)
                try:
                    old = self.store._read(build, "live.log", 1024 * 1024)
                except FileNotFoundError:
                    old = b""
                raw = old + log.encode("utf8")
                if len(raw) > 1024 * 1024:
                    raw = raw[-1024 * 1024:]
                    while raw and raw[0] & 0xc0 == 0x80:
                        raw = raw[1:]
                    job["log_truncated"] = True
                if self.store._usage(root) + max(0, len(raw) - len(old)) > self.store.max_storage_bytes:
                    fail("quota_exceeded", "Live log storage quota reached")
                self.store._publish(build, "live.log", raw, replace=True)
            self._write(root, build, job)

    def _finish(self, root, build, job, result):
        job.pop("reservation_padding", None)
        try:
            try:
                log = self.store._read(build, "live.log", 1024 * 1024)
            except FileNotFoundError:
                log = b""
            log_artifact = self.store._build_blob(root, build, job, "build_log", log)
            job["artifacts"] = [log_artifact]
            request = json.loads(self.store._read(build, "input.json", 8 * 1024 * 1024))
            capture(job, '', final=True)
            job["diagnostics"], job["diagnostics_truncated"], job['warnings'], job['warnings_truncated'] = diagnostics(log, log_artifact, request)
            if not job.get('first_error'):
                row = next((row for row in job['diagnostics'] if row['severity'] == 'error'), None)
                if row:
                    job['first_error'] = first_error(row)
            if result is not None:
                if not isinstance(result, dict) or type(result.get("success")) is not bool:
                    fail("invalid_compiler_result", "Adapter result must provide boolean success")
                if result["success"]:
                    if job.get('first_error'):
                        fail('invalid_compiler_result', 'Compiler claimed success despite an error in its output')
                    if not isinstance(result.get("firmware"), bytes) or not result["firmware"]:
                        fail("invalid_compiler_result", "Successful adapter result requires firmware bytes")
                    if result.get("firmware_type", "bin") not in ("bin", "hex", "uf2", "elf"):
                        fail("unsupported", "Unknown firmware format")
                    job["artifacts"].append(self.store._build_blob(root, build, job, "firmware", result["firmware"]))
                    job["firmware_type"] = result.get("firmware_type", "bin")
                failure = result.get("error_kind", "compile_error")
                if failure not in ("missing_library", "core_install_failed", "linker_error", "syntax_error", "compile_error", "unknown",
                                   "offline_guard_unavailable", "core_unavailable", "dependency_unavailable", "toolchain_unknown", "unsupported"):
                    failure = "compile_error"
                job.update(state="done" if result["success"] else "error", success=result["success"],
                           error_kind=None if result["success"] else failure, diagnostic_summary="TEST DOUBLE result; no real compiler was executed" if job["test_only"] else "Offline REST-owner compiler result")
            self._write(root, build, job)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            code = getattr(exc, "code", "storage_error")
            job.update(state="error", success=False, error_kind=code, diagnostics=[], diagnostic_summary=("TEST DOUBLE" if job["test_only"] else "Offline owner") + " failed: " + code + "; existing files retained")
            self._write(root, build, job)

    async def _run(self, build_id, request, *, adapter=None):
        try:
            result = await (adapter or self.adapter).compile(request, lambda: self._event(build_id, running=True), lambda line: self._event(build_id, log=line))
        except asyncio.CancelledError:
            return  # Deliberately leave pending/running for next-owner recovery.
        except Exception as exc:
            with self.store._locked(True) as root, self.store._directory(root, "builds") as builds, self.store._directory(builds, build_id) as build:
                job = self._job(root, build_id)
                if job["owner"] != self.owner or job["state"] not in ("pending", "running"):
                    return
                job.update(state="error", success=False, error_kind=getattr(exc, "code", "adapter_error"), diagnostic_summary=("TEST DOUBLE" if job["test_only"] else "Offline owner") + " adapter failed; no successful compilation inferred")
                self._finish(root, build, job, None)
            return
        self._ensure_owner()
        with self.store._locked(True) as root, self.store._directory(root, "builds") as builds, self.store._directory(builds, build_id) as build:
            job = self._job(root, build_id)
            if job["owner"] == self.owner and job["state"] in ("pending", "running"):
                self._finish(root, build, job, result)

    @staticmethod
    def _status(job):
        result = {k: job[k] for k in ("build_id", "state", "success", "error_kind", "artifacts", "firmware_type", "diagnostic_summary", "test_only", "log_truncated", "provenance_sha256", "toolchain_version")}
        result.update(ok=True, project_id=job["project_id"], version=job["version"], board_id=job["board_id"],
                      reproducibility_limited=True, shared_cache_allowed=False, diagnostics=job["diagnostics"][:10],
                      diagnostics_truncated=job["diagnostics_truncated"] or len(job["diagnostics"]) > 10)
        active = job['state'] in ('pending', 'running')
        if active:
            result.update(state='running', success=None, stage='queued' if job['state'] == 'pending' else 'compiling',
                          next_action='call build_project status build_id=' + job['build_id'])
        else:
            result.update(stage='complete', next_action='Build finished; compilation only, no simulation.' if job.get('success') else
                          'Fix first_error, save a new project version and call build_project start again.')
        legacy_warnings = [row for row in result['diagnostics'] if row.get('severity') == 'warning']
        result['diagnostics'] = sorted((row for row in result['diagnostics'] if row.get('severity') != 'warning'),
                                       key=lambda row: row.get('severity') != 'error')
        warnings = job.get('warnings', legacy_warnings)
        result.update(warnings=warnings[:5], warnings_truncated=job.get('warnings_truncated', False) or len(warnings) > 5)
        error = job.get('first_error')
        if not error and not active and job.get('success') is not True:
            error = {'file': None, 'line': None, 'message': ('Build did not succeed: ' + str(job.get('error_kind') or job['state']) + '; no parsed compiler error is available.')[:240],
                     'suggestion': 'Read the build_log artifact and resolve the reported failure before rebuilding.'}
        result['first_error'] = error
        while len(canonical(result)) > MAX_RESPONSE_BYTES and result["diagnostics"]:
            result["diagnostics"].pop()
            result["diagnostics_truncated"] = True
        return {'ok': result.pop('ok'), 'build_id': result.pop('build_id'), 'state': result.pop('state'),
                'success': result.pop('success'), 'first_error': result.pop('first_error'), **result}

    async def close(self):
        if self.adapter is None or self.adapter.test_only:
            for task in self.tasks.values():
                if not task.done():
                    task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        if self.adapter is not None and not self.adapter.test_only:
            await self.adapter.owner.drain()
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None
        self.closed = True
