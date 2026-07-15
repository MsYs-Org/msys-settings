from __future__ import annotations

import ast
from pathlib import Path
import unittest

from msys_settings.focus import hal_focus_target, role_focus_target
from msys_settings.responsive import filter_navigation, layout_metrics
from msys_settings.viewport import is_compact, window_size


class UiContractTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "files/app/msys_settings/ui.py"
        ).read_text(encoding="utf-8")

    def test_component_channel_subscribes_to_display_migration_progress(self) -> None:
        source = self._source()
        module = ast.parse(source)
        application = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsApplication"
        )
        assignment = next(
            node
            for node in application.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "EVENT_TOPICS"
                for target in node.targets
            )
        )
        topics = ast.literal_eval(assignment.value)
        self.assertIn("msys.display.migration", topics)
        self.assertIn("msys.update.checked", topics)
        self.assertIn("msys.update.applied", topics)
        self.assertIn("msys.install.package_changed", topics)
        self.assertIn("msys.audio.changed", topics)

    def test_roles_focus_selects_loaded_role_or_remembers_deferred_role(self) -> None:
        self.assertEqual(
            role_focus_target("display-output", {"display-output": {}}),
            "display-output",
        )
        self.assertIsNone(role_focus_target("display-output", {}))
        source = self._source()
        self.assertIn("target = role_focus_target(role, self.roles)", source)
        self.assertIn("self._requested_role = role if target is None else None", source)

    def test_hal_focus_selects_domain_device_or_remembers_deferred_domain(self) -> None:
        self.assertEqual(
            hal_focus_target(
                "display",
                {"display": {}},
                {
                    "power:BAT0": {"domain": "power"},
                    "display:primary": {"domain": "display"},
                },
            ),
            ("display", "display:primary"),
        )
        self.assertEqual(hal_focus_target("display", {}, {}), (None, None))
        self.assertEqual(
            hal_focus_target("display", {"display": {}}, {}),
            ("display", None),
        )
        source = self._source()
        self.assertIn("target_domain, target_device = hal_focus_target(", source)
        self.assertIn(
            "self._requested_domain = domain if target_domain is None else None",
            source,
        )

    def test_display_activation_alias_and_compact_actions_are_two_rows(self) -> None:
        source = self._source()
        self.assertIn('if panel == "display"', source)
        self.assertIn(
            'secondary_actions = ttk.Frame(logical_card, style="Panel.TFrame")',
            source,
        )
        self.assertIn('if app.compact:', source)

    def test_compact_display_debug_keeps_long_actions_on_separate_rows(self) -> None:
        source = self._source()
        layout_page = source.split("class LayoutPage", 1)[1].split(
            "class AppearancePage", 1
        )[0]
        self.assertIn("debug_mode_actions = debug_actions", layout_page)
        self.assertIn(
            'debug_mode_actions = ttk.Frame(debug_card, style="Panel.TFrame")',
            layout_page,
        )
        self.assertIn('debug_mode_actions.pack(fill="x", pady=(6, 0))', layout_page)
        self.assertIn('self.debug_apply_button.pack(fill="x")', layout_page)
        self.assertIn("ScrollableSurface(self, background=PANEL)", layout_page)

    def test_display_debug_shows_cumulative_dirty_counters_without_rates(self) -> None:
        source = self._source()
        layout_page = source.split("class LayoutPage", 1)[1].split(
            "class AppearancePage", 1
        )[0]
        for field in (
            "sent_frames",
            "zero_damage",
            "full_refreshes",
            "large_refreshes",
            "sent_pixels",
            "last_sent_pixels",
            "last_rects",
        ):
            self.assertIn(f'value("{field}")', layout_page)
        self.assertIn('self.app.tr("common.unavailable")', layout_page)
        self.assertIn('app.tr("display.debug_dirty_note")', layout_page)

    def test_320_by_480_keeps_exact_compact_viewport(self) -> None:
        self.assertTrue(is_compact(320))
        self.assertEqual(window_size(320, 480), (320, 480))
        self.assertEqual(window_size(1920, 1080), (1000, 720))

    def test_hal_provider_ui_consumes_health_and_revision_safely(self) -> None:
        source = self._source()
        self.assertIn('self.provider_detail = tk.StringVar(', source)
        self.assertIn('wraplength=286 if app.compact else 720', source)
        self.assertIn('candidate.get("selectable", True)', source)
        self.assertIn('expected_revision=expected_revision', source)
        self.assertIn('result.code == "HAL_CONFLICT"', source)

    def test_apps_page_refreshes_registry_and_requires_danger_confirmation(self) -> None:
        source = self._source()
        self.assertIn('(\"apps\", \"nav.apps\", AppsPage)', source)
        self.assertIn('self.app.model.installed_packages', source)
        self.assertIn('self.app.model.request_uninstall(package)', source)
        self.assertIn('messagebox.askyesno(', source)
        self.assertIn('default=messagebox.NO', source)
        self.assertIn('icon="warning"', source)
        self.assertIn('topic == "msys.install.package_changed"', source)

    def test_compact_home_uses_cards_while_desktop_uses_searchable_side_nav(self) -> None:
        self.assertEqual(layout_metrics(320).mode, "compact")
        self.assertEqual(layout_metrics(320).quick_columns, 2)
        self.assertEqual(layout_metrics(1000).mode, "desktop")
        self.assertEqual(layout_metrics(1000).quick_columns, 3)
        self.assertEqual(
            filter_navigation("blue", [("wifi", "Wi-Fi"), ("bluetooth", "Bluetooth")]),
            ("bluetooth",),
        )
        source = self._source()
        self.assertIn("MaterialCardButton", source)
        self.assertIn("ScrollableSurface", source)
        self.assertIn('self.search.trace_add("write"', source)
        self.assertNotIn('(\"apps\", \"Apps\", \"Apps\", AppsPage)', source)

    def test_radio_pages_only_use_generic_hal_model_and_explain_missing_provider(self) -> None:
        source = self._source()
        self.assertIn('class WifiPage(RadioPage):', source)
        self.assertIn('domain = "network"', source)
        self.assertIn('class BluetoothPage(RadioPage):', source)
        self.assertIn('domain = "bluetooth"', source)
        self.assertIn("self.app.model.hal_inventory", source)
        self.assertIn("self.app.model.hal_set_state", source)
        self.assertNotIn("wpa_cli", source)
        self.assertNotIn("dbus", source.lower())

    def test_bluetooth_separates_hal_power_from_audio_device_lifecycle(self) -> None:
        source = self._source()
        radio = source.split("class RadioPage", 1)[1].split(
            "class WifiPage", 1
        )[0]
        self.assertIn("self.app.model.audio_devices(refresh=True)", radio)
        self.assertIn("self.app.model.audio_scan_devices(15000)", radio)
        self.assertIn("self.app.model.audio_device_action(action, address)", radio)
        self.assertIn('lambda: self.apply_action("scan")', radio)
        self.assertIn("command=self.scan_bluetooth", radio)
        self.assertIn('columns=("name", "status", "address")', radio)
        self.assertIn("self._bluetooth_controller_registered", radio)
        self.assertNotIn('values.get("discovered_devices"', radio)
        self.assertNotIn("bluetoothctl", radio)

    def test_audio_page_uses_role_contract_and_reuses_bluetooth_pairing(self) -> None:
        source = self._source()
        audio = source.split("class AudioPage", 1)[1].split(
            "class LayoutPage", 1
        )[0]
        self.assertIn('("audio", "nav.audio", AudioPage)', source)
        self.assertIn("ScrollableSurface(self, background=PANEL)", audio)
        self.assertIn("MaterialStatusCard(", audio)
        self.assertIn("self.app.model.audio_state", audio)
        self.assertIn("self.app.model.audio_select_output", audio)
        self.assertIn("self.app.model.audio_set_volume", audio)
        self.assertIn("self.app.model.audio_set_muted", audio)
        self.assertIn("self.app.model.audio_configure_player", audio)
        self.assertIn('app.show_page("bluetooth")', audio)
        self.assertIn("if app.compact:\n            mute_actions", audio)
        self.assertIn("if isinstance(volume, int)", audio)
        self.assertIn("if isinstance(muted, bool)", audio)
        self.assertIn('else self.app.tr("common.unavailable")', audio)
        self.assertNotIn("pair(", audio)
        self.assertNotIn("bluetoothctl", audio)
        self.assertNotIn("dbus", audio.lower())

    def test_radio_actions_cover_saved_networks_scan_refresh_and_hard_block(self) -> None:
        source = self._source()
        self.assertIn("wifi_connect_changes(row, password)", source)
        self.assertIn("wifi_forget_changes(row)", source)
        self.assertIn('action="forget"', source)
        self.assertIn('state["values"].get("configuration_persisted")', source)
        self.assertIn("self.app.root.after(\n                    1200", source)
        self.assertIn("generation != self._state_generation", source)
        self.assertIn('state["values"].get("hard_blocked") is True', source)
        self.assertIn("self.power.set(self._confirmed_power)", source)

    def test_delayed_radio_scan_refresh_is_scoped_to_its_own_page(self) -> None:
        source = self._source()
        radio = source.split("class RadioPage", 1)[1].split(
            "class WifiPage", 1
        )[0]
        self.assertIn(
            'return "wifi" if self.domain == "network" else "bluetooth"',
            radio,
        )
        self.assertIn("page_key = self._page_key()", radio)
        self.assertIn("or page_key != self._page_key()", radio)
        self.assertIn("or self.app._active_page != page_key", radio)
        self.assertNotIn('self.app._active_page != "wifi"', radio)

    def test_input_method_entry_is_typed_and_unavailable_is_disabled(self) -> None:
        source = self._source()
        self.assertIn("self.app.model.input_method_status", source)
        self.assertIn("self.app.model.toggle_input_method", source)
        self.assertIn('self.keyboard_card.set_disabled(True)', source)

    def test_system_page_uses_cards_and_hides_raw_diagnostics_by_default(self) -> None:
        source = self._source()
        system_page = source.split("class SystemPage", 1)[1].split(
            "class RadioPage", 1
        )[0]
        self.assertIn("ScrollableSurface(self, background=PANEL)", system_page)
        self.assertIn("self._summary_card(", system_page)
        self.assertIn("self.diagnostics_visible = False", system_page)
        self.assertIn("def toggle_diagnostics", system_page)
        self.assertNotIn("self.details_frame.pack(fill=", system_page.split(
            "def toggle_diagnostics", 1
        )[0])

    def test_long_secondary_pages_use_the_shared_touch_scroll_surface(self) -> None:
        source = self._source()
        boundaries = (
            ("RolesPage", "HalPage"),
            ("HalPage", "Ch347ControlDialog"),
            ("AppsPage", "UpdatesPage"),
        )
        for page, following in boundaries:
            section = source.split(f"class {page}", 1)[1].split(
                f"class {following}", 1
            )[0]
            self.assertIn("ScrollableSurface(self, background=PANEL)", section)
        updates = source.split("class UpdatesPage", 1)[1]
        self.assertIn("ScrollableSurface(self, background=PANEL)", updates)

    def test_radio_and_hal_summaries_use_responsive_status_cards(self) -> None:
        source = self._source()
        radio = source.split("class RadioPage", 1)[1].split(
            "class WifiPage", 1
        )[0]
        hal = source.split("class HalPage", 1)[1].split(
            "class Ch347ControlDialog", 1
        )[0]
        self.assertIn("MaterialStatusCard(", radio)
        self.assertIn("MaterialStatusCard(", hal)
        self.assertIn("text_wrap_length(", hal)

    def test_compact_page_drag_can_start_over_tables_and_readonly_text(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "files/app/msys_settings/material.py"
        ).read_text(encoding="utf-8")
        exclusive = source.split("exclusive_pointer = {", 1)[1].split("}", 1)[0]
        self.assertNotIn('"Treeview"', exclusive)
        self.assertNotIn('"Text"', exclusive)
        self.assertIn('"TButton"', exclusive)
        self.assertIn('"TEntry"', exclusive)


if __name__ == "__main__":
    unittest.main()
