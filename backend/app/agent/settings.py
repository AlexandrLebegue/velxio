from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(default="http://127.0.0.1:11434/v1", max_length=2048)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    max_steps: int = Field(default=20, ge=1, le=100)
    max_output_tokens: int = Field(default=8192, ge=512, le=32768)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        parsed.port  # Validate the port while Pydantic can report a field error.
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(ord(char) < 32 for char in value):
            raise ValueError("Use an HTTP(S) API base URL without credentials, query or fragment")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value):
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid model ID")
        return value


def private_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
    temporary.replace(path)


class SettingsStore:
    def __init__(self, root: Path):
        self.root = root

    def read(self, owner: str) -> ConnectionSettings:
        path = self.root / owner / "connection.json"
        if not path.exists():
            return ConnectionSettings()
        return ConnectionSettings.model_validate_json(path.read_text())

    def save(self, owner: str, value: ConnectionSettings):
        previous = self.read(owner)
        updated = value.model_copy(update={
            "api_key": connection_key(value, previous),
            "clear_api_key": False,
        })
        private_json(self.root / owner / "connection.json", updated.model_dump())
        return self.public(updated)

    @staticmethod
    def public(value: ConnectionSettings):
        return {**value.model_dump(exclude={"api_key", "clear_api_key"}), "has_api_key": bool(value.api_key)}


def connection_key(value: ConnectionSettings, previous: ConnectionSettings):
    if value.clear_api_key:
        return None
    if value.api_key:
        return value.api_key
    current_url, previous_url = urlsplit(value.base_url), urlsplit(previous.base_url)
    if (current_url.scheme, current_url.netloc) == (previous_url.scheme, previous_url.netloc):
        return previous.api_key
    return None
