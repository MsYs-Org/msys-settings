from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from msys_settings.regional import (
    REGIONAL_SCHEMA,
    RegionalSettingsStore,
    default_state_path,
)


class RegionalSettingsStoreTests(unittest.TestCase):
    def fixture(self, root: Path) -> RegionalSettingsStore:
        zoneinfo = root / "zoneinfo"
        (zoneinfo / "Asia").mkdir(parents=True)
        (zoneinfo / "UTC").write_bytes(b"utc")
        (zoneinfo / "Asia" / "Shanghai").write_bytes(b"shanghai")
        etc = root / "etc"
        etc.mkdir()
        return RegionalSettingsStore(
            root / "state" / "regional.json",
            zoneinfo_dir=zoneinfo,
            localtime_path=etc / "localtime",
            environ={},
        )

    def test_default_state_path_respects_an_explicit_empty_environment(self) -> None:
        self.assertEqual(
            default_state_path({}),
            Path.home() / ".local/state/msys-settings/regional.json",
        )
        self.assertEqual(
            default_state_path({"MSYS_COMPONENT_STATE_DIR": "/state/component"}),
            Path("/state/component/regional.json"),
        )

    def test_language_is_persisted_atomically_as_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.fixture(root)
            result = store.set_language("zh-CN")

            self.assertEqual(result["language"], "zh-CN")
            self.assertEqual(store.load()["language"], "zh-CN")
            document = json.loads(store.state_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], REGIONAL_SCHEMA)
            self.assertEqual(document["language"], "zh-CN")
            self.assertEqual(list(store.state_path.parent.glob("*.tmp-*")), [])

    def test_invalid_language_is_rejected_without_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.fixture(Path(temporary))
            with self.assertRaises(ValueError):
                store.set_language("zh-CN; reboot")
            self.assertFalse(store.state_path.exists())

    def test_timezone_replaces_localtime_with_valid_zoneinfo_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.fixture(Path(temporary))
            result = store.set_timezone("Asia/Shanghai")

            self.assertEqual(result["timezone"], "Asia/Shanghai")
            self.assertTrue(store.localtime_path.is_symlink())
            self.assertEqual(
                store.localtime_path.resolve(strict=True),
                (store.zoneinfo_dir / "Asia/Shanghai").resolve(strict=True),
            )
            self.assertEqual(store.load()["timezone"], "Asia/Shanghai")
            self.assertTrue(result["state_persisted"])

    def test_stale_json_timezone_never_overrides_real_localtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.fixture(root)
            store.set_timezone("Asia/Shanghai")
            document = json.loads(store.state_path.read_text(encoding="utf-8"))
            document["timezone"] = "UTC"
            store.state_path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(store.load()["timezone"], "Asia/Shanghai")

    def test_timezone_remains_truthfully_applied_when_local_cache_is_read_only(self) -> None:
        class CacheFailureStore(RegionalSettingsStore):
            def _save(self, state):  # type: ignore[no-untyped-def]
                del state
                raise OSError("state cache is read-only")

        with tempfile.TemporaryDirectory() as temporary:
            base = self.fixture(Path(temporary))
            store = CacheFailureStore(
                base.state_path,
                zoneinfo_dir=base.zoneinfo_dir,
                localtime_path=base.localtime_path,
                environ={},
            )
            result = store.set_timezone("Asia/Shanghai")
            self.assertEqual(result["timezone"], "Asia/Shanghai")
            self.assertFalse(result["state_persisted"])
            self.assertIn("read-only", result["state_warning"])

    def test_timezone_traversal_and_missing_zone_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.fixture(Path(temporary))
            for candidate in ("../UTC", "Asia/../../UTC", "/etc/passwd", "Missing"):
                with self.subTest(candidate=candidate):
                    with self.assertRaises((OSError, ValueError)):
                        store.set_timezone(candidate)
            self.assertFalse(store.localtime_path.exists())

    def test_symlink_that_escapes_zoneinfo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self.fixture(root)
            outside = root / "outside"
            outside.write_bytes(b"outside")
            os.symlink(outside, store.zoneinfo_dir / "Escape")
            self.assertFalse(store.validate_timezone("Escape"))

    def test_missing_backend_reports_unavailable_and_never_fakes_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RegionalSettingsStore(
                root / "state.json",
                zoneinfo_dir=root / "missing-zoneinfo",
                localtime_path=root / "missing-etc" / "localtime",
                environ={},
            )
            status = store.status()
            self.assertFalse(status["timezone_writable"])
            self.assertEqual(status["timezone_reason_code"], "zoneinfo-unavailable")
            self.assertEqual(status["timezones"], [])
            with self.assertRaises(OSError):
                store.set_timezone("UTC")

    def test_directory_localtime_target_is_strictly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.fixture(Path(temporary))
            store.localtime_path.mkdir()
            available, reason = store.timezone_capability()
            self.assertFalse(available)
            self.assertIn("directory", reason)
            with self.assertRaises(OSError):
                store.set_timezone("UTC")


if __name__ == "__main__":
    unittest.main()
