"""Validation helpers for the replaceable ``audio-manager`` role."""

from __future__ import annotations

import re
from typing import Any


AUDIO_STATE_SCHEMA = "msys.audio-state.v1"
MAX_AUDIO_OUTPUTS = 16
MAX_AUDIO_STACK_ROWS = 8
MAX_AUDIO_DEVICES = 32
BLUETOOTH_ADDRESS = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


def _optional_percent(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError(f"Audio manager returned an invalid {label}")
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Audio manager returned an invalid {label}")
    return value


def _bounded_text(
    value: object,
    label: str,
    *,
    maximum: int,
    empty: bool = True,
) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        raise ValueError(f"Audio manager returned an invalid {label}")
    return value


def normalise_audio_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Return one small, UI-safe view of ``msys.audio-state.v1``."""

    if not isinstance(payload, dict) or payload.get("schema") != AUDIO_STATE_SCHEMA:
        raise ValueError("Audio manager returned an invalid typed state")
    available = payload.get("available")
    if not isinstance(available, bool):
        raise ValueError("Audio manager returned an invalid availability state")
    backend = _bounded_text(payload.get("backend"), "backend", maximum=32, empty=False)
    raw_reason = payload.get("reason")
    if raw_reason is not None:
        raw_reason = _bounded_text(raw_reason, "reason", maximum=96)

    raw_stack = payload.get("stack")
    if not isinstance(raw_stack, list) or len(raw_stack) > MAX_AUDIO_STACK_ROWS:
        raise ValueError("Audio manager returned an invalid stack state")
    stack: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_stack):
        if not isinstance(raw, dict):
            raise ValueError(f"Audio manager returned an invalid stack row at {index}")
        name = _bounded_text(raw.get("name"), "stack name", maximum=48, empty=False)
        running = raw.get("running")
        if not isinstance(running, bool):
            raise ValueError(f"Audio manager returned an invalid stack status for {name}")
        pid = raw.get("pid")
        returncode = raw.get("returncode")
        if pid is not None and (
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
        ):
            raise ValueError(f"Audio manager returned an invalid PID for {name}")
        if returncode is not None and (
            isinstance(returncode, bool) or not isinstance(returncode, int)
        ):
            raise ValueError(f"Audio manager returned an invalid return code for {name}")
        stack.append(
            {
                "name": name,
                "running": running,
                "pid": pid,
                "returncode": returncode,
            }
        )

    raw_active = payload.get("active_output")
    active_id = ""
    if raw_active is not None:
        if not isinstance(raw_active, dict):
            raise ValueError("Audio manager returned an invalid active output")
        active_id = _bounded_text(
            raw_active.get("id"), "active output id", maximum=96, empty=False
        )

    raw_outputs = payload.get("outputs")
    if not isinstance(raw_outputs, list) or len(raw_outputs) > MAX_AUDIO_OUTPUTS:
        raise ValueError("Audio manager returned an invalid output list")
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_outputs):
        if not isinstance(raw, dict):
            raise ValueError(f"Audio manager returned an invalid output at {index}")
        identifier = _bounded_text(
            raw.get("id"), "output id", maximum=96, empty=False
        )
        if identifier in seen:
            raise ValueError("Audio manager returned duplicate output ids")
        seen.add(identifier)
        name_value = raw.get("name", identifier)
        name = _bounded_text(name_value, "output name", maximum=128, empty=False)
        address_value = raw.get("address", "")
        address = _bounded_text(address_value, "output address", maximum=32)
        profile_value = raw.get("profile", "")
        profile = _bounded_text(profile_value, "output profile", maximum=32)
        connected = raw.get("connected", False)
        if not isinstance(connected, bool):
            raise ValueError(f"Audio manager returned invalid connection state for {identifier}")
        mixer_value = raw.get("mixer_control")
        mixer_control = None
        if mixer_value is not None:
            mixer_control = _bounded_text(
                mixer_value, "mixer control", maximum=128, empty=False
            )
        outputs.append(
            {
                "id": identifier,
                "name": name,
                "address": address,
                "profile": profile,
                "connected": connected,
                "mixer_control": mixer_control,
                "volume_percent": _optional_percent(
                    raw.get("volume_percent"), "output volume"
                ),
                "muted": _optional_boolean(raw.get("muted"), "output mute state"),
                "active": identifier == active_id,
            }
        )
    if active_id and active_id not in seen:
        raise ValueError("Audio manager active output is not in the output list")

    raw_player = payload.get("player")
    if not isinstance(raw_player, dict):
        raise ValueError("Audio manager returned an invalid player state")
    enabled = raw_player.get("enabled")
    running = raw_player.get("running", False)
    if not isinstance(enabled, bool) or not isinstance(running, bool):
        raise ValueError("Audio manager returned an invalid player status")
    player = {
        "enabled": enabled,
        "running": running,
        "server": _bounded_text(raw_player.get("server", ""), "player server", maximum=255),
        "name": _bounded_text(
            raw_player.get("name", "MSYS Audio"),
            "player name",
            maximum=64,
            empty=False,
        ),
    }

    return {
        "schema": AUDIO_STATE_SCHEMA,
        "backend": backend,
        "available": available,
        "reason": raw_reason,
        "controller_registered": payload.get("controller_registered") is True,
        "stack": stack,
        "outputs": outputs,
        "active_output": active_id,
        "volume_percent": _optional_percent(
            payload.get("volume_percent"), "active volume"
        ),
        "muted": _optional_boolean(payload.get("muted"), "active mute state"),
        "player": player,
    }


def normalise_audio_devices(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the bounded device catalog owned by the private BlueZ stack."""

    if not isinstance(payload, dict) or payload.get("schema") != "msys.audio-devices.v1":
        raise ValueError("Audio manager returned an invalid typed device catalog")
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, list) or len(raw_devices) > MAX_AUDIO_DEVICES:
        raise ValueError("Audio manager returned an invalid Bluetooth device list")
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_devices):
        if not isinstance(raw, dict):
            raise ValueError(f"Audio manager returned an invalid device at {index}")
        address_value = raw.get("address")
        if not isinstance(address_value, str) or BLUETOOTH_ADDRESS.fullmatch(address_value) is None:
            raise ValueError(f"Audio manager returned an invalid device address at {index}")
        address = address_value.upper()
        if address in seen:
            raise ValueError("Audio manager returned duplicate Bluetooth addresses")
        seen.add(address)
        name = _bounded_text(
            raw.get("name") or raw.get("alias") or address,
            "device name",
            maximum=128,
            empty=False,
        )
        alias = _bounded_text(raw.get("alias", name), "device alias", maximum=128)
        icon = _bounded_text(raw.get("icon", "audio-card"), "device icon", maximum=64)
        flags: dict[str, bool] = {}
        for field in ("paired", "trusted", "connected"):
            value = raw.get(field, False)
            if not isinstance(value, bool):
                raise ValueError(
                    f"Audio manager returned invalid {field} state for {address}"
                )
            flags[field] = value
        devices.append(
            {
                "address": address,
                "name": name,
                "alias": alias,
                "icon": icon,
                **flags,
            }
        )
    devices.sort(
        key=lambda item: (
            0 if item["connected"] else 1 if item["paired"] else 2,
            item["name"].casefold(),
            item["address"],
        )
    )
    result: dict[str, Any] = {"schema": "msys.audio-devices.v1", "devices": devices}
    raw_scan = payload.get("scan")
    if raw_scan is not None:
        if not isinstance(raw_scan, dict):
            raise ValueError("Audio manager returned invalid scan metadata")
        expected = {
            "discovery_started",
            "duration_ms",
            "transport",
            "result",
            "diagnostic",
        }
        if set(raw_scan) != expected:
            raise ValueError("Audio manager returned incomplete scan metadata")
        duration = raw_scan.get("duration_ms")
        diagnostic = raw_scan.get("diagnostic")
        if (
            not isinstance(raw_scan.get("discovery_started"), bool)
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 0 <= duration <= 30000
            or raw_scan.get("transport") != "private-bluez"
            or raw_scan.get("result") not in {"devices-found", "no-devices"}
            or not isinstance(diagnostic, str)
            or len(diagnostic) > 128
        ):
            raise ValueError("Audio manager returned invalid scan metadata")
        result["scan"] = dict(raw_scan)
    return result


