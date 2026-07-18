"""Typed high-level calls for MSYS Settings.

Every operation maps to a documented language-neutral mIPC address.  Keeping
these mappings here makes the Tk UI replaceable by Qt, Electron, or a native
frontend without changing the system contract.
"""

from __future__ import annotations

from typing import Any, Protocol

from .ipc import PublicMipcClient

HAL_MANAGER = "interface:org.msys.hal.manager.v1"
HAL_READ_TIMEOUT = 35.0
CH347_CONTROL = "interface:org.msys.hal.ch347-control.v1"
CH347_CONTROL_TIMEOUT = 60.0
UPDATE_AGENT = "role:update-agent"
INSTALL_AGENT = "role:install-agent"
INPUT_METHOD = "role:input-method"
AUDIO_MANAGER = "role:audio-manager"
STORAGE_MANAGER = "role:storage"
AUDIO_READ_TIMEOUT = 20.0
AUDIO_WRITE_TIMEOUT = 45.0


class RpcClient(Protocol):
    def call(
        self,
        target: str,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]: ...

class SettingsClient:
    def __init__(self, rpc: RpcClient | None = None) -> None:
        self.rpc = rpc or PublicMipcClient()

    def discover(self) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core", "discover", {}, idempotent=True
        )

    def list_components(self) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core", "list_components", {}, idempotent=True
        )

    def start_component(self, component: str) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core",
            "start",
            {"component": component},
            timeout=12.0,
        )

    def isolation_capabilities(self) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core", "isolation_capabilities", {}, idempotent=True
        )

    def get_session_preferences(self) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core", "get_session_preferences", {}, idempotent=True
        )

    def set_session_language(self, language: str) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core",
            "set_session_preferences",
            {"language": language},
            timeout=5.0,
        )

    def notify_timezone_changed(self, timezone: str) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core",
            "broadcast",
            {
                "topic": "msys.timezone.changed",
                "payload": {"timezone": timezone},
            },
            timeout=5.0,
        )

    def list_roles(self) -> dict[str, Any]:
        return self.rpc.call("msys.core", "list_roles", {}, idempotent=True)

    def select_role(self, role: str, provider: str) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core",
            "select_role",
            {"role": role, "provider": provider},
            timeout=12.0,
        )

    def reset_role(self, role: str) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core", "reset_role", {"role": role}, timeout=12.0
        )

    def input_method_status(self) -> dict[str, Any]:
        return self.rpc.call(
            INPUT_METHOD,
            "status",
            {},
            timeout=5.0,
            idempotent=True,
        )

    def toggle_input_method(self) -> dict[str, Any]:
        return self.rpc.call(
            INPUT_METHOD,
            "toggle",
            {},
            timeout=8.0,
        )

    def show_input_method(self) -> dict[str, Any]:
        """Explicitly show the keyboard; unlike toggle this is idempotent."""
        return self.rpc.call(INPUT_METHOD, "show", {}, timeout=8.0)

    def hide_input_method(self) -> dict[str, Any]:
        return self.rpc.call(
            INPUT_METHOD,
            "hide",
            {"reason": "settings"},
            timeout=8.0,
        )

    def set_input_method_mode(self, mode: str) -> dict[str, Any]:
        return self.rpc.call(
            INPUT_METHOD,
            "set_mode",
            {"mode": mode},
            timeout=8.0,
        )

    def audio_get_state(self, *, refresh: bool = False) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "get_state",
            {"refresh": refresh},
            timeout=AUDIO_READ_TIMEOUT,
            idempotent=True,
        )

    def audio_list_devices(self, *, refresh: bool = False) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "list_devices",
            {"refresh": refresh},
            timeout=AUDIO_READ_TIMEOUT,
            idempotent=True,
        )

    def audio_scan(self, *, timeout_ms: int = 15000) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "scan",
            {"timeout_ms": timeout_ms},
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def audio_device_action(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action not in {"pair", "connect", "disconnect", "forget"}:
            raise ValueError("Unsupported Bluetooth audio action")
        return self.rpc.call(
            AUDIO_MANAGER,
            action,
            payload,
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def audio_set_volume(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "set_volume",
            payload,
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def audio_set_muted(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "set_muted",
            payload,
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def audio_select_output(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "select_output",
            payload,
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def audio_configure_player(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rpc.call(
            AUDIO_MANAGER,
            "configure_player",
            payload,
            timeout=AUDIO_WRITE_TIMEOUT,
        )

    def storage_get_state(self) -> dict[str, Any]:
        return self.rpc.call(
            STORAGE_MANAGER,
            "get_state",
            {},
            timeout=8.0,
            idempotent=True,
        )

    def storage_refresh(self) -> dict[str, Any]:
        return self.rpc.call(
            STORAGE_MANAGER,
            "refresh",
            {},
            timeout=20.0,
        )

    def storage_set_config(self, auto_mount: bool) -> dict[str, Any]:
        return self.rpc.call(
            STORAGE_MANAGER,
            "set_config",
            {"auto_mount": bool(auto_mount)},
            timeout=20.0,
        )

    def storage_mount(
        self,
        volume_id: str,
        *,
        read_only: bool = False,
    ) -> dict[str, Any]:
        return self.rpc.call(
            STORAGE_MANAGER,
            "mount",
            {"volume_id": volume_id, "read_only": bool(read_only)},
            timeout=20.0,
        )

    def storage_unmount(self, volume_id: str) -> dict[str, Any]:
        return self.rpc.call(
            STORAGE_MANAGER,
            "unmount",
            {"volume_id": volume_id},
            timeout=20.0,
        )

    def get_layout(self) -> dict[str, Any]:
        return self.rpc.call(
            "role:window-manager", "get_layout", {}, idempotent=True
        )

    def set_layout(
        self,
        profile: str,
        orientation: str,
        insets: str | dict[str, int],
    ) -> dict[str, Any]:
        return self.rpc.call(
            "role:window-manager",
            "set_layout",
            {
                "profile": profile,
                "orientation": orientation,
                "insets": insets,
            },
            timeout=8.0,
        )

    def get_desktop_preferences(self) -> dict[str, Any]:
        return self.rpc.call(
            "role:launcher",
            "get_preferences",
            {},
            idempotent=True,
        )

    def set_desktop_preferences(
        self,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        return self.rpc.call(
            "role:launcher",
            "set_preferences",
            preferences,
            timeout=8.0,
        )

    def hal_inventory(self, *, refresh: bool = False) -> dict[str, Any]:
        return self.rpc.call(
            HAL_MANAGER,
            "inventory",
            {"refresh": refresh},
            # A cold manager may build the bounded provider catalog before it
            # can answer.  Keep this explicit instead of weakening the
            # ComponentChannel five-second default for unrelated RPC.
            timeout=HAL_READ_TIMEOUT,
            idempotent=True,
        )

    def hal_get_state(
        self,
        device: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return self.rpc.call(
            HAL_MANAGER,
            "get_state",
            {"id": device, "refresh": refresh},
            # Provider resolution can trigger the same cold catalog build as
            # inventory, even though this operation is read-only.
            timeout=HAL_READ_TIMEOUT,
            idempotent=True,
        )

    def hal_set_state(self, device: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self.rpc.call(
            HAL_MANAGER,
            "set_state",
            {"id": device, "changes": changes},
            # The HAL manager allows a provider write up to 30 seconds.  Keep
            # a small transport margin so a completed write is not reported as
            # a client timeout while the worker remains off the Tk thread.
            timeout=35.0,
        )

    def hal_list_providers(
        self,
        domain: str | None = None,
        *,
        refresh: bool = False,
        probe: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"refresh": refresh}
        if domain:
            payload["domain"] = domain
        if probe is not None:
            payload["probe"] = probe
        return self.rpc.call(
            HAL_MANAGER,
            "list_providers",
            payload,
            # The first catalog/probe pass is intentionally bounded by HAL,
            # but can exceed the component channel's general five seconds.
            timeout=HAL_READ_TIMEOUT,
            idempotent=True,
        )

    def hal_select_provider(
        self,
        domain: str,
        component: str,
        *,
        expected_revision: int | None = None,
        allow_unavailable: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"domain": domain, "component": component}
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        if allow_unavailable:
            payload["allow_unavailable"] = True
        return self.rpc.call(
            HAL_MANAGER,
            "select_provider",
            payload,
            timeout=12.0,
        )

    def hal_reset_provider(
        self,
        domain: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"domain": domain}
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        return self.rpc.call(
            HAL_MANAGER,
            "reset_provider",
            payload,
            timeout=12.0,
        )

    def ch347_status(self) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "status",
            {},
            timeout=CH347_CONTROL_TIMEOUT,
            idempotent=True,
        )

    def ch347_get_fps(self) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "get_fps",
            {},
            timeout=CH347_CONTROL_TIMEOUT,
            idempotent=True,
        )

    def ch347_set_fps(self, fps: int, idle_fps: int) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "set_fps",
            {"fps": fps, "idle_fps": idle_fps},
            timeout=CH347_CONTROL_TIMEOUT,
        )

    def ch347_get_debug(self) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "get_debug",
            {},
            timeout=CH347_CONTROL_TIMEOUT,
            idempotent=True,
        )

    def ch347_set_debug(
        self,
        settings: bool | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(settings, bool):
            payload: dict[str, Any] = {"enabled": settings}
        elif isinstance(settings, dict) and settings:
            payload = dict(settings)
            if "cursor_enabled" in payload:
                cursor_enabled = payload["cursor_enabled"]
                if not isinstance(cursor_enabled, bool):
                    raise TypeError("CH347 touch cursor enabled must be true or false")
                payload["cursor_enabled"] = cursor_enabled
            overlay = payload.get("overlay")
            if isinstance(overlay, dict):
                payload["overlay"] = {
                    **overlay,
                    **(
                        {"items": list(overlay["items"])}
                        if isinstance(overlay.get("items"), list)
                        else {}
                    ),
                }
        else:
            raise TypeError("CH347 debug settings must be a boolean or non-empty object")
        return self.rpc.call(
            CH347_CONTROL,
            "set_debug",
            payload,
            timeout=CH347_CONTROL_TIMEOUT,
        )

    def ch347_get_touch_calibration(self) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "get_touch_calibration",
            {},
            timeout=CH347_CONTROL_TIMEOUT,
            idempotent=True,
        )

    def ch347_set_touch_calibration(
        self,
        calibration: dict[str, Any],
    ) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "set_touch_calibration",
            {"touch_calibration": calibration},
            timeout=CH347_CONTROL_TIMEOUT,
        )

    def ch347_set_physical_rotation(self, rotation: str) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "set_physical_rotation",
            {"physical_rotation": rotation},
            timeout=CH347_CONTROL_TIMEOUT,
        )

    def ch347_restart(self) -> dict[str, Any]:
        return self.rpc.call(
            CH347_CONTROL,
            "restart",
            {},
            timeout=CH347_CONTROL_TIMEOUT,
        )

    def request_update_check(self, source: str, package: str | None) -> dict[str, Any]:
        return self.rpc.call(
            UPDATE_AGENT,
            "check_updates",
            _update_payload(source, package),
            timeout=60.0,
            idempotent=True,
        )

    def request_update_apply(self, source: str, package: str | None) -> dict[str, Any]:
        return self.rpc.call(
            UPDATE_AGENT,
            "apply_updates",
            _update_payload(source, package),
            timeout=300.0,
        )

    def request_rollback(self, package: str) -> dict[str, Any]:
        return self.rpc.call(
            INSTALL_AGENT,
            "rollback",
            {"package": package},
            timeout=90.0,
        )

    def request_registry(self) -> dict[str, Any]:
        return self.rpc.call(
            INSTALL_AGENT,
            "registry",
            {},
            timeout=15.0,
            idempotent=True,
        )

    def request_uninstall(self, package: str) -> dict[str, Any]:
        return self.rpc.call(
            INSTALL_AGENT,
            "uninstall",
            {"package": package},
            timeout=90.0,
        )

    def display_migration_status(self, migration_id: int) -> dict[str, Any]:
        return self.rpc.call(
            "msys.core",
            "display_migration_status",
            {"id": migration_id},
            timeout=8.0,
            idempotent=True,
        )


def _update_payload(source: str, package: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": source}
    if package and package != "all":
        payload["package"] = package
    return payload
