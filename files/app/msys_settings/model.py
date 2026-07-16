"""UI-independent Settings model and normalization rules."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .audio import (
    bluetooth_address_request,
    muted_request,
    normalise_audio_devices,
    normalise_audio_state,
    output_request,
    player_request,
    volume_request,
)
from .client import SettingsClient
from .ipc import MipcRemoteError

LAYOUT_PROFILES = ("mobile", "kiosk", "desktop")
ORIENTATIONS = ("auto", "portrait", "landscape")
DESKTOP_LAYOUTS = ("profile", "auto", "mobile", "desktop", "kiosk")
DESKTOP_SORTS = ("name", "component")
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")
HAL_DOMAIN = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
HAL_COMPONENT = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+:[a-z][a-z0-9._-]*$"
)
HAL_CAPABILITY = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")
HAL_LEGACY_FEATURE_ERRORS = frozenset({"HAL_BAD_PAYLOAD", "HAL_UNKNOWN_METHOD"})
CH347_CONTROL_SCHEMA = "org.msys.hal.ch347-control.v1"
CH347_DEVICE = "display-output:ch347"
CH347_DEBUG_STATUSES = ("active", "idle", "unavailable")
CH347_DEBUG_COUNTER_FIELDS = (
    "sent_frames",
    "zero_damage",
    "full_refreshes",
    "large_refreshes",
    "sent_pixels",
    "last_sent_pixels",
    "last_rects",
)
CH347_DEBUG_OVERLAY_ITEMS = (
    "fps",
    "dirty",
    "bytes",
    "cpu",
    "bbox",
    "memory",
)
DEFAULT_CH347_DEBUG_OVERLAY: dict[str, Any] = {
    "enabled": False,
    "alpha": 176,
    "scale": 1,
    "items": ["fps", "dirty", "bytes", "cpu"],
    "interval_ms": 1000,
}
UINT64_MAX = 18_446_744_073_709_551_615
CH347_CALIBRATION_BOOLEAN_FIELDS = (
    "enabled",
    "swap_xy",
    "invert_x",
    "invert_y",
)
CH347_CALIBRATION_INTEGER_FIELDS = (
    "x_min",
    "x_max",
    "y_min",
    "y_max",
    "width",
    "height",
    "z_min",
    "pressure_min",
    "pressure_max",
)
CH347_CALIBRATION_FIELDS = (
    *CH347_CALIBRATION_BOOLEAN_FIELDS,
    *CH347_CALIBRATION_INTEGER_FIELDS,
)
RGB_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SHELL_PREFERENCES_SCHEMA = "msys.shell-preferences.v1"
INSTALL_AGENT_RESULT_SCHEMA = "msys.install-agent-result.v1"
INSTALL_AGENT_ERROR_SCHEMA = "msys.install-agent-error.v1"
INSTALLED_REGISTRY_SCHEMA = "msys.installed.v1"
DISPLAY_MIGRATION_SCHEMA = "msys.display-migration.v1"
DISPLAY_MIGRATION_PHASES = ("planned", "switching", "succeeded", "rolled-back")
DISPLAY_MIGRATION_TERMINAL_PHASES = frozenset({"succeeded", "rolled-back"})
INPUT_METHOD_STATE_SCHEMA = "msys.input-method-state.v1"

DEFAULT_DESKTOP_PREFERENCES: dict[str, Any] = {
    "layout": "profile",
    "wallpaper_color": "#101419",
    "accent_color": "#55A8FF",
    "icon_size": 64,
    "show_labels": True,
    "sort": "name",
}


@dataclass(slots=True)
class OperationResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    code: str = ""


def _section_failure(section: str, result: OperationResult) -> dict[str, str]:
    return {
        "section": section,
        "code": result.code or "UNAVAILABLE",
        "message": result.message,
    }


def _unavailable_section(result: OperationResult) -> dict[str, Any]:
    return {
        "available": False,
        "code": result.code or "UNAVAILABLE",
        "message": result.message,
        "details": result.data,
    }


def _normalise_input_method_result(result: OperationResult) -> OperationResult:
    if not result.ok:
        return result
    payload = result.data
    if not isinstance(payload, dict):
        return OperationResult(
            False,
            message="Input method returned a non-object state",
            code="INPUT_METHOD_BAD_RESPONSE",
        )
    schema = payload.get("schema")
    visible = payload.get("visible")
    if schema != INPUT_METHOD_STATE_SCHEMA or not isinstance(visible, bool):
        return OperationResult(
            False,
            {"response": payload},
            "Input method returned an invalid typed state",
            "INPUT_METHOD_BAD_RESPONSE",
        )
    result.data = {
        "schema": INPUT_METHOD_STATE_SCHEMA,
        "visible": visible,
        "layout": str(payload.get("layout") or ""),
        "locale": str(payload.get("locale") or ""),
        "mode": str(payload.get("mode") or ""),
    }
    return result


def normalise_role_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the dynamic role/provider catalog returned by ``msys.core``."""

    if not isinstance(payload, dict):
        raise TypeError("Core returned a non-object role catalog")
    raw_roles = payload.get("roles")
    if not isinstance(raw_roles, list):
        raise ValueError("Core returned an invalid role list")
    roles: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for index, raw in enumerate(raw_roles):
        if not isinstance(raw, dict):
            raise ValueError(f"Core returned a non-object role row at index {index}")
        role = raw.get("role")
        if not isinstance(role, str) or ROLE_NAME.fullmatch(role) is None:
            raise ValueError(f"Core returned an invalid role name at index {index}")
        if role in seen_roles:
            raise ValueError(f"Core returned duplicate role: {role}")
        seen_roles.add(role)

        raw_candidates = raw.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError(f"Core returned invalid candidates for role {role}")
        candidates: list[dict[str, Any]] = []
        seen_candidates: set[str] = set()
        for candidate_index, candidate in enumerate(raw_candidates):
            if not isinstance(candidate, dict):
                raise ValueError(
                    f"Core returned a non-object candidate for role {role}"
                )
            component = candidate.get("component")
            if not isinstance(component, str) or not component.strip():
                raise ValueError(
                    f"Core returned an invalid candidate for role {role} "
                    f"at index {candidate_index}"
                )
            if component in seen_candidates:
                continue
            seen_candidates.add(component)
            priority = candidate.get("priority", 0)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ValueError(
                    f"Core returned an invalid candidate priority for role {role}"
                )
            candidates.append(
                {
                    "component": component,
                    "priority": priority,
                    "exclusive": bool(candidate.get("exclusive", False)),
                    "explicit": bool(candidate.get("explicit", False)),
                    "declared": bool(candidate.get("declared", True)),
                    "state": str(candidate.get("state") or "declared"),
                }
            )

        exclusive = raw.get("exclusive", False)
        if not isinstance(exclusive, bool):
            raise ValueError(f"Core returned invalid exclusivity for role {role}")
        active = raw.get("active")
        preferred = raw.get("preferred")
        if active is not None and not isinstance(active, str):
            raise ValueError(f"Core returned an invalid active provider for role {role}")
        if preferred is not None and not isinstance(preferred, str):
            raise ValueError(
                f"Core returned an invalid preferred provider for role {role}"
            )
        raw_active_providers = raw.get(
            "active_providers", [active] if isinstance(active, str) and active else []
        )
        if not isinstance(raw_active_providers, list) or any(
            not isinstance(item, str) or not item for item in raw_active_providers
        ):
            raise ValueError(f"Core returned invalid active providers for role {role}")
        active_providers = list(dict.fromkeys(raw_active_providers))
        roles.append(
            {
                "role": role,
                "exclusive": exclusive,
                "preferred": preferred,
                "active": active,
                "active_providers": active_providers,
                "candidates": candidates,
                "available": bool(candidates),
            }
        )
    return {"roles": roles}


