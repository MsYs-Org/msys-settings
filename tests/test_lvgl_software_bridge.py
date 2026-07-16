from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from lvgl_bridge import Bridge
from msys_settings.model import OperationResult


class SoftwareModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def installed_packages(self) -> OperationResult:
        return OperationResult(
            True,
            {
                "packages": [
                    {
                        "package": "org.example.alpha",
                        "version": "1.2.3",
                        "path": "/state/alpha",
                    },
                    {
                        "package": "org.example.beta",
                        "version": "2.0.0",
                        "path": "/state/beta",
                    },
                ]
            },
        )

    def request_update(self, action: str, source: str, package: str) -> OperationResult:
        self.calls.append((action, source, package))
        return OperationResult(
            True,
            {
                "schema": "msys.install-agent-result.v1",
                "operation": f"{action}_updates",
                "ok": True,
            },
        )

    def request_rollback(self, package: str) -> OperationResult:
        self.calls.append(("rollback", "", package))
        return OperationResult(False, {"operation": "rollback"}, "no previous", "NO_PREVIOUS")

    def request_uninstall(self, package: str) -> OperationResult:
        self.calls.append(("uninstall", "", package))
        return OperationResult(
            True,
            {
                "schema": "msys.install-agent-result.v1",
                "operation": "uninstall",
                "ok": True,
            },
        )


class LvglSoftwareBridgeTests(unittest.TestCase):
    def make_bridge(self) -> tuple[Bridge, SoftwareModel, list[dict[str, object]]]:
        model = SoftwareModel()
        with patch.dict(
            os.environ,
            {"MSYS_SETTINGS_MODE": "software-center", "MSYS_UPDATE_SOURCE": "index.json"},
        ):
            bridge = Bridge(model)  # type: ignore[arg-type]
        emitted: list[dict[str, object]] = []
        bridge.emit = emitted.append  # type: ignore[method-assign]
        return bridge, model, emitted

    def test_registry_is_exposed_as_bounded_dynamic_rows(self) -> None:
        bridge, _model, _emitted = self.make_bridge()
        fields = bridge.collect_apps()
        self.assertEqual(fields["software.available"], "1")
        self.assertEqual(fields["software.package_count"], "2")
        self.assertEqual(fields["software.package.0.id"], "org.example.alpha")
        self.assertEqual(fields["software.package.1.version"], "2.0.0")

    def test_update_actions_call_existing_model_and_wait_for_terminal_result(self) -> None:
        bridge, model, emitted = self.make_bridge()
        bridge.software_action("software_check", "all")
        self.assertEqual(model.calls, [("check", "index.json", "all")])
        self.assertEqual(emitted[0]["software.busy"], "1")
        self.assertEqual(emitted[1]["software.busy"], "0")
        self.assertIn("检查更新：成功", str(emitted[1]["software.operation"]))

    def test_agent_error_is_not_reported_as_success(self) -> None:
        bridge, model, emitted = self.make_bridge()
        bridge.software_action("software_rollback", "org.example.alpha")
        self.assertEqual(model.calls, [("rollback", "", "org.example.alpha")])
        terminal = emitted[1]
        self.assertIn("回退：失败", str(terminal["software.operation"]))
        self.assertIn("NO_PREVIOUS", str(terminal["software.operation"]))
        self.assertIn("操作失败", str(terminal["toast"]))


if __name__ == "__main__":
    unittest.main()