def bluetooth_address_request(address: object) -> dict[str, str]:
    if not isinstance(address, str) or BLUETOOTH_ADDRESS.fullmatch(address) is None:
        raise ValueError("Bluetooth address is invalid")
    return {"address": address.upper()}


def volume_request(percent: object, output: str = "") -> dict[str, Any]:
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise ValueError("Volume must be an integer from 0 to 100")
    payload: dict[str, Any] = {"percent": percent}
    if output:
        payload["output"] = _bounded_text(
            output, "output id", maximum=96, empty=False
        )
    return payload


def muted_request(muted: object, output: str = "") -> dict[str, Any]:
    if not isinstance(muted, bool):
        raise ValueError("Muted must be a boolean")
    payload: dict[str, Any] = {"muted": muted}
    if output:
        payload["output"] = _bounded_text(
            output, "output id", maximum=96, empty=False
        )
    return payload


def output_request(output: str) -> dict[str, str]:
    return {
        "id": _bounded_text(output, "output id", maximum=96, empty=False)
    }


def player_request(enabled: object, server: object, name: object) -> dict[str, Any]:
    if not isinstance(enabled, bool):
        raise ValueError("Player enabled must be a boolean")
    server_text = _bounded_text(server, "player server", maximum=255)
    if any(character.isspace() for character in server_text):
        raise ValueError("Player server must not contain whitespace")
    name_text = _bounded_text(name, "player name", maximum=64, empty=False)
    if any(ord(character) < 32 for character in name_text):
        raise ValueError("Player name contains a control character")
    return {"enabled": enabled, "server": server_text, "name": name_text}


__all__ = [
    "AUDIO_STATE_SCHEMA",
    "bluetooth_address_request",
    "muted_request",
    "normalise_audio_devices",
    "normalise_audio_state",
    "output_request",
    "player_request",
    "volume_request",
]