@dataclass(slots=True)
class DisplayMigrationTracker:
    """Accept ordered records for one live display migration at a time."""

    active_id: int | None = None
    active_phase: str = ""
    last_terminal_id: int | None = None
    record: dict[str, Any] = field(default_factory=dict)

    def consume(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        record = normalise_display_migration(payload)
        migration_id = int(record["id"])
        phase = str(record["phase"])
        ranks = {"planned": 0, "switching": 1, "succeeded": 2, "rolled-back": 2}

        if migration_id == self.last_terminal_id:
            return None
        if self.active_id is not None and migration_id != self.active_id:
            if phase != "planned":
                return None
        elif self.active_id == migration_id:
            if ranks[phase] <= ranks.get(self.active_phase, -1):
                return None

        self.record = record
        if phase in DISPLAY_MIGRATION_TERMINAL_PHASES:
            self.active_id = None
            self.active_phase = phase
            self.last_terminal_id = migration_id
        else:
            self.active_id = migration_id
            self.active_phase = phase
        return record


class SettingsModel:
    def __init__(self, client: SettingsClient) -> None:
        self.client = client

    @staticmethod
    def _safe(operation: Callable[[], dict[str, Any]]) -> OperationResult:
        try:
            return OperationResult(True, operation())
        except MipcRemoteError as exc:
            return OperationResult(
                False,
                exc.payload,
                exc.message,
                exc.code,
            )
        except (OSError, RuntimeError, TypeError, ValueError, TimeoutError) as exc:
            return OperationResult(False, message=str(exc), code="UNAVAILABLE")

    def overview(self) -> OperationResult:
        sections: dict[str, Any] = {
            "session": {
                "component": os.environ.get("MSYS_COMPONENT_ID", "standalone"),
                "package": os.environ.get("MSYS_PACKAGE_ID", "org.msys.settings"),
                "package_version": os.environ.get("MSYS_PACKAGE_VERSION", "development"),
                "runtime_dir": os.environ.get("MSYS_RUNTIME_DIR", "/run/msys/main"),
                "display": os.environ.get("DISPLAY") or "not provided",
            }
        }
        failures: list[dict[str, str]] = []
        for name, operation in (
            ("components", lambda: self._safe(self.client.list_components)),
            ("services", lambda: self._safe(self.client.discover)),
            ("isolation", lambda: self._safe(self.client.isolation_capabilities)),
            ("roles", self.list_roles),
        ):
            result = operation()
            if result.ok:
                sections[name] = result.data
            else:
                sections[name] = {"available": False}
                failures.append(
                    {"section": name, "code": result.code, "message": result.message}
                )
        sections["partial_errors"] = failures
        if len(failures) == 4:
            return OperationResult(
                False,
                sections,
                "MSYS control service is unavailable",
                "UNAVAILABLE",
            )
        message = "Some system information is unavailable" if failures else ""
        return OperationResult(True, sections, message)

    def get_layout(self) -> OperationResult:
        return self._safe(self.client.get_layout)

    def set_layout(
        self,
        profile: str,
        orientation: str,
        insets: str,
    ) -> OperationResult:
        try:
            normalised = validate_layout(profile, orientation, insets)
        except ValueError as exc:
            return OperationResult(False, message=str(exc), code="INVALID_LAYOUT")
        return self._safe(
            lambda: self.client.set_layout(profile, orientation, normalised)
        )

    def physical_rotation(self, *, refresh: bool = True) -> OperationResult:
        """Discover optional physical panel rotation without naming hardware.

        Logical layout belongs to the window-manager role.  Pixel/touch
        rotation belongs to a display or display-output HAL provider and is
        writable only when that provider explicitly advertises the field.
        """

        inventory = self.hal_inventory(refresh=refresh)
        if not inventory.ok:
            return self._typed_physical_rotation(
                inventory.message or inventory.code or "hal-unavailable"
            )
        candidates = [
            item
            for item in inventory.data.get("devices", [])
            if isinstance(item, dict)
            and item.get("domain") in {"display", "display-output"}
            and (
                "physical_rotation" in item.get("mutable", [])
                or (
                    isinstance(item.get("metadata"), dict)
                    and "physical_rotation_control" in item["metadata"]
                )
            )
        ]
        candidates.sort(
            key=lambda item: (
                0 if "physical_rotation" in item.get("mutable", []) else 1,
                str(item.get("id") or ""),
            )
        )
        if not candidates:
            return self._typed_physical_rotation(
                "provider-does-not-expose-physical-rotation"
            )
        identifier = str(candidates[0].get("id") or "")
        state = self.hal_get_state(identifier, refresh=refresh)
        if not state.ok:
            return OperationResult(
                True,
                {
                    "available": False,
                    "writable": False,
                    "device": identifier,
                    "reason": state.message or state.code or "state-unavailable",
                },
            )
        values = state.data.get("values", {})
        mutable = state.data.get("mutable", [])
        rotation = values.get("physical_rotation") if isinstance(values, dict) else None
        valid = rotation in {"normal", "right", "left", "inverted"}
        return OperationResult(
            True,
            {
                "available": valid,
                "writable": valid and "physical_rotation" in mutable,
                "device": identifier,
                "value": rotation if valid else "normal",
                "reason": (
                    ""
                    if valid and "physical_rotation" in mutable
                    else str(
                        values.get("physical_rotation_control")
                        if isinstance(values, dict)
                        else "state-invalid"
                    )
                ),
                "provider": str(state.data.get("provider") or ""),
            },
        )

    def _typed_physical_rotation(self, fallback_reason: str) -> OperationResult:
        """Bridge the optional typed display-output control on native HAL v1.

        The resident native manager intentionally does not broker other HAL
        providers.  A display-output may still expose the same truthful
        mutable field through its typed control interface.
        """

        if not callable(getattr(self.client, "ch347_status", None)):
            return OperationResult(
                True,
                {
                    "available": False,
                    "writable": False,
                    "reason": fallback_reason,
                },
            )
        typed = self.ch347_status()
        if not typed.ok:
            return OperationResult(
                True,
                {
                    "available": False,
                    "writable": False,
                    "reason": fallback_reason,
                },
            )
        state = typed.data.get("state", {})
        mutable = typed.data.get("mutable", [])
        rotation = state.get("physical_rotation") if isinstance(state, dict) else None
        if rotation not in {"normal", "right", "left", "inverted"}:
            return OperationResult(
                True,
                {
                    "available": False,
                    "writable": False,
                    "reason": fallback_reason,
                },
            )
        control = str(state.get("physical_rotation_control") or "unavailable")
        if control == "unavailable":
            return OperationResult(
                True,
                {
                    "available": False,
                    "writable": False,
                    "device": CH347_DEVICE,
                    "value": rotation,
                    "reason": fallback_reason,
                    "provider": "typed-display-output",
                },
            )
        writable = "physical_rotation" in mutable
        return OperationResult(
            True,
            {
                "available": True,
                "writable": writable,
                "device": CH347_DEVICE,
                "value": rotation,
                "reason": "" if writable else control,
                "provider": "typed-display-output",
            },
        )

    def set_physical_rotation(self, device: str, rotation: str) -> OperationResult:
        if not isinstance(device, str) or not device:
            return OperationResult(
                False,
                message="Physical rotation device is unavailable",
                code="ROTATION_UNAVAILABLE",
            )
        if rotation not in {"normal", "right", "left", "inverted"}:
            return OperationResult(
                False,
                message="Unsupported physical rotation",
                code="INVALID_ROTATION",
            )
        if device == CH347_DEVICE:
            result = self._safe(
                lambda: self.client.ch347_set_physical_rotation(rotation)
            )
            return _normalise_ch347_result(result, normalise_ch347_status)
        return self.hal_set_state(device, {"physical_rotation": rotation})

    def desktop_preferences(self) -> OperationResult:
        result = self._safe(self.client.get_desktop_preferences)
        if not result.ok:
            return result
        try:
            result.data = normalise_desktop_preferences(result.data)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": result.data},
                str(exc),
                "SHELL_BAD_RESPONSE",
            )
        return result

    def set_desktop_preferences(
        self,
        layout: str,
        wallpaper_color: str,
        accent_color: str,
        icon_size: int | str,
        show_labels: bool,
        sort: str,
    ) -> OperationResult:
        try:
            preferences = validate_desktop_preferences(
                {
                    "layout": layout,
                    "wallpaper_color": wallpaper_color,
                    "accent_color": accent_color,
                    "icon_size": icon_size,
                    "show_labels": show_labels,
                    "sort": sort,
                }
            )
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                message=str(exc),
                code="INVALID_PREFERENCES",
            )
        result = self._safe(lambda: self.client.set_desktop_preferences(preferences))
        if not result.ok:
            return result
        try:
            result.data = normalise_desktop_preferences(result.data)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": result.data},
                str(exc),
                "SHELL_BAD_RESPONSE",
            )
        return result

    def list_roles(self) -> OperationResult:
        result = self._safe(self.client.list_roles)
        if not result.ok:
            return result
        try:
            result.data = normalise_role_catalog(result.data)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": result.data},
                str(exc),
                "ROLE_BAD_RESPONSE",
            )
        return result

    def display_settings(self, *, refresh: bool = False) -> OperationResult:
        """Combine the replaceable display contracts into one page snapshot.

        The window manager, core role registry, and HAL manager are independent
        optional services.  A missing provider therefore degrades one section
        instead of making the whole Settings application unusable.
        """

        sections: dict[str, Any] = {}
        failures: list[dict[str, str]] = []
        successful_calls = 0

        layout = self._safe(self.client.get_layout)
        if layout.ok:
            successful_calls += 1
            sections["layout"] = {"available": True, "value": layout.data}
        else:
            sections["layout"] = _unavailable_section(layout)
            failures.append(_section_failure("layout", layout))

        roles = self.list_roles()
        if roles.ok:
            successful_calls += 1
            output_role = next(
                (
                    item
                    for item in roles.data.get("roles", [])
                    if item.get("role") == "display-output"
                ),
                None,
            )
            sections["output"] = {
                "available": output_role is not None,
                "role": output_role or {},
                **(
                    {}
                    if output_role is not None
                    else {
                        "code": "NO_PROVIDER",
                        "message": "No display-output role is installed",
                    }
                ),
            }
            if output_role is None:
                failures.append(
                    {
                        "section": "output",
                        "code": "NO_PROVIDER",
                        "message": "No display-output role is installed",
                    }
                )
        else:
            sections["output"] = _unavailable_section(roles)
            failures.append(_section_failure("output", roles))

        hal = self.hal_inventory(refresh=refresh)
        if hal.ok:
            successful_calls += 1
            display_domains = [
                item
                for item in hal.data.get("domains", [])
                if item.get("domain") in {"display", "display-output"}
            ]
            display_devices = [
                item
                for item in hal.data.get("devices", [])
                if item.get("domain") in {"display", "display-output"}
            ]
            sections["hal"] = {
                "available": bool(display_domains or display_devices),
                "domains": display_domains,
                "devices": display_devices,
                "provider_management": hal.data.get(
                    "provider_management", {"available": False}
                ),
                "inventory_status": hal.data.get(
                    "inventory_status", {"available": True}
                ),
                **(
                    {}
                    if display_domains or display_devices
                    else {
                        "code": "NO_DISPLAY_DEVICE",
                        "message": "HAL reported no display domain or device",
                    }
                ),
            }
            if not display_domains and not display_devices:
                failures.append(
                    {
                        "section": "hal.display",
                        "code": "NO_DISPLAY_DEVICE",
                        "message": "HAL reported no display domain or device",
                    }
                )
            for failure in hal.data.get("partial_errors", []):
                if isinstance(failure, dict):
                    failures.append(
                        {
                            "section": "hal." + str(failure.get("section", "unknown")),
                            "code": str(failure.get("code", "UNAVAILABLE")),
                            "message": str(failure.get("message", "")),
                        }
                    )
        else:
            sections["hal"] = _unavailable_section(hal)
            failures.append(_section_failure("hal", hal))

        sections["partial_errors"] = failures
        if successful_calls == 0:
            return OperationResult(
                False,
                sections,
                "Display services are unavailable",
                "UNAVAILABLE",
            )
        return OperationResult(
            True,
            sections,
            "Some display settings are unavailable" if failures else "",
        )

    def select_role(self, role: str, provider: str) -> OperationResult:
        if not role or not provider:
            return OperationResult(
                False,
                message="Select both a role and a provider",
                code="INVALID_SELECTION",
            )
        return self._safe(lambda: self.client.select_role(role, provider))

    def reset_role(self, role: str) -> OperationResult:
        if not role:
            return OperationResult(False, message="Select a role", code="INVALID_SELECTION")
        return self._safe(lambda: self.client.reset_role(role))

    def input_method_status(self) -> OperationResult:
        result = self._safe(self.client.input_method_status)
        return _normalise_input_method_result(result)

    def toggle_input_method(self) -> OperationResult:
        result = self._safe(self.client.toggle_input_method)
        return _normalise_input_method_result(result)

    @staticmethod
    def _normalise_audio_result(result: OperationResult) -> OperationResult:
        if not result.ok:
            return result
        try:
            result.data = normalise_audio_state(result.data)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": result.data},
                str(exc),
                "AUDIO_BAD_RESPONSE",
            )
        return result

    def audio_state(self, *, refresh: bool = True) -> OperationResult:
        result = self._safe(
            lambda: self.client.audio_get_state(refresh=refresh)
        )
        return self._normalise_audio_result(result)

    @staticmethod
    def _normalise_audio_devices_result(
        result: OperationResult,
        *,
        action_response: bool = False,
    ) -> OperationResult:
        if not result.ok:
            return result
        payload = result.data
        if action_response and isinstance(payload, dict):
            payload = {
                "schema": "msys.audio-devices.v1",
                "devices": payload.get("devices"),
            }
        try:
            result.data = normalise_audio_devices(payload)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": result.data},
                str(exc),
                "AUDIO_BAD_RESPONSE",
            )
        return result

    def audio_devices(self, *, refresh: bool = True) -> OperationResult:
        state = self.audio_state(refresh=refresh)
        if not state.ok:
            return state
        controller_registered = state.data.get("controller_registered") is True
        if not controller_registered:
            return OperationResult(
                True,
                {
                    "schema": "msys.audio-devices.v1",
                    "devices": [],
                    "controller_registered": False,
                    "reason": str(state.data.get("reason") or "controller-not-registered"),
                    "backend": str(state.data.get("backend") or ""),
                },
            )
        result = self._normalise_audio_devices_result(
            self._safe(lambda: self.client.audio_list_devices(refresh=refresh))
        )
        if result.ok:
            result.data.update(
                {
                    "controller_registered": True,
                    "reason": state.data.get("reason"),
                    "backend": state.data.get("backend"),
                }
            )
        return result

    def audio_scan_devices(self, timeout_ms: object = 15000) -> OperationResult:
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1000 <= timeout_ms <= 30000
        ):
            return OperationResult(
                False,
                message="Bluetooth scan timeout must be 1000..30000 ms",
                code="AUDIO_BAD_PAYLOAD",
            )
        return self._normalise_audio_devices_result(
            self._safe(lambda: self.client.audio_scan(timeout_ms=timeout_ms))
        )

    def audio_device_action(self, action: str, address: object) -> OperationResult:
        if action not in {"pair", "connect", "disconnect", "forget"}:
            return OperationResult(
                False,
                message="Unsupported Bluetooth audio action",
                code="AUDIO_BAD_PAYLOAD",
            )
        try:
            payload = bluetooth_address_request(address)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="AUDIO_BAD_PAYLOAD")
        return self._normalise_audio_devices_result(
            self._safe(lambda: self.client.audio_device_action(action, payload)),
            action_response=True,
        )

    def audio_set_volume(
        self,
        percent: object,
        output: str = "",
    ) -> OperationResult:
        try:
            payload = volume_request(percent, output)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="AUDIO_BAD_PAYLOAD")
        return self._normalise_audio_result(
            self._safe(lambda: self.client.audio_set_volume(payload))
        )

    def audio_set_muted(
        self,
        muted: object,
        output: str = "",
    ) -> OperationResult:
        try:
            payload = muted_request(muted, output)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="AUDIO_BAD_PAYLOAD")
        return self._normalise_audio_result(
            self._safe(lambda: self.client.audio_set_muted(payload))
        )

    def audio_select_output(self, output: str) -> OperationResult:
        try:
            payload = output_request(output)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="AUDIO_BAD_PAYLOAD")
        return self._normalise_audio_result(
            self._safe(lambda: self.client.audio_select_output(payload))
        )

    def audio_configure_player(
        self,
        enabled: object,
        server: object,
        name: object,
    ) -> OperationResult:
        try:
            payload = player_request(enabled, server, name)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="AUDIO_BAD_PAYLOAD")
        return self._normalise_audio_result(
            self._safe(lambda: self.client.audio_configure_player(payload))
        )

    def hal_inventory(self, *, refresh: bool = True) -> OperationResult:
        inventory = self._safe(lambda: self.client.hal_inventory(refresh=refresh))
        base_providers = self._safe(
            lambda: self.client.hal_list_providers(refresh=refresh)
        )
        providers = self._hal_provider_catalog(
            inventory.data if inventory.ok else {},
            base_providers,
        )
        if not inventory.ok:
            if not providers.ok:
                inventory.data = {
                    "inventory_status": _unavailable_section(inventory),
                    "provider_management": _unavailable_section(providers),
                    "partial_errors": [
                        _section_failure("inventory", inventory),
                        _section_failure("providers", providers),
                    ],
                }
                return inventory
            try:
                domains = normalise_hal_domains({}, providers.data)
            except (TypeError, ValueError) as exc:
                return OperationResult(
                    False,
                    {
                        "inventory_status": _unavailable_section(inventory),
                        "providers": providers.data,
                    },
                    str(exc),
                    "HAL_BAD_RESPONSE",
                )
            return OperationResult(
                True,
                {
                    "devices": [],
                    "domains": domains,
                    "raw": {"inventory": {}, "providers": providers.data},
                    "revision": _hal_catalog_revision(providers.data),
                    "inventory_status": _unavailable_section(inventory),
                    "provider_management": {
                        "available": True,
                        "probe_supported": bool(
                            providers.data.get("probe_supported", False)
                        ),
                        "degraded": bool(
                            providers.data.get("partial_errors", [])
                        ),
                    },
                    "partial_errors": [
                        _section_failure("inventory", inventory),
                        *list(providers.data.get("partial_errors", [])),
                    ],
                },
                "HAL inventory is unavailable; provider management remains available",
            )
        raw_inventory = inventory.data
        try:
            domains = normalise_hal_domains(raw_inventory, {})
            devices = normalise_hal_inventory(raw_inventory, domains)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"inventory": raw_inventory},
                str(exc),
                "HAL_BAD_RESPONSE",
            )
        provider_payload = providers.data if providers.ok else {}
        management_error: dict[str, Any] | None = None
        if providers.ok:
            try:
                domains = normalise_hal_domains(raw_inventory, provider_payload)
                devices = normalise_hal_inventory(raw_inventory, domains)
            except (TypeError, ValueError) as exc:
                management_error = {
                    "available": False,
                    "code": "HAL_BAD_RESPONSE",
                    "message": str(exc),
                }
        else:
            management_error = {
                "available": False,
                "code": providers.code,
                "message": providers.message,
            }
        inventory.data = {
            "devices": devices,
            "domains": domains,
            "revision": max(
                _hal_catalog_revision(raw_inventory),
                _hal_catalog_revision(provider_payload),
            ),
            "raw": {
                "inventory": raw_inventory,
                "providers": provider_payload,
            },
            "provider_management": (
                {
                    "available": True,
                    "probe_supported": bool(
                        provider_payload.get("probe_supported", False)
                    ),
                    "degraded": bool(provider_payload.get("partial_errors", [])),
                }
                if management_error is None
                else management_error
            ),
            "inventory_status": {"available": True},
            "partial_errors": (
                []
                if management_error is None
                else [
                    {
                        "section": "providers",
                        "code": str(management_error.get("code", "UNAVAILABLE")),
                        "message": str(management_error.get("message", "")),
                    }
                ]
            ) + (
                list(provider_payload.get("partial_errors", []))
                if management_error is None
                else []
            ),
        }
        if management_error is not None:
            inventory.message = "HAL devices are available; provider management is unavailable"
        elif provider_payload.get("partial_errors"):
            inventory.message = "HAL provider health is partially unavailable"
        return inventory

    def _hal_provider_catalog(
        self,
        inventory_payload: dict[str, Any],
        base: OperationResult,
    ) -> OperationResult:
        if not base.ok:
            return base
        try:
            initial_domains = normalise_hal_domains(inventory_payload, base.data)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"providers": base.data},
                str(exc),
                "HAL_BAD_RESPONSE",
            )
        raw_rows = base.data.get("providers", [])
        if not isinstance(raw_rows, list):
            return OperationResult(
                False,
                {"providers": base.data},
                "HAL manager returned an invalid provider list",
                "HAL_BAD_RESPONSE",
            )
        merged = {
            str(row.get("domain")): dict(row)
            for row in raw_rows
            if isinstance(row, dict) and row.get("domain")
        }
        revisions = [_hal_catalog_revision(inventory_payload), _hal_catalog_revision(base.data)]
        partial_errors: list[dict[str, str]] = []
        probe_supported = False
        for item in initial_domains:
            domain_name = str(item["domain"])
            detail = self._safe(
                lambda name=domain_name: self.client.hal_list_providers(
                    name,
                    refresh=False,
                    probe=True,
                )
            )
            legacy = False
            if not detail.ok and detail.code in HAL_LEGACY_FEATURE_ERRORS:
                legacy = True
                detail = self._safe(
                    lambda name=domain_name: self.client.hal_list_providers(
                        name,
                        refresh=False,
                    )
                )
            if not detail.ok:
                partial_errors.append(_section_failure(f"providers.{domain_name}", detail))
                if domain_name in merged:
                    merged[domain_name] = _hal_failed_probe_row(
                        merged[domain_name],
                        domain_name,
                        detail.code,
                    )
                continue
            try:
                row = _hal_provider_row(detail.data, domain_name)
                normalise_hal_domains({}, {"providers": [row]})
            except (TypeError, ValueError) as exc:
                partial_errors.append({
                    "section": f"providers.{domain_name}",
                    "code": "HAL_BAD_RESPONSE",
                    "message": str(exc),
                })
                if domain_name in merged:
                    merged[domain_name] = _hal_failed_probe_row(
                        merged[domain_name],
                        domain_name,
                        "HAL_BAD_RESPONSE",
                    )
                continue
            merged[domain_name] = row
            revisions.append(_hal_catalog_revision(detail.data))
            if not legacy:
                probe_supported = True
        return OperationResult(True, {
            "schema": str(
                base.data.get("schema") or "org.msys.hal.manager.v1"
            ),
            "revision": max(revisions, default=0),
            "providers": [
                merged[name]
                for name in sorted(merged)
            ],
            "probe_supported": probe_supported,
            "partial_errors": partial_errors,
        })

    def hal_get_state(self, device: str, *, refresh: bool = True) -> OperationResult:
        if not device:
            return OperationResult(False, message="Select a HAL device", code="NO_DEVICE")
        result = self._safe(
            lambda: self.client.hal_get_state(device, refresh=refresh)
        )
        if not result.ok:
            return result
        try:
            result.data = normalise_hal_state(result.data, device)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="HAL_BAD_RESPONSE")
        return result

    def hal_set_state(self, device: str, state: dict[str, Any]) -> OperationResult:
        if not device:
            return OperationResult(False, message="Select a HAL device", code="NO_DEVICE")
        if not isinstance(state, dict) or not state:
            return OperationResult(
                False,
                message="HAL changes must be a non-empty JSON object",
                code="BAD_STATE",
            )
        result = self._safe(lambda: self.client.hal_set_state(device, state))
        if not result.ok:
            return result
        try:
            result.data = normalise_hal_state(result.data, device)
        except (TypeError, ValueError) as exc:
            return OperationResult(False, message=str(exc), code="HAL_BAD_RESPONSE")
        return result

    def select_hal_provider(
        self,
        domain: str,
        provider: str,
        *,
        expected_revision: int | None = None,
        allow_unavailable: bool = False,
    ) -> OperationResult:
        if (
            HAL_DOMAIN.fullmatch(domain) is None
            or HAL_COMPONENT.fullmatch(provider) is None
        ):
            return OperationResult(
                False,
                message="Select both a HAL domain and provider",
                code="INVALID_SELECTION",
            )
        if (
            expected_revision is not None
            and (
                isinstance(expected_revision, bool)
                or not isinstance(expected_revision, int)
                or expected_revision < 0
            )
        ):
            return OperationResult(
                False,
                message="HAL provider revision is invalid",
                code="INVALID_REVISION",
            )
        if expected_revision is None and not allow_unavailable:
            result = self._safe(
                lambda: self.client.hal_select_provider(domain, provider)
            )
        else:
            result = self._safe(lambda: self.client.hal_select_provider(
                domain,
                provider,
                expected_revision=expected_revision,
                allow_unavailable=allow_unavailable,
            ))
        if (
            expected_revision is not None
            and not allow_unavailable
            and not result.ok
            and result.code in HAL_LEGACY_FEATURE_ERRORS
        ):
            return self._safe(lambda: self.client.hal_select_provider(
                domain,
                provider,
            ))
        return result

    def reset_hal_provider(
        self,
        domain: str,
        *,
        expected_revision: int | None = None,
    ) -> OperationResult:
        if HAL_DOMAIN.fullmatch(domain) is None:
            return OperationResult(
                False,
                message="Select a HAL domain",
                code="INVALID_SELECTION",
            )
        if (
            expected_revision is not None
            and (
                isinstance(expected_revision, bool)
                or not isinstance(expected_revision, int)
                or expected_revision < 0
            )
        ):
            return OperationResult(
                False,
                message="HAL provider revision is invalid",
                code="INVALID_REVISION",
            )
        if expected_revision is None:
            result = self._safe(lambda: self.client.hal_reset_provider(domain))
        else:
            result = self._safe(lambda: self.client.hal_reset_provider(
                domain,
                expected_revision=expected_revision,
            ))
        if (
            expected_revision is not None
            and not result.ok
            and result.code in HAL_LEGACY_FEATURE_ERRORS
        ):
            return self._safe(lambda: self.client.hal_reset_provider(domain))
        return result

    def ch347_status(self) -> OperationResult:
        result = self._safe(self.client.ch347_status)
        return _normalise_ch347_result(result, normalise_ch347_status)

    def ch347_set_fps(self, fps: Any, idle_fps: Any) -> OperationResult:
        try:
            selected_fps, selected_idle = validate_ch347_fps(fps, idle_fps)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                message=str(exc),
                code="INVALID_CH347_CONFIG",
            )
        result = self._safe(
            lambda: self.client.ch347_set_fps(selected_fps, selected_idle)
        )
        return _normalise_ch347_result(result, normalise_ch347_fps_response)

    def ch347_get_debug(self) -> OperationResult:
        result = self._safe(self.client.ch347_get_debug)
        return _normalise_ch347_result(result, normalise_ch347_debug_response)

    def ch347_set_debug(self, settings: Any) -> OperationResult:
        try:
            selected = validate_ch347_debug_request(settings)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                message=str(exc),
                code="INVALID_CH347_CONFIG",
            )
        request: bool | dict[str, Any] = (
            selected["enabled"] if isinstance(settings, bool) else selected
        )
        result = self._safe(lambda: self.client.ch347_set_debug(request))
        return _normalise_ch347_result(result, normalise_ch347_debug_response)

    def ch347_set_touch_calibration(
        self,
        calibration: dict[str, Any],
    ) -> OperationResult:
        try:
            selected = validate_ch347_calibration(calibration, require_all=True)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                message=str(exc),
                code="INVALID_CH347_CONFIG",
            )
        result = self._safe(
            lambda: self.client.ch347_set_touch_calibration(selected)
        )
        return _normalise_ch347_result(
            result,
            normalise_ch347_calibration_response,
        )

    def ch347_restart(self) -> OperationResult:
        result = self._safe(self.client.ch347_restart)
        return _normalise_ch347_result(result, normalise_ch347_status)

    def request_update(
        self,
        action: str,
        source: str,
        package: str,
    ) -> OperationResult:
        source = source.strip()
        package = package.strip()
        if not source:
            return OperationResult(False, message="Update source is required", code="NO_SOURCE")
        if package and package != "all" and PACKAGE_ID.fullmatch(package) is None:
            return OperationResult(False, message="Invalid package id", code="BAD_PACKAGE")
        operation = {
            "check": self.client.request_update_check,
            "apply": self.client.request_update_apply,
        }.get(action)
        if operation is None:
            return OperationResult(False, message="Unknown update action", code="BAD_ACTION")
        response = self._safe(lambda: operation(source, package or None))
        if not response.ok:
            return response
        return normalise_install_agent_result(
            response.data,
            "check_updates" if action == "check" else "apply_updates",
        )

    def request_rollback(self, package: str) -> OperationResult:
        package = package.strip()
        if PACKAGE_ID.fullmatch(package) is None:
            return OperationResult(
                False,
                message="A valid package id is required for rollback",
                code="BAD_PACKAGE",
            )
        response = self._safe(lambda: self.client.request_rollback(package))
        if not response.ok:
            return response
        return normalise_install_agent_result(response.data, "rollback")

    def installed_packages(self) -> OperationResult:
        response = self._safe(self.client.request_registry)
        if not response.ok:
            return _normalise_install_agent_error(response, "registry")
        terminal = normalise_install_agent_result(response.data, "registry")
        if not terminal.ok:
            return terminal
        try:
            registry = normalise_installed_registry(terminal.data.get("result"))
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": terminal.data},
                str(exc),
                "INSTALL_REGISTRY_BAD_RESPONSE",
            )
        return OperationResult(
            True,
            {
                "response": terminal.data,
                "registry": registry,
                "packages": registry["packages"],
            },
            f"{len(registry['packages'])} installed package(s)",
        )

    def request_uninstall(self, package: str) -> OperationResult:
        package = package.strip()
        if PACKAGE_ID.fullmatch(package) is None:
            return OperationResult(
                False,
                message="A valid package id is required for uninstall",
                code="BAD_PACKAGE",
            )
        response = self._safe(lambda: self.client.request_uninstall(package))
        if not response.ok:
            return _normalise_install_agent_error(response, "uninstall")
        return normalise_install_agent_result(response.data, "uninstall")

    def display_migration_status(self, migration_id: int) -> OperationResult:
        if isinstance(migration_id, bool) or not isinstance(migration_id, int) or migration_id <= 0:
            return OperationResult(
                False,
                message="Display migration id must be a positive integer",
                code="BAD_MIGRATION_ID",
            )
        response = self._safe(
            lambda: self.client.display_migration_status(migration_id)
        )
        if not response.ok:
            return response
        if not isinstance(response.data, dict):
            return OperationResult(
                False,
                {"response": response.data},
                "Core returned a non-object display migration response",
                "DISPLAY_MIGRATION_BAD_RESPONSE",
            )
        migration = response.data.get("migration")
        if not isinstance(migration, dict):
            return OperationResult(
                False,
                {"response": response.data},
                "Core returned no display migration record",
                "DISPLAY_MIGRATION_BAD_RESPONSE",
            )
        try:
            normalised = normalise_display_migration(migration)
        except (TypeError, ValueError) as exc:
            return OperationResult(
                False,
                {"response": response.data},
                str(exc),
                "DISPLAY_MIGRATION_BAD_RESPONSE",
            )
        return OperationResult(True, normalised)


