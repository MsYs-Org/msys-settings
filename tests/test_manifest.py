from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

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
        self.assertEqual(__version__, "0.2.11")
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
                "appearance",
                "apps",
                "roles",
                "hal",
                "updates",
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
            "mipc.call:org.msys.hal.manager.v1",
            "mipc.call:org.msys.hal.ch347-control.v1",
            "mipc.event:subscribe:msys.activation",
            "mipc.event:subscribe:msys.hal.changed",
            "mipc.event:subscribe:msys.shell.preferences.changed",
            "mipc.event:subscribe:msys.display.migration",
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
        }
        self.assertTrue(
            {
                f"mipc.event:subscribe:{topic}"
                for topic in event_topics
            }.issubset(permissions)
        )
        entry = component["exec"][1].removeprefix("@package/")
        self.assertTrue((ROOT / entry).is_file())

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
