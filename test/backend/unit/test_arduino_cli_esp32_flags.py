"""ESP32 compiles must never override build.extra_flags.

The arduino-esp32 core stores its OWN native flags in build.extra_flags
(3.3.8: `-DARDUINO_HOST_OS=... -DARDUINO_FQBN=... -DESP32=ESP32 ...`;
2.0.17: `-DESP32 -DCORE_DEBUG_LEVEL=... {build.extra_flags.esp32}`). The old
code passed `--build-property build.extra_flags=-DARDUINO_ESP32_LCGAMBOA=1`,
which REPLACES that value, so every ESP32 compile silently lost -DESP32 and
the USB-CDC flag. GxEPD2 1.6.9 is the canary:

    #if defined(ESP8266) || defined(ESP32)
    #include <pgmspace.h>
    #else
    #include <avr/pgmspace.h>   -> fatal on the Xtensa toolchain

The custom defines now ride compiler.cpp.extra_flags, which is empty in
every arduino-esp32 core and only ever ADDS to recipe.cpp.o.pattern.

The process launcher the service calls is monkeypatched with a fake that
records the argv and drops the files a real build would leave in
--output-dir, so no arduino-cli is needed.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.arduino_cli import ArduinoCLIService  # noqa: E402

SKETCH = [{"name": "sketch.ino", "content": "void setup(){}\nvoid loop(){}\n"}]
ESP32_FQBN = "esp32:esp32:esp32"
ESP32C3_FQBN = "esp32:esp32:esp32c3"
AVR_FQBN = "arduino:avr:uno"

ESP32_CPP_EXTRA_FLAGS = "compiler.cpp.extra_flags=-DARDUINO_ESP32_LCGAMBOA=1 -DBitOrder=uint8_t"


def _service() -> ArduinoCLIService:
    svc = object.__new__(ArduinoCLIService)
    svc.cli_path = "arduino-cli"
    svc._installed_cores = ""
    return svc


def _outputs_for(fqbn: str) -> dict:
    if fqbn.startswith("esp32"):
        return {
            "sketch.ino.bin": b"\x00" * 16,
            "sketch.ino.bootloader.bin": b"\x01" * 8,
            "sketch.ino.partitions.bin": b"\x02" * 4,
        }
    return {"sketch.ino.hex": b":00000001FF\n"}


def _compile(fqbn: str, monkeypatch) -> tuple:
    """Run compile() against a fake arduino-cli; return (result, argv)."""
    captured = {}

    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        out = Path(cmd[cmd.index("--output-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        for name, data in _outputs_for(fqbn).items():
            (out / name).write_bytes(data)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    result = asyncio.run(_service().compile(SKETCH, fqbn))
    return result, captured["cmd"]


def _prop(cmd: list) -> str:
    return cmd[cmd.index("--build-property") + 1]


# ── the regression: the core's build.extra_flags must never be clobbered ─────


def test_esp32_compile_does_not_clobber_the_core_build_extra_flags(monkeypatch):
    result, cmd = _compile(ESP32_FQBN, monkeypatch)
    assert result["success"] is True
    assert "build.extra_flags" not in " ".join(cmd)
    assert _prop(cmd) == ESP32_CPP_EXTRA_FLAGS
    assert cmd[cmd.index("--fqbn") + 1] == "esp32:esp32:esp32:FlashMode=dio"


def test_esp32c3_compile_does_not_clobber_the_core_build_extra_flags(monkeypatch):
    result, cmd = _compile(ESP32C3_FQBN, monkeypatch)
    assert result["success"] is True
    assert "build.extra_flags" not in " ".join(cmd)
    assert _prop(cmd) == ESP32_CPP_EXTRA_FLAGS
    assert cmd[cmd.index("--fqbn") + 1] == "esp32:esp32:esp32c3:FlashMode=dio"


def test_lcgamboa_marker_define_still_reaches_the_cpp_compile(monkeypatch):
    """The lcgamboa marker moved to another property but must not be lost."""
    _, cmd = _compile(ESP32_FQBN, monkeypatch)
    assert "-DARDUINO_ESP32_LCGAMBOA=1" in _prop(cmd)


def test_bit_order_define_still_reaches_the_cpp_compile(monkeypatch):
    """BitOrder restoration (Adafruit_BusIO 1.17.x on ESP32 3.x) must survive."""
    _, cmd = _compile(ESP32_FQBN, monkeypatch)
    assert "-DBitOrder=uint8_t" in _prop(cmd)


# ── the command-construction contract ────────────────────────────────────────


def test_esp32_compile_command_is_exact():
    cmd = _service()._compile_command(ESP32_FQBN, Path("/build"), Path("/sketch"))
    assert cmd == [
        "arduino-cli", "compile",
        "--fqbn", "esp32:esp32:esp32:FlashMode=dio",
        "--build-property", ESP32_CPP_EXTRA_FLAGS,
        "--output-dir", "/build",
        "/sketch",
    ]


def test_a_fqbn_that_already_carries_flash_mode_is_not_rewritten():
    cmd = _service()._compile_command(
        "esp32:esp32:esp32s3:FlashMode=qio", Path("/build"), Path("/sketch"))
    assert cmd[3] == "esp32:esp32:esp32s3:FlashMode=qio"
    assert _prop(cmd) == ESP32_CPP_EXTRA_FLAGS


def test_avr_compile_command_carries_no_build_properties():
    cmd = _service()._compile_command(AVR_FQBN, Path("/build"), Path("/sketch"))
    assert cmd == [
        "arduino-cli", "compile",
        "--fqbn", AVR_FQBN,
        "--output-dir", "/build",
        "/sketch",
    ]