def normalise_install_agent_result(
    payload: dict[str, Any],
    expected_operation: str,
) -> OperationResult:
    """Turn the install agent's terminal envelope into one UI operation."""

    if not isinstance(payload, dict):
        return OperationResult(
            False,
            {"response": payload},
            "Install agent returned a non-object terminal result",
            "INSTALL_AGENT_BAD_RESPONSE",
        )
    if (
        payload.get("schema") != INSTALL_AGENT_RESULT_SCHEMA
        or payload.get("operation") != expected_operation
        or not isinstance(payload.get("ok"), bool)
    ):
        return OperationResult(
            False,
            {"response": payload},
            "Install agent returned an invalid terminal result envelope",
            "INSTALL_AGENT_BAD_RESPONSE",
        )
    envelope = dict(payload)
    if payload["ok"]:
        return OperationResult(
            True,
            envelope,
            f"{expected_operation.replace('_', ' ')} completed",
        )

    code = "INSTALL_AGENT_OPERATION_FAILED"
    message = f"{expected_operation.replace('_', ' ')} completed with errors"
    result = payload.get("result")
    if isinstance(result, dict):
        errors = result.get("errors")
        if isinstance(errors, list):
            first = next((item for item in errors if isinstance(item, dict)), None)
            if first is not None:
                if isinstance(first.get("code"), str) and first["code"]:
                    code = str(first["code"])
                if isinstance(first.get("message"), str) and first["message"]:
                    message = str(first["message"])
    return OperationResult(False, envelope, message, code)


