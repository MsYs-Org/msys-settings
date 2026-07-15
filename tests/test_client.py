from __future__ import annotations

import unittest

from msys_settings.client import SettingsClient


class FakeRpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.broadcasts: list[tuple[str, dict, dict]] = []

    def call(self, target: str, method: str, payload=None, **options):
        self.calls.append((target, method, payload or {}, options))
        return {"ok": True}

    def broadcast(self, topic: str, payload=None, **options):
        self.broadcasts.append((topic, payload or {}, options))
        return {"ok": True}


class SettingsClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rpc = FakeRpc()
        self.client = SettingsClient(self.rpc)

    def test_layout_uses_window_manager_role(self) -> None:
        self.client.get_layout()
        self.client.set_layout("desktop", "landscape", "auto")
        self.assertEqual(self.rpc.calls[0][:2], ("role:window-manager", "get_layout"))
        self.assertEqual(self.rpc.calls[1][2]["profile"], "desktop")

    def test_desktop_preferences_use_launcher_role(self) -> None:
        preferences = {
            "layout": "desktop",
            "wallpaper_color": "#101419",
            "accent_color": "#55A8FF",
            "icon_size": 64,
            "show_labels": True,
            "sort": "name",
        }
        self.client.get_desktop_preferences()
        self.client.set_desktop_preferences(preferences)
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:launcher", "get_preferences"),
                ("role:launcher", "set_preferences"),
            ],
        )
        self.assertTrue(self.rpc.calls[0][3]["idempotent"])
        self.assertEqual(self.rpc.calls[1][2], preferences)

    def test_roles_use_core_methods(self) -> None:
        self.client.list_roles()
        self.client.select_role("launcher", "org.example:launcher")
        self.client.reset_role("launcher")
        self.assertEqual([call[1] for call in self.rpc.calls], ["list_roles", "select_role", "reset_role"])
        self.assertEqual(self.rpc.calls[1][2], {"role": "launcher", "provider": "org.example:launcher"})

    def test_input_method_uses_replaceable_typed_role(self) -> None:
        self.client.input_method_status()
        self.client.toggle_input_method()
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:input-method", "status"),
                ("role:input-method", "toggle"),
            ],
        )
        self.assertTrue(self.rpc.calls[0][3]["idempotent"])
        self.assertNotIn("idempotent", self.rpc.calls[1][3])

    def test_audio_uses_only_the_replaceable_audio_manager_role(self) -> None:
        self.client.audio_get_state(refresh=True)
        self.client.audio_set_volume({"percent": 60, "output": "headset"})
        self.client.audio_set_muted({"muted": True, "output": "headset"})
        self.client.audio_select_output({"id": "headset"})
        self.client.audio_configure_player(
            {"enabled": True, "server": "10.0.0.2", "name": "Desk"}
        )
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:audio-manager", "get_state"),
                ("role:audio-manager", "set_volume"),
                ("role:audio-manager", "set_muted"),
                ("role:audio-manager", "select_output"),
                ("role:audio-manager", "configure_player"),
            ],
        )
        self.assertEqual(self.rpc.calls[0][2], {"refresh": True})
        self.assertEqual(
            self.rpc.calls[0][3],
            {"timeout": 20.0, "idempotent": True},
        )
        self.assertTrue(
            all(call[3] == {"timeout": 45.0} for call in self.rpc.calls[1:])
        )

    def test_bluetooth_audio_lifecycle_uses_one_role_and_bounded_timeouts(self) -> None:
        self.client.audio_list_devices(refresh=True)
        self.client.audio_scan(timeout_ms=15000)
        for action in ("pair", "connect", "disconnect", "forget"):
            self.client.audio_device_action(
                action,
                {"address": "AA:BB:CC:DD:EE:FF"},
            )
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:audio-manager", "list_devices"),
                ("role:audio-manager", "scan"),
                ("role:audio-manager", "pair"),
                ("role:audio-manager", "connect"),
                ("role:audio-manager", "disconnect"),
                ("role:audio-manager", "forget"),
            ],
        )
        self.assertEqual(
            self.rpc.calls[0][3],
            {"timeout": 20.0, "idempotent": True},
        )
        self.assertTrue(
            all(call[3] == {"timeout": 45.0} for call in self.rpc.calls[1:])
        )
        with self.assertRaises(ValueError):
            self.client.audio_device_action("remove", {"address": "unused"})

    def test_hal_uses_versioned_interface(self) -> None:
        self.client.hal_inventory(refresh=True)
        self.client.hal_get_state("display:primary", refresh=True)
        self.client.hal_set_state("display:primary", {"brightness": 60})
        self.client.hal_list_providers("display", refresh=True, probe=True)
        self.client.hal_select_provider(
            "display",
            "org.example:display",
            expected_revision=7,
        )
        self.client.hal_reset_provider("display", expected_revision=8)
        self.assertTrue(all(call[0] == "interface:org.msys.hal.manager.v1" for call in self.rpc.calls))
        self.assertEqual(
            [call[1] for call in self.rpc.calls],
            [
                "inventory",
                "get_state",
                "set_state",
                "list_providers",
                "select_provider",
                "reset_provider",
            ],
        )
        self.assertEqual(self.rpc.calls[0][2], {"refresh": True})
        self.assertEqual(
            self.rpc.calls[1][2],
            {"id": "display:primary", "refresh": True},
        )
        self.assertEqual(
            self.rpc.calls[2][2],
            {"id": "display:primary", "changes": {"brightness": 60}},
        )
        self.assertEqual(
            [self.rpc.calls[index][3] for index in range(4)],
            [
                {"timeout": 35.0, "idempotent": True},
                {"timeout": 35.0, "idempotent": True},
                {"timeout": 35.0},
                {"timeout": 35.0, "idempotent": True},
            ],
        )
        self.assertEqual(
            self.rpc.calls[3][2],
            {"domain": "display", "refresh": True, "probe": True},
        )
        self.assertEqual(
            self.rpc.calls[4][2],
            {
                "domain": "display",
                "component": "org.example:display",
                "expected_revision": 7,
            },
        )
        self.assertEqual(
            self.rpc.calls[5][2],
            {"domain": "display", "expected_revision": 8},
        )

    def test_hal_legacy_payload_omits_new_optional_fields(self) -> None:
        self.client.hal_list_providers("display", refresh=False)
        self.client.hal_select_provider("display", "org.example:display")
        self.client.hal_reset_provider("display")
        self.assertEqual(
            self.rpc.calls[0][2],
            {"domain": "display", "refresh": False},
        )
        self.assertEqual(
            self.rpc.calls[1][2],
            {"domain": "display", "component": "org.example:display"},
        )
        self.assertEqual(self.rpc.calls[2][2], {"domain": "display"})

    def test_hal_unavailable_override_is_explicit(self) -> None:
        self.client.hal_select_provider(
            "display",
            "org.example:display",
            expected_revision=9,
            allow_unavailable=True,
        )
        self.assertEqual(self.rpc.calls[0][2], {
            "domain": "display",
            "component": "org.example:display",
            "expected_revision": 9,
            "allow_unavailable": True,
        })

    def test_update_and_rollback_wait_for_typed_agent_roles(self) -> None:
        self.client.request_update_check("index.json", None)
        self.client.request_update_apply("index.json", "org.example.app")
        self.client.request_rollback("org.example.app")
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:update-agent", "check_updates"),
                ("role:update-agent", "apply_updates"),
                ("role:install-agent", "rollback"),
            ],
        )
        self.assertEqual(self.rpc.broadcasts, [])
        self.assertEqual(self.rpc.calls[0][2], {"source": "index.json"})
        self.assertEqual(
            self.rpc.calls[1][2],
            {"source": "index.json", "package": "org.example.app"},
        )
        self.assertEqual(self.rpc.calls[2][2], {"package": "org.example.app"})
        self.assertTrue(self.rpc.calls[0][3]["idempotent"])
        self.assertEqual(self.rpc.calls[1][3]["timeout"], 300.0)
        self.assertEqual(self.rpc.calls[2][3]["timeout"], 90.0)

    def test_apps_registry_and_uninstall_use_install_agent_rpc(self) -> None:
        self.client.request_registry()
        self.client.request_uninstall("org.example.app")
        self.assertEqual(
            [call[:2] for call in self.rpc.calls],
            [
                ("role:install-agent", "registry"),
                ("role:install-agent", "uninstall"),
            ],
        )
        self.assertEqual(self.rpc.calls[0][2], {})
        self.assertTrue(self.rpc.calls[0][3]["idempotent"])
        self.assertEqual(
            self.rpc.calls[1][2],
            {"package": "org.example.app"},
        )
        self.assertEqual(self.rpc.calls[1][3]["timeout"], 90.0)

    def test_display_migration_status_uses_idempotent_core_query(self) -> None:
        self.client.display_migration_status(17)
        call = self.rpc.calls[0]
        self.assertEqual(call[:2], ("msys.core", "display_migration_status"))
        self.assertEqual(call[2], {"id": 17})
        self.assertTrue(call[3]["idempotent"])


if __name__ == "__main__":
    unittest.main()
