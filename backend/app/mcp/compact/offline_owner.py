"""Internal REST-owner binding. Production execution remains fail-closed.

No compiler import, worker, install, environment mutation or network operation.
"""

import asyncio
import base64
import copy
import os
import sys
from types import MethodType

from .projects import fail

_SEAL = object()


class RestCompileOwner:
    def __init__(self, seal, *, lane_for, arduino, idf, request_model, resolve_scope, resolve_priority, admit, retry_context, test_only):
        if seal is not _SEAL:
            raise TypeError("Use the real route binding or the explicit test factory")
        self.lane_for, self.arduino, self.idf = lane_for, arduino, idf
        self.request_model, self.resolve_scope, self.resolve_priority = request_model, resolve_scope, resolve_priority
        self.admit, self.retry_context = admit, retry_context
        self._test_only = test_only
        self.pid, self.loop = os.getpid(), asyncio.get_running_loop()
        self.app = None
        self.active = False
        self.closing = False
        self.tasks = set()

    @classmethod
    def from_route(cls, module):
        if module is not sys.modules.get("app.api.routes.compile"):
            fail("owner_integration_required", "Binding must originate from the actual compile route module")
        if type(module.arduino_cli).__module__ != "app.services.arduino_cli" or type(module.espidf_compiler).__module__ != "app.services.espidf_compiler":
            fail("owner_integration_required", "Production cannot bind caller-supplied fake compiler callbacks")
        for service in (module.arduino_cli, module.espidf_compiler):
            for name in ('compile_offline', 'offline_capabilities'):
                method = getattr(service, name)
                original = type(service).__dict__.get(name)
                if not isinstance(method, MethodType) or method.__self__ is not service or method.__func__ is not original or original.__module__ != type(service).__module__:
                    fail("owner_integration_required", "Production offline methods must be genuine class-bound methods, not injected callbacks")
        return cls(_SEAL, lane_for=module.build_queue.lane_for, arduino=module.arduino_cli, idf=module.espidf_compiler,
                   request_model=module.CompileRequest, resolve_scope=module._resolve_compile_scope,
                   resolve_priority=module._resolve_queue_priority, admit=module._admit_compile,
                   retry_context=module.scope_retry_allowed, test_only=False)

    @classmethod
    def for_tests(cls, **services):
        """Explicit monkeypatched-service tests; cannot mint production mode."""
        return cls(_SEAL, test_only=True, **services)

    @property
    def test_only(self):
        return self._test_only

    @property
    def production_blockers(self):
        blockers = []
        for service in (self.idf,):  # ESP32-only production scope; Arduino stays unsupported.
            capability = service.offline_capabilities()
            if not capability.get('ready'):
                blockers.extend(capability.get('blockers') or ['offline_service_capability_unknown'])
        return blockers

    def activate(self, app):
        self._owned_loop()
        if self.active:
            fail("owner_conflict", "REST owner already active")
        self.app, self.active = app, True

    def _owned_loop(self):
        if os.getpid() != self.pid or asyncio.get_running_loop() is not self.loop:
            fail("owner_conflict", "REST binding belongs to another process/event loop")

    def bind(self, request, user_id=None):
        self._owned_loop()
        if not self.active or self.closing or request.app is not self.app:
            fail("owner_integration_required", "An active matching REST application lifespan is required")
        return BoundOfflineAdapter(_SEAL, self, request, user_id)

    async def drain(self):
        self._owned_loop()
        while self.tasks:
            pending = tuple(self.tasks)
            waiter = asyncio.gather(*pending, return_exceptions=True)
            while True:
                try:
                    await asyncio.shield(waiter)
                    break
                except asyncio.CancelledError:
                    if waiter.done():
                        break

    async def close(self):
        self.closing = True
        await self.drain()
        self.active = False

    async def dispatch_offline(self, payload, log, scope, nice):
        """Only calls explicit offline methods; never ensure-core or CLI fallback."""
        common = {"board_options": payload.get("board_options"), "allowed_libraries": scope[0], "owner_id": scope[1],
                  "offline_evidence": payload.get("toolchain"), "library_proofs": payload.get("library_proofs", {})}
        if payload["board_fqbn"].startswith("esp32:"):
            result = await self.idf.compile_offline(payload["files"], payload["board_fqbn"],
                progress_callback=log, spiffs_files=payload.get("spiffs_files"), pure_idf=payload.get("language") == "espidf", cpu_nice=nice, **common)
        else:
            if not self.test_only:
                fail('unsupported', 'Offline production scope is ESP32 with approved template only')
            if payload.get("language") != "arduino":
                fail("unsupported", "Only installed Arduino cores support this offline branch")
            result = await self.arduino.compile_offline(payload["files"], payload["board_fqbn"], **common)
        for field in ("stdout", "stderr"):
            if result.get(field):
                log(result[field])
        if not result.get("success"):
            return {"success": False, "error_kind": result.get("error_kind", "compile_error")}
        if result.get("binary_content"):
            firmware = base64.b64decode(result["binary_content"], validate=True)
            kind = result.get("binary_type") or "bin"
        elif result.get("hex_content"):
            firmware, kind = result["hex_content"].encode("utf8"), "hex"
        else:
            fail("invalid_compiler_result", "Offline service returned success without firmware")
        if len(firmware) > 32 * 1024 * 1024:
            fail("quota_exceeded", "Decoded firmware exceeds 32 MiB")
        return {"success": True, "firmware": firmware, "firmware_type": kind}