def _normalise_install_agent_error(
    result: OperationResult,
    expected_operation: str,
) -> OperationResult:
    payload = result.data
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != INSTALL_AGENT_ERROR_SCHEMA
        or payload.get("operation") != expected_operation
    ):
        return OperationResult(
            False,
            {"response": payload},
            "Install agent returned an invalid structured error envelope",
            "INSTALL_AGENT_BAD_RESPONSE",
        )
    return result


def normalise_installed_registry(payload: Any) -> dict[str, Any]:
    """Validate and sort the package registry shown by the Apps page."""

    if not isinstance(payload, dict):
        raise TypeError("Install agent returned a non-object package registry")
    if payload.get("schema") != INSTALLED_REGISTRY_SCHEMA:
        raise ValueError("Install agent returned an invalid package registry schema")
    raw_packages = payload.get("packages")
    if not isinstance(raw_packages, list):
        raise ValueError("Install agent returned an invalid package list")
    packages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_packages):
        if not isinstance(raw, dict):
            raise ValueError(f"Install agent returned a non-object package at index {index}")
        package = raw.get("package")
        version = raw.get("version")
        if not isinstance(package, str) or PACKAGE_ID.fullmatch(package) is None:
            raise ValueError(f"Install agent returned an invalid package id at index {index}")
        if package in seen:
            raise ValueError(f"Install agent returned duplicate package: {package}")
        if not isinstance(version, str) or not version or len(version) > 128:
            raise ValueError(f"Install agent returned an invalid version for {package}")
        path = raw.get("path", "")
        if not isinstance(path, str):
            raise ValueError(f"Install agent returned an invalid path for {package}")
        seen.add(package)
        packages.append({**dict(raw), "package": package, "version": version, "path": path})
    return {
        "schema": INSTALLED_REGISTRY_SCHEMA,
        "packages": sorted(packages, key=lambda item: item["package"]),
    }


