from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from msys_settings import __version__


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_release_version_is_consistent_in_all_three_locations(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_version = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', project_text
        )
        self.assertIsNotNone(project_version)
        self.assertEqual(__version__, "0.4.5")
        self.assertEqual(manifest["package"]["version"], __version__)
        self.assertEqual(project_version.group(1), __version__)

    def test_package_is_self_contained_and_launchable(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "msys.manifest.v1")
        self.assertEqual(manifest["package"]["id"], "org.msys.settings")
        self.assertEqual(manifest["package"]["version"], __version__)
        self.assertEqual(
            manifest["package"]["x-msys-i18n"],
            {
                "catalog": "files/share/i18n/catalog.json",
                "name_key": "app.name",
                "summary_key": "app.summary",
            },
        )
        project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_version = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', project_text
        )
        self.assertIsNotNone(project_version)
        self.assertEqual(project_version.group(1), __version__)
        self.assertIn('requires-python = ">=3.10"', project_text)
        component = manifest["components"][0]
        self.assertEqual(component["runtime"], "tk")
        self.assertEqual(component["readiness"]["mode"], "mipc-ready")
        self.assertIn(
            {
                "interface": "org.msys.application-navigation.v1",
                "exclusive": False,
                "priority": 100,
            },
            component["provides"],
        )
        self.assertIn(
            {
                "interface": "org.msys.settings.regional.v1",
                "exclusive": False,
                "priority": 100,
            },
            component["provides"],
        )
        self.assertTrue(component["activation"]["launchable"])
        self.assertEqual(component["activation"]["intents"][0]["action"], "settings-panel")
        self.assertEqual(component["isolation"], "baseline")
        self.assertNotIn("DISPLAY", component.get("env", {}))
        self.assertEqual(component["windowing"]["display"], "inherit")
        intent_names = {
            item["name"]
            for item in component["activation"]["intents"]
            if item["action"] == "settings-panel"
        }
        self.assertEqual(
            intent_names,
            {
                "system",
                "layout",
                "display",
                "wifi",
                "bluetooth",
                "audio",
                "appearance",
                "apps",
                "storage",
                "roles",
                "hal",
                "updates",
                "regional",
            },
        )
        permissions = set(component["permissions"])
        self.assertTrue({
            "display:x11",
            "mipc.call:msys.core",
            "mipc.call:role:window-manager",
            "mipc.call:role:launcher",
            "mipc.call:role:update-agent",
            "mipc.call:role:install-agent",
            "mipc.call:role:input-method",
            "mipc.call:role:audio-manager",
            "mipc.call:role:storage",
            "mipc.call:org.msys.hal.manager.v1",
            "mipc.call:org.msys.hal.ch347-control.v1",
            "mipc.event:subscribe:msys.activation",
            "mipc.event:subscribe:msys.hal.changed",
            "mipc.event:subscribe:msys.shell.preferences.changed",
            "mipc.event:subscribe:msys.display.migration",
            "mipc.event:subscribe:msys.audio.changed",
        }.issubset(permissions))
        event_topics = {
            "msys.activation",
            "msys.hal.changed",
            "msys.shell.preferences.changed",
            "msys.update.checked",
            "msys.update.applied",
            "msys.update.error",
            "msys.install.package_changed",
            "msys.install.error",
            "msys.display.migration",
            "msys.audio.changed",
        }
        self.assertTrue(
            {
                f"mipc.event:subscribe:{topic}"
                for topic in event_topics
            }.issubset(permissions)
        )
        entry = component["exec"][1].removeprefix("@package/")
        self.assertTrue((ROOT / entry).is_file())

        software = next(
            item for item in manifest["components"]
            if item["id"] == "software-center"
        )
        self.assertEqual(software["id"], "software-center")
        self.assertEqual(software["runtime"], "native")
        self.assertEqual(
            software["windowing"]["identity"],
            {
                "app_id": "org.msys.software-center",
                "x11_wm_class": "org.msys.software-center",
                "x11_wm_instance": "software-center",
            },
        )
        self.assertTrue(software["activation"]["launchable"])
        self.assertEqual(software["env"]["MSYS_SETTINGS_MODE"], "software-center")
        self.assertEqual(
            software["x-msys-ui-provider"]["fallback_component"],
            "org.msys.settings:software-center-tk",
        )
        software_ui = software["exec"][software["exec"].index("--ui") + 1]
        self.assertEqual(
            software_ui,
            "@package/files/share/ui/software-center.xml",
        )
        software_document = ROOT / "files/share/ui/software-center.xml"
        software_root = ET.parse(software_document).getroot()
        software_names = {
            node.attrib.get("name") for node in software_root.iter()
        }
        self.assertTrue({
            "software_apps_page",
            "software_updates_page",
            "software_detail_page",
            "software_package_list",
            "software_confirm",
        } <= software_names)
        self.assertEqual(
            {
                item["name"]
                for item in software["activation"]["intents"]
                if item["action"] == "software-center"
            },
            {"apps", "updates", "details", "uninstall"},
        )
        software_tk = next(
            item for item in manifest["components"]
            if item["id"] == "software-center-tk"
        )
        self.assertEqual(software_tk["runtime"], "tk")
        self.assertFalse(software_tk["activation"]["launchable"])

        native = next(
            item for item in manifest["components"]
            if item["id"] == "main-lvgl"
        )
        self.assertEqual(native["runtime"], "native")
        self.assertFalse(native["activation"]["launchable"])
        self.assertTrue({
            "mipc.call:role:launcher",
            "mipc.call:role:window-manager",
            "mipc.event:subscribe:msys.shell.preferences.changed",
            "mipc.event:subscribe:msys.layout.changed",
        }.issubset(set(native["permissions"])))
        self.assertEqual(
            native["x-msys-ui-provider"]["fallback_component"],
            "org.msys.settings:main",
        )
        self.assertTrue((ROOT / "files/app/lvgl_bridge.py").is_file())
        ui_index = native["exec"].index("--ui") + 1
        self.assertEqual(
            native["exec"][ui_index],
            "@package/files/share/ui/settings.xml",
        )
        document = ROOT / "files/share/ui/settings.xml"
        self.assertTrue(document.is_file())
        root = ET.parse(document).getroot()
        self.assertEqual(root.tag, "component")
        names = {node.attrib.get("name") for node in root.iter()}
        self.assertTrue(
            {
                "home_page", "detail_page", "home_content", "detail_content",
                "appearance_page", "appearance_content",
                "navigation_buttons", "navigation_pill",
                "wallpaper_color_input", "wallpaper_path_input",
                "animations_switch", "reduce_motion_switch",
            }
            <= names
        )
        bridge_source = (ROOT / "files/app/lvgl_bridge.py").read_text(encoding="utf-8")
        appearance_actions = bridge_source.split(
            'if name == "appearance_wallpaper":', 1
        )[1].split('if name == "software_page":', 1)[0]
        self.assertNotIn("restart", appearance_actions.lower())
        self.assertNotIn("x11display", appearance_actions.lower())
        self.assertNotIn("ch347", appearance_actions.lower())

    def test_launcher_icon_is_declared_and_is_a_valid_ppm(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        icons = manifest["package"]["icons"]
        self.assertEqual(len(icons), 1)
        icon = icons[0]
        self.assertEqual(icon["mime"], "image/x-portable-pixmap")
        path = ROOT / icon["path"]
        self.assertTrue(path.is_file())
        magic, comment, dimensions, maximum, pixels = path.read_bytes().split(b"\n", 4)
        self.assertEqual(magic, b"P6")
        self.assertTrue(comment.startswith(b"#"))
        self.assertEqual(dimensions, b"32 32")
        self.assertEqual(maximum, b"126")
        self.assertEqual(len(pixels.rstrip(b"\n")), 32 * 32 * 3)

    def test_no_systemd_or_dbus_runtime_dependency(self) -> None:
        manifest_text = (ROOT / "manifest.json").read_text(encoding="utf-8").lower()
        self.assertNotIn("systemd", manifest_text)
        self.assertNotIn("dbus", manifest_text)


if __name__ == "__main__":
    unittest.main()
