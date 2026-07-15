from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from msys_sdk.i18n import Catalog
from msys_settings.localization import ENGLISH_FALLBACK, SettingsI18n


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "files/share/i18n/catalog.json"


class SettingsI18nTests(unittest.TestCase):
    def test_shipped_catalog_is_valid_complete_and_bilingual(self) -> None:
        catalog = Catalog.load(CATALOG_PATH)
        self.assertEqual(catalog.id, "org.msys.settings")
        self.assertEqual(catalog.default_locale, "en-US")
        self.assertEqual(
            set(catalog.messages["en-US"]),
            set(catalog.messages["zh-CN"]),
        )
        self.assertEqual(catalog.messages["zh"], catalog.messages["zh-CN"])
        self.assertTrue(set(ENGLISH_FALLBACK).issubset(catalog.messages["en-US"]))

    def test_environment_locale_and_named_placeholders_are_used(self) -> None:
        i18n = SettingsI18n(environ={"MSYS_LOCALE": "zh_CN.UTF-8"})
        self.assertEqual(i18n.locale, "zh-CN")
        self.assertEqual(i18n.text("nav.system"), "系统")
        summary = i18n.text(
            "system.summary",
            {"ready": 3, "total": 4, "roles": 2, "services": 1},
        )
        self.assertIn("3/4", summary)
        self.assertIn("组件", summary)

        script_locale = SettingsI18n(
            environ={"MSYS_LOCALE": "zh-Hans-CN"}
        )
        self.assertEqual(script_locale.locale, "zh")
        self.assertEqual(script_locale.text("nav.system"), "系统")

    def test_extended_roles_hal_ch347_and_appearance_text_is_localized(self) -> None:
        i18n = SettingsI18n(environ={"MSYS_LOCALE": "zh_CN.UTF-8"})
        self.assertEqual(i18n.text("appearance.layout"), "布局")
        self.assertEqual(i18n.text("appearance.layout_kiosk"), "信息亭")
        self.assertEqual(
            i18n.text("roles.migration_pending", {
                "id": 7,
                "phase": "switching",
                "source": "old-provider",
                "target": "new-provider",
            }),
            "正在等待显示迁移 #7 · switching · old-provider → new-provider",
        )
        self.assertEqual(
            i18n.text("hal.summary", {"domains": 2, "devices": 3}),
            "2 个硬件域 · 3 个设备",
        )
        self.assertEqual(
            i18n.text("ch347.status", {"status": "可用", "running": "正在运行"}),
            "可用 · 正在运行",
        )
        self.assertEqual(
            i18n.text("display.debug_no_sample"),
            "暂无可信采样",
        )
        self.assertEqual(
            i18n.text("display.debug_capture_value", {"fps": "12.5"}),
            "捕获 12.5 FPS",
        )
        self.assertEqual(
            i18n.text("display.debug_dirty_note"),
            "自显示接收端启动后累计；这些数值不是采样速率。",
        )
        self.assertEqual(
            i18n.text("display.debug_dirty_pixels_value", {
                "sent_pixels": 1000,
                "last_sent_pixels": 320,
                "last_rects": 2,
            }),
            "总计 1000 · 上次 320 · 上次 2 个矩形",
        )
        self.assertEqual(
            i18n.text("apps.summary", {"count": 4}),
            "4 个已安装的软件包",
        )
        self.assertEqual(i18n.text("nav.audio"), "音频")
        self.assertEqual(
            i18n.text(
                "audio.status_unavailable",
                {"backend": "bluealsa", "reason": "控制器未注册"},
            ),
            "后端 bluealsa：控制器未注册",
        )

    def test_missing_catalog_recovers_with_english_without_sdk_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            i18n = SettingsI18n(Path(temporary) / "missing.json", locale="zh-CN")
        self.assertTrue(i18n.load_error)
        self.assertEqual(i18n.locale, "en-US")
        self.assertEqual(i18n.text("radio.wifi.title"), "Wi-Fi")
        self.assertEqual(
            i18n.text("status.loading_radio", {"radio": "Wi-Fi"}),
            "Loading Wi-Fi settings…",
        )

    def test_catalog_resource_is_plain_json_without_runtime_service_metadata(self) -> None:
        document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "msys.i18n.catalog.v1")
        self.assertNotIn("service", document)
        self.assertNotIn("role", document)

    def test_english_text_has_no_known_mojibake_symbols(self) -> None:
        document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        english = {
            **document["messages"]["en-US"],
            **ENGLISH_FALLBACK,
        }
        for key, value in english.items():
            for damaged in ("路", "鈥", "鈫", "掳"):
                self.assertNotIn(damaged, value, key)

    def test_static_ui_translation_keys_have_catalog_and_recovery_entries(self) -> None:
        keys: set[str] = set()
        key_prefixes = (
            "app.",
            "nav.",
            "home.",
            "common.",
            "status.",
            "system.",
            "display.",
            "radio.",
            "audio.",
            "keyboard.",
            "regional.",
            "appearance.",
            "apps.",
            "roles.",
            "hal.",
            "ch347.",
            "updates.",
        )
        for relative in (
            "files/app/msys_settings/ui.py",
            "files/app/msys_settings/__main__.py",
        ):
            module = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "tr"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    keys.add(node.args[0].value)
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith(key_prefixes)
                    and not node.value.endswith(".")
                ):
                    keys.add(node.value)
        catalog = Catalog.load(CATALOG_PATH)
        self.assertTrue(keys.issubset(catalog.messages["en-US"]))
        self.assertTrue(keys.issubset(ENGLISH_FALLBACK))

    def test_known_user_facing_ui_literals_do_not_bypass_the_catalog(self) -> None:
        module = ast.parse(
            (ROOT / "files/app/msys_settings/ui.py").read_text(encoding="utf-8")
        )
        literals = {
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for literal in (
            "Profile default",
            "Layout",
            "Wallpaper",
            "Icon size",
            "Select a role",
            "Core did not return a valid planned migration",
            "The requested provider was not selected.",
            "The active provider remains unchanged until succeeded.",
            "Hardware information unavailable",
            "HAL manager is not installed or not running",
            "No HAL domains were reported.",
            "CH347 controls",
            "The provider is not installed or not responding.",
            "Frame-rate update failed",
            "Calibration update failed",
            "Restart failed",
            "Installed packages unavailable",
        ):
            self.assertNotIn(literal, literals, literal)


if __name__ == "__main__":
    unittest.main()
