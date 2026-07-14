from __future__ import annotations

import unittest

from msys_settings.ipc import MipcRemoteError
from msys_settings.model import SettingsModel, uninstall_confirmation


class AppsClient:
    def __init__(self) -> None:
        self.uninstalled: list[str] = []

    def request_registry(self):
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "registry",
            "ok": True,
            "result": {
                "schema": "msys.installed.v1",
                "packages": [
                    {
                        "package": "org.example.zeta",
                        "version": "2.0.0",
                        "path": "/state/zeta",
                    },
                    {
                        "package": "org.example.alpha",
                        "version": "1.0.0",
                        "path": "/state/alpha",
                    },
                ],
            },
        }

    def request_uninstall(self, package):
        self.uninstalled.append(package)
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "uninstall",
            "ok": True,
            "package": package,
            "version": "1.0.0",
            "action": "uninstall",
        }


class UninstallErrorClient(AppsClient):
    def request_uninstall(self, package):
        raise MipcRemoteError(
            "INSTALL_COMMIT_HEALTH_FAILED",
            "remaining catalog did not become healthy",
            {
                "schema": "msys.install-agent-error.v1",
                "operation": "uninstall",
                "details": {"package": package, "recovery_complete": True},
            },
        )


class AppsModelTests(unittest.TestCase):
    def test_registry_is_validated_and_sorted_for_refresh(self) -> None:
        result = SettingsModel(AppsClient()).installed_packages()  # type: ignore[arg-type]
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            [item["package"] for item in result.data["packages"]],
            ["org.example.alpha", "org.example.zeta"],
        )
        self.assertEqual(result.data["registry"]["schema"], "msys.installed.v1")

    def test_uninstall_waits_for_typed_terminal_success(self) -> None:
        client = AppsClient()
        result = SettingsModel(client).request_uninstall("org.example.alpha")  # type: ignore[arg-type]
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["schema"], "msys.install-agent-result.v1")
        self.assertEqual(result.data["operation"], "uninstall")
        self.assertEqual(client.uninstalled, ["org.example.alpha"])

    def test_invalid_package_is_rejected_before_rpc(self) -> None:
        client = AppsClient()
        result = SettingsModel(client).request_uninstall("../../root")  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "BAD_PACKAGE")
        self.assertEqual(client.uninstalled, [])

    def test_structured_uninstall_error_is_preserved(self) -> None:
        result = SettingsModel(UninstallErrorClient()).request_uninstall(  # type: ignore[arg-type]
            "org.example.alpha"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INSTALL_COMMIT_HEALTH_FAILED")
        self.assertEqual(result.data["schema"], "msys.install-agent-error.v1")
        self.assertEqual(result.data["operation"], "uninstall")
        self.assertTrue(result.data["details"]["recovery_complete"])


class AppsConfirmationTests(unittest.TestCase):
    def test_danger_confirmation_names_exact_package_and_is_irreversible(self) -> None:
        title, prompt = uninstall_confirmation("org.example.alpha", "1.0.0")
        self.assertEqual(title, "Uninstall package")
        self.assertIn("org.example.alpha", prompt)
        self.assertIn("1.0.0", prompt)
        self.assertIn("health gate", prompt)
        self.assertIn("cannot be undone", prompt)


if __name__ == "__main__":
    unittest.main()