class BoundOfflineAdapter:
    def __init__(self, seal, owner, request, user_id):
        if seal is not _SEAL:
            raise TypeError("Production adapter requires the internal owner binding")
        self.owner, self.request, self.user_id = owner, request, user_id
        self.name = "rest-owner-offline-v1"

    @property
    def test_only(self):
        return self.owner.test_only

    @property
    def blocker(self):
        return ("offline_guard_unavailable", "ESP32 production requires the reviewed template capability and verified local SDK/dependency proofs; other Arduino platforms remain unsupported. No OS network sandbox is claimed.")

    @property
    def ready(self):
        # Genuine binding is necessary, not proof of offline execution safety.
        try:
            self.owner._owned_loop()
        except (ValueError, RuntimeError):
            return False
        return self.owner.active and not self.owner.closing and (self.owner.test_only or not self.owner.production_blockers)

    async def compile(self, payload, running, log):
        owner = self.owner
        owner._owned_loop()
        if not owner.active or self.request.app is not owner.app:
            fail("owner_conflict", "REST owner is no longer active")
        if not self.ready:
            fail(*self.blocker)

        async def admitted():
            request = owner.request_model(**{k: copy.deepcopy(v) for k, v in payload.items() if k in (
                "files", "board_fqbn", "board_kind", "project_id", "board_options", "spiffs_files", "libraries", "language")})
            priority, _tier, nice = await owner.resolve_priority(self.user_id, self.request)
            scope = await owner.resolve_scope(request, self.user_id)
            allowed, _retry, _gallery, refusal = await owner.admit(request, payload["files"], scope[0], scope[1], self.user_id)
            if refusal is not None:
                fail("admission_refused", "Existing REST admission refused the compile")
            # Never let an overlay silently expand the pinned offline scope.
            if allowed != scope[0]:
                fail("offline_scope_changed", "Admission changed the verified dependency scope")
            token = owner.retry_context.set(False)
            try:
                async with owner.lane_for(payload["board_fqbn"].startswith("esp32:")).slot(priority=priority, key=payload["request_key"]):
                    running()
                    return await owner.dispatch_offline(payload, log, scope, nice)
            finally:
                owner.retry_context.reset(token)

        task = asyncio.create_task(admitted())
        owner.tasks.add(task)
        task.add_done_callback(owner.tasks.discard)
        # A cancelled client cannot drop the admission slot while shared build
        # directories are still being written. Finish/drain before returning.
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    return task.result()