def uninstall_confirmation(package: str, version: str) -> tuple[str, str]:
    """Return the explicit destructive-action prompt used by every frontend."""

    return (
        "Uninstall package",
        f"Remove {package!r} version {version!r}?\n\n"
        "Its running components will be stopped and Core must pass the "
        "catalog health gate. This operation cannot be undone unless the "
        "package archive is available for reinstall.",
    )


def normalise_display_migration(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a live ``msys.display.migration`` event/status record."""

    if not isinstance(payload, dict):
        raise TypeError("Display migration record must be an object")
    if payload.get("schema") != DISPLAY_MIGRATION_SCHEMA:
        raise ValueError("Core returned an invalid display migration schema")
    migration_id = payload.get("id")
    if (
        isinstance(migration_id, bool)
        or not isinstance(migration_id, int)
        or migration_id <= 0
    ):
        raise ValueError("Core returned an invalid display migration id")
    if payload.get("role") != "display-output":
        raise ValueError("Core returned a display migration for another role")
    phase = payload.get("phase")
    if phase not in DISPLAY_MIGRATION_PHASES:
        raise ValueError("Core returned an invalid display migration phase")
    if phase == "rolled-back":
        error = payload.get("error")
        if not isinstance(error, dict):
            raise ValueError("Rolled-back display migration has no structured error")
        if not isinstance(error.get("code"), str) or not error["code"]:
            raise ValueError("Rolled-back display migration has no error code")
        if not isinstance(error.get("message"), str) or not error["message"]:
            raise ValueError("Rolled-back display migration has no error message")
        if not isinstance(payload.get("rollback_complete"), bool):
            raise ValueError("Rolled-back display migration has invalid rollback health")
    return dict(payload)


def validate_layout(
    profile: str,
    orientation: str,
    insets: str,
) -> str | dict[str, int]:
    if profile not in LAYOUT_PROFILES:
        raise ValueError(f"Unsupported layout profile: {profile}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"Unsupported orientation: {orientation}")
    value = insets.strip()
    if value == "auto":
        return "auto"
    parts = value.split(",")
    if len(parts) != 4 or any(part.strip() != part or not part.isdigit() for part in parts):
        raise ValueError("Insets must be 'auto' or top,right,bottom,left")
    edges = [int(part) for part in parts]
    if any(edge > 32767 for edge in edges):
        raise ValueError("Insets must be between 0 and 32767")
    return dict(zip(("top", "right", "bottom", "left"), edges, strict=True))


def validate_desktop_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("Desktop preferences must be an object")
    required = set(DEFAULT_DESKTOP_PREFERENCES)
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required)
    if missing:
        raise ValueError(f"Desktop preferences are missing: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Unknown desktop preferences: {', '.join(unknown)}")

    layout = payload["layout"]
    if layout not in DESKTOP_LAYOUTS:
        raise ValueError(f"Unsupported desktop layout: {layout}")
    sort = payload["sort"]
    if sort not in DESKTOP_SORTS:
        raise ValueError(f"Unsupported desktop sort order: {sort}")
    wallpaper = payload["wallpaper_color"]
    accent = payload["accent_color"]
    if not isinstance(wallpaper, str) or RGB_COLOR.fullmatch(wallpaper) is None:
        raise ValueError("Wallpaper color must use #RRGGBB")
    if not isinstance(accent, str) or RGB_COLOR.fullmatch(accent) is None:
        raise ValueError("Accent color must use #RRGGBB")
    raw_icon_size = payload["icon_size"]
    if isinstance(raw_icon_size, bool):
        raise ValueError("Icon size must be a whole number from 40 to 96")
    try:
        icon_size = int(raw_icon_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Icon size must be a whole number from 40 to 96") from exc
    if isinstance(raw_icon_size, float) and not raw_icon_size.is_integer():
        raise ValueError("Icon size must be a whole number from 40 to 96")
    if isinstance(raw_icon_size, str) and str(icon_size) != raw_icon_size.strip():
        raise ValueError("Icon size must be a whole number from 40 to 96")
    if not 40 <= icon_size <= 96:
        raise ValueError("Icon size must be from 40 to 96")
    show_labels = payload["show_labels"]
    if not isinstance(show_labels, bool):
        raise ValueError("Show labels must be true or false")
    return {
        "layout": str(layout),
        "wallpaper_color": wallpaper.upper(),
        "accent_color": accent.upper(),
        "icon_size": icon_size,
        "show_labels": show_labels,
        "sort": str(sort),
    }


def normalise_desktop_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("Launcher returned a non-object preferences response")
    schema = payload.get("schema")
    if schema is not None and schema != SHELL_PREFERENCES_SCHEMA:
        raise ValueError(f"Launcher returned unsupported preferences schema: {schema}")
    raw = payload.get("preferences", payload)
    if not isinstance(raw, dict):
        raise TypeError("Launcher returned non-object desktop preferences")
    preference_fields = set(DEFAULT_DESKTOP_PREFERENCES)
    selected = {key: raw[key] for key in preference_fields if key in raw}
    try:
        preferences = validate_desktop_preferences(selected)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Launcher returned invalid desktop preferences: {exc}") from exc
    result: dict[str, Any] = {"preferences": preferences}
    if "revision" in payload:
        result["revision"] = payload["revision"]
    if schema is not None:
        result["schema"] = str(schema)
    return result


def _ch347_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("CH347 control returned a non-object response")
    schema = payload.get("schema")
    if schema != CH347_CONTROL_SCHEMA:
        raise ValueError(f"CH347 control returned unsupported schema: {schema}")
    device = payload.get("device")
    if device != CH347_DEVICE:
        raise ValueError("CH347 control returned a response for another device")
    return payload


def _bounded_integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a whole number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be from {minimum} to {maximum}")
    return value


def validate_ch347_fps(fps: Any, idle_fps: Any) -> tuple[int, int]:
    selected_fps = _bounded_integer(fps, "FPS", 1, 240)
    selected_idle = _bounded_integer(idle_fps, "Idle FPS", 0, 60)
    if selected_idle > selected_fps:
        raise ValueError("Idle FPS must not exceed FPS")
    return selected_fps, selected_idle


def validate_ch347_debug_overlay(overlay: Any) -> dict[str, Any]:
    if not isinstance(overlay, dict):
        raise TypeError("Display debug overlay must be an object")
    expected = {"enabled", "alpha", "scale", "items", "interval_ms"}
    unknown = sorted(set(overlay) - expected)
    missing = sorted(expected - set(overlay))
    if unknown:
        raise ValueError(
            "Display debug overlay has unknown fields: " + ", ".join(unknown)
        )
    if missing:
        raise ValueError(
            "Display debug overlay is missing fields: " + ", ".join(missing)
        )
    enabled = overlay["enabled"]
    if not isinstance(enabled, bool):
        raise TypeError("Display debug overlay enabled must be true or false")
    alpha = _bounded_integer(
        overlay["alpha"], "Display debug overlay alpha", 0, 255
    )
    scale = _bounded_integer(overlay["scale"], "Display debug overlay scale", 1, 2)
    if scale not in {1, 2}:
        raise ValueError("Display debug overlay scale must be 1 or 2")
    interval_ms = _bounded_integer(
        overlay["interval_ms"],
        "Display debug overlay interval",
        250,
        5000,
    )
    items = overlay["items"]
    if not isinstance(items, list) or not items:
        raise TypeError("Display debug overlay items must be a non-empty list")
    if any(not isinstance(item, str) for item in items):
        raise TypeError("Display debug overlay item names must be strings")
    if len(items) != len(set(items)):
        raise ValueError("Display debug overlay items must not contain duplicates")
    unsupported = sorted(set(items) - set(CH347_DEBUG_OVERLAY_ITEMS))
    if unsupported:
        raise ValueError(
            "Display debug overlay has unsupported items: "
            + ", ".join(unsupported)
        )
    selected_items = [item for item in CH347_DEBUG_OVERLAY_ITEMS if item in items]
    return {
        "enabled": enabled,
        "alpha": alpha,
        "scale": scale,
        "items": selected_items,
        "interval_ms": interval_ms,
    }


def validate_ch347_debug_request(request: Any) -> dict[str, Any]:
    if isinstance(request, bool):
        return {"enabled": request}
    if not isinstance(request, dict) or not request:
        raise TypeError("CH347 debug settings must be a boolean or non-empty object")
    unknown = sorted(set(request) - {"enabled", "overlay", "cursor_enabled"})
    if unknown:
        raise ValueError(
            "CH347 debug settings have unknown fields: " + ", ".join(unknown)
        )
    selected: dict[str, Any] = {}
    if "enabled" in request:
        if not isinstance(request["enabled"], bool):
            raise TypeError("CH347 detailed logging must be true or false")
        selected["enabled"] = request["enabled"]
    if "overlay" in request:
        selected["overlay"] = validate_ch347_debug_overlay(request["overlay"])
    if "cursor_enabled" in request:
        if not isinstance(request["cursor_enabled"], bool):
            raise TypeError("CH347 touch cursor enabled must be true or false")
        selected["cursor_enabled"] = request["cursor_enabled"]
    return selected


def normalise_ch347_touch_cursor(cursor: Any) -> dict[str, Any]:
    """Normalise the optional touch-cursor receipt from a debug response.

    Older providers omit the object entirely.  That is represented as an
    unavailable capability rather than an enabled-looking default, so callers
    cannot accidentally present a successful write that the provider ignored.
    """

    if cursor is None:
        return {
            "available": False,
            "enabled": False,
            "applied": False,
            "requires_restart": False,
            "provider_generation": None,
            "reason": "unsupported",
        }
    if not isinstance(cursor, dict):
        raise ValueError("CH347 control returned a non-object touch cursor state")
    expected = {
        "enabled",
        "applied",
        "requires_restart",
        "provider_generation",
        "reason",
    }
    unknown = sorted(set(cursor) - expected)
    missing = sorted(expected - set(cursor))
    if unknown:
        raise ValueError(
            "CH347 touch cursor state has unknown fields: " + ", ".join(unknown)
        )
    if missing:
        raise ValueError(
            "CH347 touch cursor state is missing fields: " + ", ".join(missing)
        )
    for field in ("enabled", "applied", "requires_restart"):
        if not isinstance(cursor[field], bool):
            raise ValueError(f"CH347 control returned invalid touch cursor {field}")
    generation = cursor["provider_generation"]
    if generation is not None:
        generation = _bounded_integer(
            generation,
            "Touch cursor provider generation",
            0,
            2_147_483_647,
        )
    reason = cursor["reason"]
    if not isinstance(reason, str) or len(reason) > 1024:
        raise ValueError("CH347 control returned invalid touch cursor reason")
    return {
        "available": True,
        "enabled": cursor["enabled"],
        "applied": cursor["applied"],
        "requires_restart": cursor["requires_restart"],
        "provider_generation": generation,
        "reason": reason,
    }


def validate_ch347_calibration(
    calibration: dict[str, Any],
    *,
    require_all: bool,
) -> dict[str, Any]:
    if not isinstance(calibration, dict):
        raise TypeError("Touch calibration must be an object")
    unknown = sorted(set(calibration) - set(CH347_CALIBRATION_FIELDS))
    if unknown:
        raise ValueError(
            "Touch calibration has unknown fields: " + ", ".join(unknown)
        )
    if require_all:
        missing = [field for field in CH347_CALIBRATION_FIELDS if field not in calibration]
        if missing:
            raise ValueError(
                "Touch calibration is missing fields: " + ", ".join(missing)
            )
    elif not calibration:
        raise ValueError("Touch calibration changes must not be empty")

    selected: dict[str, Any] = {}
    for field in CH347_CALIBRATION_BOOLEAN_FIELDS:
        if field not in calibration:
            continue
        value = calibration[field]
        if not isinstance(value, bool):
            raise TypeError(f"Touch {field} must be true or false")
        selected[field] = value
    for field in CH347_CALIBRATION_INTEGER_FIELDS:
        if field not in calibration:
            continue
        maximum = 8192 if field in {"width", "height"} else 65535
        minimum = 1 if field in {"width", "height", "pressure_max"} else 0
        selected[field] = _bounded_integer(
            calibration[field],
            f"Touch {field}",
            minimum,
            maximum,
        )

    for lower, upper in (
        ("x_min", "x_max"),
        ("y_min", "y_max"),
        ("pressure_min", "pressure_max"),
    ):
        if lower in selected and upper in selected and selected[lower] >= selected[upper]:
            raise ValueError(f"Touch {lower} must be less than {upper}")
    return selected


def normalise_ch347_fps_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = _ch347_envelope(payload)
    fps, idle_fps = validate_ch347_fps(
        response.get("fps"),
        response.get("idle_fps"),
    )
    return {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "fps": fps,
        "idle_fps": idle_fps,
    }


def normalise_ch347_debug_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = _ch347_envelope(payload)
    debug = response.get("debug")
    if not isinstance(debug, dict):
        raise ValueError("CH347 control returned a non-object debug state")

    enabled = debug.get("enabled")
    applied = debug.get("applied")
    requires_restart = debug.get("requires_restart")
    for field, value in (
        ("enabled", enabled),
        ("applied", applied),
        ("requires_restart", requires_restart),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"CH347 control returned invalid debug {field}")

    fps, idle_fps = validate_ch347_fps(
        debug.get("fps"),
        debug.get("idle_fps"),
    )
    max_fps = _bounded_integer(debug.get("max_fps"), "XCAP maximum FPS", 1, 240)
    if max_fps != fps:
        raise ValueError("FPS and XCAP maximum FPS must match")
    if idle_fps > max_fps:
        raise ValueError("Idle FPS must not exceed XCAP maximum FPS")

    generation = debug.get("provider_generation")
    if generation is not None:
        generation = _bounded_integer(
            generation,
            "Provider generation",
            0,
            2_147_483_647,
        )

    observed_fps = debug.get("observed_fps")
    if observed_fps is not None:
        if (
            isinstance(observed_fps, bool)
            or not isinstance(observed_fps, (int, float))
            or not 0 <= float(observed_fps) <= 1000
        ):
            raise ValueError("CH347 control returned invalid observed FPS")
        observed_fps = float(observed_fps)

    panel_fps = debug.get("panel_fps")
    if panel_fps is not None:
        if (
            isinstance(panel_fps, bool)
            or not isinstance(panel_fps, (int, float))
            or not 0 <= float(panel_fps) <= 1000
        ):
            raise ValueError("CH347 control returned invalid panel FPS")
        panel_fps = float(panel_fps)

    frames = debug.get("frames")
    if frames is not None:
        frames = _bounded_integer(frames, "Observed frames", 0, 4_294_967_295)
    window_ms = debug.get("window_ms")
    if window_ms is not None:
        window_ms = _bounded_integer(
            window_ms,
            "Observation window",
            1,
            86_400_000,
        )
    dirty_counters: dict[str, int | None] = {}
    for field in CH347_DEBUG_COUNTER_FIELDS:
        value = debug.get(field)
        dirty_counters[field] = (
            None
            if value is None
            else _bounded_integer(value, f"CH347 debug {field}", 0, UINT64_MAX)
        )
    status = debug.get("status")
    if status not in CH347_DEBUG_STATUSES:
        raise ValueError("CH347 control returned invalid debug status")
    reason = debug.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 1024:
        raise ValueError("CH347 control returned invalid debug reason")
    raw_overlay = debug.get("overlay")
    if raw_overlay is None:
        overlay = {
            **DEFAULT_CH347_DEBUG_OVERLAY,
            "items": list(DEFAULT_CH347_DEBUG_OVERLAY["items"]),
        }
        overlay["available"] = False
    else:
        overlay = validate_ch347_debug_overlay(raw_overlay)
        overlay["available"] = True
    touch_cursor = normalise_ch347_touch_cursor(debug.get("touch_cursor"))

    return {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "debug": {
            "enabled": enabled,
            "applied": applied,
            "requires_restart": requires_restart,
            "provider_generation": generation,
            "fps": fps,
            "max_fps": max_fps,
            "idle_fps": idle_fps,
            "observed_fps": observed_fps,
            "panel_fps": panel_fps,
            "frames": frames,
            "window_ms": window_ms,
            **dirty_counters,
            "status": status,
            "reason": reason,
            "overlay": overlay,
            "touch_cursor": touch_cursor,
        },
    }


def normalise_ch347_calibration_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = _ch347_envelope(payload)
    calibration = validate_ch347_calibration(
        response.get("touch_calibration"),
        require_all=True,
    )
    result: dict[str, Any] = {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "touch_calibration": calibration,
    }
    if "status" in response:
        status = response["status"]
        if status not in {"available", "degraded", "unavailable"}:
            raise ValueError("CH347 control returned an invalid status")
        result["status"] = status
    return result


def normalise_ch347_status(payload: dict[str, Any]) -> dict[str, Any]:
    response = _ch347_envelope(payload)
    state = response.get("state")
    if not isinstance(state, dict):
        raise ValueError("CH347 control returned a non-object state")
    status = state.get("status")
    if status not in {"available", "degraded", "unavailable"}:
        raise ValueError("CH347 control returned an invalid status")
    running = state.get("running")
    if not isinstance(running, bool):
        raise ValueError("CH347 control returned an invalid running state")
    fps, idle_fps = validate_ch347_fps(state.get("fps"), state.get("idle_fps"))
    calibration = validate_ch347_calibration(
        state.get("touch_calibration"),
        require_all=True,
    )
    normalised = dict(state)
    normalised.update({
        "status": status,
        "running": running,
        "fps": fps,
        "idle_fps": idle_fps,
        "touch_calibration": calibration,
    })
    if "debug" in normalised:
        normalised["debug"] = normalise_ch347_debug_response({
            "schema": CH347_CONTROL_SCHEMA,
            "device": CH347_DEVICE,
            "debug": normalised["debug"],
        })["debug"]
    for field in ("configuration_valid", "configuration_provisioned"):
        if field in normalised and not isinstance(normalised[field], bool):
            raise ValueError(f"CH347 control returned invalid {field}")
    if "live_processes" in normalised:
        _bounded_integer(normalised["live_processes"], "Live processes", 0, 65535)
    errors = normalised.get("configuration_errors", [])
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise ValueError("CH347 control returned invalid configuration errors")
    normalised["configuration_errors"] = list(errors)
    if "physical_rotation" in normalised:
        if normalised["physical_rotation"] not in {
            "normal", "right", "left", "inverted"
        }:
            raise ValueError("CH347 control returned invalid physical rotation")
        control = normalised.get("physical_rotation_control", "unavailable")
        if control not in {"writable", "read-only", "unavailable"}:
            raise ValueError("CH347 control returned invalid physical rotation control")
        normalised["physical_rotation_control"] = control
    mutable = response.get("mutable", [])
    if (
        not isinstance(mutable, list)
        or len(mutable) > 16
        or any(not isinstance(item, str) or not item for item in mutable)
    ):
        raise ValueError("CH347 control returned invalid mutable fields")
    return {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "state": normalised,
        "mutable": list(dict.fromkeys(mutable)),
    }


def _normalise_ch347_result(
    result: OperationResult,
    normaliser: Callable[[dict[str, Any]], dict[str, Any]],
) -> OperationResult:
    if not result.ok:
        return result
    try:
        result.data = normaliser(result.data)
    except (TypeError, ValueError) as exc:
        return OperationResult(
            False,
            {"response": result.data},
            str(exc),
            "CH347_BAD_RESPONSE",
        )
    return result


def hal_state_changes(
    original: dict[str, Any],
    edited: dict[str, Any],
    mutable: list[str],
) -> dict[str, Any]:
    """Return only changed allowlisted HAL fields from a state editor."""

    if not isinstance(original, dict) or not isinstance(edited, dict):
        raise ValueError("HAL state values must be JSON objects")
    allowed = {str(item) for item in mutable}
    changed_read_only = sorted(
        key
        for key in set(original) | set(edited)
        if key not in allowed and original.get(key) != edited.get(key)
    )
    if changed_read_only:
        raise ValueError(
            f"Read-only HAL fields were changed: {', '.join(changed_read_only)}"
        )
    removed = sorted(key for key in allowed if key in original and key not in edited)
    if removed:
        raise ValueError(f"HAL fields cannot be removed: {', '.join(removed)}")
    changes = {
        key: edited[key]
        for key in sorted(allowed)
        if key in edited and original.get(key) != edited[key]
    }
    if not changes:
        raise ValueError("No mutable HAL values were changed")
    return changes


def _hal_catalog_revision(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    revision = payload.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return 0
    return revision


def _hal_provider_row(payload: Any, domain_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("HAL manager returned a non-object provider response")
    rows = payload.get("providers")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("HAL manager returned an invalid provider list")
    matching = [row for row in rows if row.get("domain") == domain_name]
    if len(matching) != 1:
        raise ValueError(
            f"HAL manager did not return exactly one provider row for {domain_name}"
        )
    return dict(matching[0])


def _hal_failed_probe_row(
    row: dict[str, Any],
    domain_name: str,
    error_code: str,
) -> dict[str, Any]:
    result = dict(row)
    raw_candidates = row.get("candidates", [])
    candidates: list[dict[str, Any]] = []
    if isinstance(raw_candidates, list):
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            candidate = dict(raw)
            candidate.setdefault("domains", [domain_name])
            candidate["health"] = {
                "status": "unavailable",
                "reason": "probe-failed",
                "error_code": (error_code or "HAL_UNAVAILABLE")[:64],
            }
            candidates.append(candidate)
    result["candidates"] = candidates
    return result


def _normalise_hal_health(raw: Any, component: str) -> dict[str, Any]:
    if raw is None:
        return {
            "status": "unknown",
            "reason": "not-reported",
            "reported": False,
        }
    if not isinstance(raw, dict) or len(raw) > 16:
        raise ValueError(f"HAL provider {component} has invalid health")
    status = raw.get("status", "unknown")
    reason = raw.get("reason", "")
    if not isinstance(status, str) or status not in {
        "available", "degraded", "unavailable", "unknown"
    }:
        raise ValueError(f"HAL provider {component} has invalid health status")
    if not isinstance(reason, str) or len(reason) > 256:
        raise ValueError(f"HAL provider {component} has invalid health reason")
    result: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "reported": True,
    }
    for field in ("checked_at_unix_ms", "latency_ms", "device_count"):
        if field not in raw:
            continue
        value = raw[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"HAL provider {component} has invalid health {field}")
        result[field] = value
    mutable = raw.get("mutable", [])
    if not isinstance(mutable, list) or len(mutable) > 32 or any(
        not isinstance(item, str) or not item or len(item) > 64
        for item in mutable
    ):
        raise ValueError(f"HAL provider {component} has invalid health mutable fields")
    result["mutable"] = list(dict.fromkeys(mutable))
    truncated = raw.get("mutable_truncated", False)
    if not isinstance(truncated, bool):
        raise ValueError(f"HAL provider {component} has invalid health truncation flag")
    result["mutable_truncated"] = truncated
    if "error_code" in raw:
        error_code = raw["error_code"]
        if not isinstance(error_code, str) or not error_code or len(error_code) > 64:
            raise ValueError(f"HAL provider {component} has invalid health error code")
        result["error_code"] = error_code
    return result


def normalise_hal_domains(
    inventory: dict[str, Any],
    provider_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(inventory, dict) or not isinstance(provider_payload, dict):
        raise TypeError("HAL manager returned a non-object inventory")
    inventory_rows = inventory.get("domains", [])
    provider_rows = provider_payload.get("providers", [])
    if not isinstance(inventory_rows, list) or not isinstance(provider_rows, list):
        raise ValueError("HAL manager returned invalid domain/provider lists")
    if any(not isinstance(item, dict) for item in inventory_rows + provider_rows):
        raise ValueError("HAL manager returned a non-object domain/provider row")
    inventory_names = [item.get("domain") for item in inventory_rows]
    provider_names = [item.get("domain") for item in provider_rows]
    if any(not isinstance(name, str) or not name for name in inventory_names + provider_names):
        raise ValueError("HAL manager returned a domain/provider row without a domain")
    if len(set(inventory_names)) != len(inventory_names):
        raise ValueError("HAL manager returned duplicate inventory domains")
    if len(set(provider_names)) != len(provider_names):
        raise ValueError("HAL manager returned duplicate provider domains")
    inventory_by_domain = {
        str(item.get("domain")): item
        for item in inventory_rows
        if isinstance(item, dict) and item.get("domain")
    }
    providers_by_domain = {
        str(item.get("domain")): item
        for item in provider_rows
        if isinstance(item, dict) and item.get("domain")
    }
    domains: list[dict[str, Any]] = []
    for name in sorted(set(inventory_by_domain) | set(providers_by_domain)):
        if HAL_DOMAIN.fullmatch(name) is None:
            raise ValueError(f"HAL manager returned invalid domain: {name!r}")
        inventory_row = inventory_by_domain.get(name, {})
        provider_row = providers_by_domain.get(name, {})
        raw_candidates = provider_row.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError(f"HAL provider candidates for {name} are not a list")
        candidates: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            if not isinstance(candidate, dict) or not candidate.get("component"):
                raise ValueError(f"HAL provider candidate for {name} is invalid")
            component = candidate["component"]
            if not isinstance(component, str) or HAL_COMPONENT.fullmatch(component) is None:
                raise ValueError(f"HAL provider candidate for {name} has an invalid component")
            if any(item["component"] == component for item in candidates):
                continue
            priority = candidate.get("priority", 0)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ValueError(f"HAL provider candidate for {name} has invalid priority")
            raw_capabilities = candidate.get("capabilities", [])
            if not isinstance(raw_capabilities, list) or len(raw_capabilities) > 32:
                raise ValueError(f"HAL provider capabilities for {name} are invalid")
            capabilities: list[str] = []
            for capability in raw_capabilities:
                if (
                    not isinstance(capability, str)
                    or HAL_CAPABILITY.fullmatch(capability) is None
                    or not capability.startswith(f"{name}.")
                ):
                    raise ValueError(f"HAL provider capability for {name} is invalid")
                if capability not in capabilities:
                    capabilities.append(capability)
            raw_domains = candidate.get("domains", [name])
            if not isinstance(raw_domains, list) or not raw_domains or len(raw_domains) > 8:
                raise ValueError(f"HAL provider candidate {component} has invalid domains")
            candidate_domains: list[str] = []
            for candidate_domain in raw_domains:
                if (
                    not isinstance(candidate_domain, str)
                    or HAL_DOMAIN.fullmatch(candidate_domain) is None
                ):
                    raise ValueError(f"HAL provider candidate {component} has invalid domains")
                if candidate_domain not in candidate_domains:
                    candidate_domains.append(candidate_domain)
            if name not in candidate_domains:
                raise ValueError(f"HAL provider candidate {component} omits domain {name}")
            health = _normalise_hal_health(candidate.get("health"), component)
            candidates.append({
                "component": component,
                "name": str(candidate.get("name") or component),
                "version": str(candidate.get("version") or ""),
                "priority": priority,
                "domains": candidate_domains,
                "capabilities": capabilities,
                "health": health,
                "selectable": health["status"] != "unavailable",
            })
        active = provider_row.get("active", inventory_row.get("provider"))
        status = inventory_row.get("status", "unknown")
        selection = provider_row.get(
            "selection", inventory_row.get("selection", "automatic")
        )
        if not isinstance(status, str) or status not in {
            "available", "unavailable", "degraded", "unknown"
        }:
            raise ValueError(f"HAL domain {name} has an invalid status")
        if not isinstance(selection, str) or selection not in {
            "automatic", "manual", "stale"
        }:
            raise ValueError(f"HAL domain {name} has an invalid selection mode")
        for candidate in candidates:
            candidate["active"] = candidate["component"] == active
            candidate["selected"] = candidate["component"] == provider_row.get("preferred")
        domains.append({
            "domain": name,
            "status": status,
            "reason": str(inventory_row.get("reason", "")),
            "selection": selection,
            "preferred": str(provider_row.get("preferred") or ""),
            "active": str(active or ""),
            "candidates": candidates,
            "error": str(inventory_row.get("error", "")),
        })
    return domains


def normalise_hal_inventory(
    payload: dict[str, Any],
    domains: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise TypeError("HAL manager returned a non-object inventory")
    raw_devices: Any = payload.get("devices", payload.get("inventory", payload.get("items", [])))
    if isinstance(raw_devices, dict):
        raw_devices = [
            {"id": key, **(value if isinstance(value, dict) else {"state": value})}
            for key, value in raw_devices.items()
        ]
    if not isinstance(raw_devices, list):
        raise ValueError("HAL manager returned an invalid device list")
    domain_map = {
        str(item.get("domain")): item
        for item in (domains or [])
        if isinstance(item, dict) and item.get("domain")
    }
    devices: list[dict[str, Any]] = []
    seen_devices: set[str] = set()
    for index, raw in enumerate(raw_devices):
        if not isinstance(raw, dict):
            raise ValueError(f"HAL device row {index} is not an object")
        raw_identifier = raw.get("id") or raw.get("device") or raw.get("name")
        if raw_identifier is None or not str(raw_identifier):
            raise ValueError(f"HAL device row {index} has no stable id")
        device_id = str(raw_identifier)
        if device_id in seen_devices:
            raise ValueError(f"HAL manager returned duplicate device id: {device_id}")
        seen_devices.add(device_id)
        device_domain = str(raw.get("domain") or device_id.split(":", 1)[0])
        available = raw.get("available", True)
        mutable = raw.get("mutable", [])
        metadata = raw.get("metadata", {})
        if not isinstance(available, bool):
            raise ValueError(f"HAL device {device_id} has invalid availability")
        if not isinstance(mutable, list) or any(
            not isinstance(item, str) for item in mutable
        ):
            raise ValueError(f"HAL device {device_id} has invalid mutable fields")
        if not isinstance(metadata, dict):
            raise ValueError(f"HAL device {device_id} has invalid metadata")
        domain_info = domain_map.get(device_domain, {})
        provider = raw.get(
            "provider",
            raw.get("active_provider", domain_info.get("active", "")),
        )
        raw_candidates = raw.get("providers", raw.get("candidates", []))
        if not isinstance(raw_candidates, list):
            raise ValueError(f"HAL device {device_id} has invalid provider candidates")
        candidates: list[str] = []
        for candidate in raw_candidates:
            if isinstance(candidate, dict):
                value = candidate.get("component", candidate.get("id", candidate.get("provider")))
            else:
                value = candidate
            if value is not None and str(value) not in candidates:
                candidates.append(str(value))
        if not candidates:
            candidates = [
                str(item["component"])
                for item in domain_info.get("candidates", [])
                if isinstance(item, dict) and item.get("component")
            ]
        devices.append(
            {
                "id": device_id,
                "name": str(raw.get("name") or device_id),
                "domain": device_domain,
                "kind": str(raw.get("kind", raw.get("class", device_domain or "device"))),
                "provider": str(provider or ""),
                "providers": candidates,
                "available": available,
                "mutable": list(mutable),
                "metadata": metadata,
                "raw": raw,
            }
        )
    return devices


def normalise_hal_state(payload: dict[str, Any], identifier: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("HAL manager returned a non-object state response")
    raw = payload.get("state", payload)
    if not isinstance(raw, dict):
        raise ValueError("HAL manager returned a non-object state")
    returned_id = str(raw.get("id", identifier))
    if returned_id != identifier:
        raise ValueError("HAL manager returned state for another device")
    values = raw.get("values", {})
    mutable = raw.get("mutable", [])
    available = raw.get("available", True)
    if (
        not isinstance(values, dict)
        or not isinstance(mutable, list)
        or any(not isinstance(item, str) for item in mutable)
        or not isinstance(available, bool)
    ):
        raise ValueError("HAL manager returned an invalid state contract")
    # Command-style capabilities (for example network scan/connect) are
    # write-only actions, not durable state values.  Other mutable fields must
    # still be present so Settings cannot fabricate their current value.
    missing_mutable = sorted(set(mutable) - set(values) - {"action"})
    if missing_mutable:
        raise ValueError(
            "HAL manager returned mutable fields without values: "
            + ", ".join(missing_mutable)
        )
    return {
        "id": returned_id,
        "domain": str(raw.get("domain") or identifier.split(":", 1)[0]),
        "available": available,
        "provider": str(payload.get("provider") or ""),
        "values": values,
        "mutable": list(mutable),
        "revision": payload.get("revision", 0),
    }
