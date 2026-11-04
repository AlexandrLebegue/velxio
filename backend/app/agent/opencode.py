"""Managed OpenCode HTTP adapter. No LLM loop is implemented in Velxio."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import socket

import httpx

from .settings import AgentError, ConnectionSettings


class OpenCodeAdapter:
    def __init__(self, root: Path, work: Path, settings: ConnectionSettings, callback_url: str, token: str):
        self.root, self.work, self.settings = root, work, settings
        self.callback_url, self.token = callback_url, token
        self.process = None
        self.client = None
        self.password = secrets.token_urlsafe(32)
        self.session_id = None

    @staticmethod
    def executable():
        return shutil.which(os.environ.get("VELXIO_OPENCODE_BIN", "opencode"))

    async def start(self):
        binary = self.executable()
        if not binary:
            raise AgentError("harness_unavailable", "OpenCode is not installed on the Velxio server", 503)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": "velxio/" + self.settings.model,
            "enabled_providers": ["velxio"],
            "autoupdate": False,
            "share": "disabled",
            "lsp": False,
            "formatter": False,
            "provider": {"velxio": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Velxio connection",
                "options": {"baseURL": self.settings.base_url, "apiKey": self.settings.api_key or "local"},
                "models": {self.settings.model: {"name": self.settings.model, "tool_call": True,
                                                 "limit": {"output": self.settings.max_output_tokens}}},
            }},
            "permission": {
                "*": "deny", "read": "allow", "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow",
                "external_directory": "deny", "velxio_*": "allow",
            },
            "tools": {"*": False, "read": True, "edit": True, "glob": True, "grep": True, "list": True, "velxio_*": True},
            "agent": {"velxio": {"mode": "primary", "description": "Edit and simulate the active Velxio electronics project", "steps": self.settings.max_steps}},
            "default_agent": "velxio",
            "mcp": {"velxio": {"type": "remote", "url": self.callback_url, "headers": {"Authorization": "Bearer " + self.token}, "oauth": False}},
        }
        # Deliberately omit ambient provider credentials and user plugin config.
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")}
        env.update({
            "XDG_CONFIG_HOME": str(self.root / "config"), "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"), "OPENCODE_CONFIG_CONTENT": json.dumps(config),
            "OPENCODE_SERVER_PASSWORD": self.password, "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "OPENCODE_DISABLE_AUTOUPDATE": "true", "OPENCODE_DISABLE_MODELS_FETCH": "true",
        })
        log = open(self.root / "server.log", "ab")
        try:
            self.process = await asyncio.create_subprocess_exec(binary, "serve", "--hostname", "127.0.0.1", "--port", str(port), cwd=self.work, env=env, stdout=log, stderr=log)
        finally:
            log.close()
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", auth=("opencode", self.password),
                                       headers={"x-opencode-directory": str(self.work.resolve())}, timeout=15, trust_env=False)
        try:
            for _ in range(150):
                if self.process.returncode is not None:
                    raise AgentError("harness_start_failed", "OpenCode could not start; check its private server log", 503)
                try:
                    response = await self.client.get("/global/health")
                    if response.is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            raise AgentError("harness_timeout", "OpenCode did not become ready", 503)
        except BaseException:
            await self.close()
            raise

    async def create_session(self):
        response = await self.client.post("/session", json={"title": "Velxio project"})
        response.raise_for_status()
        self.session_id = response.json()["id"]
        return self.session_id

    async def prompt(self, text: str, system: str):
        response = await self.client.post(f"/session/{self.session_id}/prompt_async", json={
            "agent": "velxio", "model": {"providerID": "velxio", "modelID": self.settings.model},
            "system": system, "parts": [{"type": "text", "text": text}],
        })
        response.raise_for_status()

    async def events(self, ready: asyncio.Event):
        async with self.client.stream("GET", "/event", timeout=None) as response:
            response.raise_for_status()
            ready.set()
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    yield json.loads(line[5:].strip())

    async def messages(self):
        response = await self.client.get(f"/session/{self.session_id}/message", params={"limit": 100})
        response.raise_for_status()
        return response.json()

    async def abort(self):
        if self.client and self.session_id:
            try:
                await self.client.post(f"/session/{self.session_id}/abort")
            except httpx.HTTPError:
                pass

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.client:
            await self.client.aclose()
            self.client = None
