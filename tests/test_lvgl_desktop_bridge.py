from __future__ import annotations

import unittest

from lvgl_bridge import Bridge
from msys_settings.model import OperationResult


class DesktopModel:
    def __init__(self) -> None:
        self.preferences: dict[str, object] = {
            "layout": "profile",
            "wallpaper_color": "#F4F6FA",
            "accent_color": "#356AE6",
            "icon_size": 64,
            "show_labels": True,
            "sort": "name",
            "wallpaper_path": "",
            "grid_columns": 0,
            "grid_rows": 0,
            "acrylic": False,
            "navigation_mode": "pill",
            "navigation_visibility": "always",
            "status_visibility": "always",
            "icon_spacing": 8,
            "folders_enabled": True,
            "large_folders_enabled": True,
            "animations_enabled": True,
            "reduce_motion": False,
        }
        self.calls: list[tuple[object, ...]] = []

    def get_layout(self) -> OperationResult:
        self.calls.append(("get_layout",))
        return OperationResult(True, {
            "schema": "msys.window-layout.v1",
            "effective": {
                "profile": "mobile",
                "orientation_policy": "portrait",
                "insets_policy": "0,0,42,0",
            },
        })

    def desktop_preferences(self) -> OperationResult:
        self.calls.append(("get_preferences",))
        return OperationResult(True, {
            "schema": "msys.shell-preferences.v1",
            "revision": 7,
            "preferences": dict(self.preferences),
        })

    def update_desktop_preferences(
        self, changes: dict[str, object]
    ) -> OperationResult:
        self.calls.append(("set_preferences", dict(changes)))
        self.preferences.update(changes)
        return OperationResult(True, {
            "schema": "msys.shell-preferences.v1",
            "revision": 8,
            "preferences": dict(self.preferences),
        })

    def set_layout(
        self, profile: str, orientation: str, insets: str
    ) -> OperationResult:
        self.calls.append(("set_layout", profile, orientation, insets))
        return OperationResult(True, {
            "profile": profile,
            "orientation_policy": orientation,
            "insets_policy": insets,
        })


class LvglDesktopBridgeTests(unittest.TestCase):
    def make_bridge(self) -> tuple[Bridge, DesktopModel, list[dict[str, object]]]:
        model = DesktopModel()
        bridge = Bridge(model)  # type: ignore[arg-type]
        emitted: list[dict[str, object]] = []
        bridge.emit = emitted.append  # type: ignore[method-assign]
        return bridge, model, emitted

    def test_snapshot_is_exactly_the_shell_063_preferences_shape(self) -> None:
        bridge, _model, _emitted = self.make_bridge()
        fields = bridge.collect_layout()
        self.assertEqual(fields["appearance.contract.available"], "1")
        self.assertEqual(fields["appearance.preference.layout"], "profile")
        self.assertEqual(fields["appearance.preference.navigation_mode"], "pill")
        self.assertEqual(fields["appearance.preference.navigation_visibility"], "always")
        self.assertEqual(fields["appearance.preference.status_visibility"], "always")
        self.assertEqual(fields["appearance.preference.grid_columns"], 0)
        self.assertEqual(fields["appearance.preference.icon_spacing"], 8)
        self.assertEqual(fields["appearance.preference.wallpaper_path"], "")
        self.assertEqual(fields["appearance.preference.acrylic"], "0")
        self.assertEqual(fields["appearance.preference.animations_enabled"], "1")
        self.assertEqual(fields["appearance.orientation"], "portrait")

    def test_all_launcher_controls_hot_update_without_display_restart(self) -> None:
        bridge, model, _emitted = self.make_bridge()
        actions = (
            ("appearance_set_layout", "mobile"),
            ("appearance_set_layout", "profile"),
            ("appearance_set_navigation_mode", "buttons"),
            ("appearance_set_navigation_visibility", "auto-hide"),
            ("appearance_set_status_visibility", "auto-hide"),
            ("grid_columns", "4"),
            ("grid_rows", "5"),
            ("icon_size", "72"),
            ("icon_spacing", "12"),
            ("appearance_wallpaper", "#EAF1FF/media/msys/wallpaper.ppm"),
            ("acrylic", "1"),
            ("animations_enabled", "0"),
            ("reduce_motion", "1"),
        )
        for name, value in actions:
            bridge.action(name, value)
        writes = [call for call in model.calls if call[0] == "set_preferences"]
        self.assertEqual(len(writes), len(actions))
        self.assertEqual(model.preferences["layout"], "profile")
        self.assertEqual(model.preferences["navigation_mode"], "buttons")
        self.assertEqual(model.preferences["navigation_visibility"], "auto-hide")
        self.assertEqual(model.preferences["status_visibility"], "auto-hide")
        self.assertEqual(model.preferences["grid_columns"], "4")
        self.assertEqual(model.preferences["icon_size"], "72")
        self.assertEqual(model.preferences["wallpaper_color"], "#EAF1FF")
        self.assertEqual(
            model.preferences["wallpaper_path"], "/media/msys/wallpaper.ppm"
        )
        self.assertTrue(model.preferences["acrylic"])
        self.assertFalse(model.preferences["animations_enabled"])
        self.assertTrue(model.preferences["reduce_motion"])
        operation_names = {str(call[0]) for call in model.calls}
        self.assertFalse(any("restart" in name for name in operation_names))
        self.assertFalse(any("x11" in name or "spi" in name for name in operation_names))

    def test_orientation_preserves_profile_and_insets_without_restart(self) -> None:
        bridge, model, emitted = self.make_bridge()
        bridge.action("appearance_orientation", "landscape")
        self.assertIn(
            ("set_layout", "mobile", "landscape", "0,0,42,0"),
            model.calls,
        )
        self.assertEqual(emitted[-1]["appearance.orientation"], "landscape")
        self.assertNotIn("restart", " ".join(str(call) for call in model.calls).lower())


if __name__ == "__main__":
    unittest.main()
