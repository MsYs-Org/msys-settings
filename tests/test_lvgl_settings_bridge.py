from __future__ import annotations

from pathlib import Path
import threading
import unittest

from lvgl_bridge import Bridge


ROOT = Path(__file__).resolve().parents[1]


class LvglSettingsBridgeTests(unittest.TestCase):
    def _bare_bridge(self) -> tuple[Bridge, list[dict[str, object]]]:
        bridge = object.__new__(Bridge)
        emitted: list[dict[str, object]] = []
        bridge._collect_lock = threading.Lock()
        bridge.emit = emitted.append  # type: ignore[method-assign]
        return bridge, emitted

    def test_home_load_is_bounded_and_does_not_wake_optional_roles(self) -> None:
        bridge, emitted = self._bare_bridge()
        calls: list[tuple[str, object]] = []
        bridge.local_fields = lambda: {"locale": "system"}  # type: ignore[method-assign]
        bridge.collect_layout = (  # type: ignore[method-assign]
            lambda *, details=True: calls.append(("layout", details)) or {"display.summary": "mobile"}
        )
        bridge.collect_home()
        self.assertEqual(calls, [("layout", False)])
        self.assertEqual(emitted[-1]["status"], "设置已就绪；二级页面按需读取")
        source = (ROOT / "files/app/lvgl_bridge.py").read_text(encoding="utf-8")
        home = source.split("def collect_home", 1)[1].split("def collect_panel", 1)[0]
        for forbidden in (
            "collect_audio(", "collect_storage(", "collect_apps(",
            "collect_system(", "collect_developer(", "collect_hal(",
        ):
            self.assertNotIn(forbidden, home)

    def test_refresh_dispatches_only_the_requested_panel_collector(self) -> None:
        bridge, emitted = self._bare_bridge()
        calls: list[str] = []
        for name in (
            "collect_wifi", "collect_bluetooth_panel", "collect_audio",
            "collect_layout", "collect_storage", "collect_apps",
            "collect_hal", "collect_developer", "collect_system",
        ):
            setattr(
                bridge,
                name,
                lambda selected=name: calls.append(selected) or {"collector": selected},
            )
        bridge.collect_panel("wifi")
        self.assertEqual(calls, ["collect_wifi"])
        self.assertEqual(emitted, [{"collector": "collect_wifi"}])
        calls.clear()
        emitted.clear()
        bridge.collect_panel("developer")
        self.assertEqual(calls, ["collect_developer"])
        self.assertEqual(emitted, [{"collector": "collect_developer"}])

    def test_p0_actions_use_existing_model_contracts(self) -> None:
        source = (ROOT / "files/app/lvgl_bridge.py").read_text(encoding="utf-8")
        action = source.split("def action(self, name: str, value: str)", 1)[1].split(
            "\ndef main()", 1
        )[0]
        expected = {
            "wifi_scan": "self.model.hal_set_state(device, changes)",
            "wifi_connect": "wifi_connect_changes(row, password)",
            "wifi_forget": "wifi_forget_changes(row)",
            "bluetooth_scan": "self.model.audio_scan_devices(15000)",
            "bluetooth_pair": "self.model.audio_device_action(action, value.strip())",
            "audio_volume": "self.model.audio_set_volume(value)",
            "audio_output": "self.model.audio_select_output(output)",
            "storage_mount": "self.model.storage_mount(volume_id)",
            "regional_language": "self.regional.set_language(value)",
            "hal_select": "self.model.select_hal_provider(domain, provider.strip())",
            "developer_fps": "self.model.ch347_set_fps(value, idle)",
            "physical_rotation": "self.model.set_physical_rotation(device, value)",
        }
        native = (ROOT / "native/src/main.c").read_text(encoding="utf-8")
        for action_name, call in expected.items():
            self.assertIn(action_name, action + native)
            self.assertIn(call, action)
        self.assertNotIn("bluetoothctl", action)
        self.assertNotIn("wpa_cli", action)

    def test_activation_and_back_share_the_native_page_state(self) -> None:
        source = (ROOT / "files/app/lvgl_bridge.py").read_text(encoding="utf-8")
        self.assertIn('bridge.emit({"settings.page": panel})', source)
        self.assertIn('if bridge._settings_page == "home":', source)
        self.assertIn('return {"handled": False, "page": "home"}', source)
        self.assertIn('bridge.emit({"settings.page": "home"})', source)
        native = (ROOT / "native/src/main.c").read_text(encoding="utf-8")
        self.assertIn('send_bridge(active_app, "ACTION", "settings_page", panel->id)', native)
        self.assertIn('send_bridge(active_app, "ACTION", "settings_page", "home")', native)


if __name__ == "__main__":
    unittest.main()
