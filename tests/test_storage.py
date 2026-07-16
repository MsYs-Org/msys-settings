from __future__ import annotations

import unittest

from msys_settings.model import SettingsModel, TOUCH_CALIBRATION_COMPONENT


class StorageClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    @staticmethod
    def _state():
        return {
            "schema": "org.msys.hal.storage.v1",
            "auto_mount": True,
            "mount_root": "/media/msys",
            "volumes": [
                {
                    "id": "storage:sda1",
                    "name": "sda1",
                    "label": "USB",
                    "mounted": True,
                    "managed": True,
                    "mount_point": "/media/msys/USB",
                    "size_bytes": 1024,
                }
            ],
        }

    def storage_get_state(self):
        self.calls.append(("get_state", None))
        return self._state()

    def storage_refresh(self):
        self.calls.append(("refresh", None))
        return self._state()

    def storage_set_config(self, enabled):
        self.calls.append(("set_config", enabled))
        return self._state()

    def storage_mount(self, volume_id, *, read_only=False):
        self.calls.append(("mount", (volume_id, read_only)))
        return {"volume": {}}

    def storage_unmount(self, volume_id):
        self.calls.append(("unmount", volume_id))
        return {"volume": {}}


class CalibrationClient:
    def __init__(self) -> None:
        self.started = ""

    def list_components(self):
        return {"components": [{"id": TOUCH_CALIBRATION_COMPONENT, "state": "dormant"}]}

    def start_component(self, component):
        self.started = component
        return {"component": component, "state": "ready"}


class StorageAndCalibrationTests(unittest.TestCase):
    def test_storage_state_and_actions_use_the_role_client(self) -> None:
        client = StorageClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        state = model.storage_state()
        self.assertTrue(state.ok, state.message)
        self.assertEqual(state.data["volumes"][0]["name"], "USB")
        model.storage_set_auto_mount(False)
        model.storage_mount("storage:sda1", read_only=True)
        model.storage_unmount("storage:sda1")
        self.assertIn(("set_config", False), client.calls)
        self.assertIn(("mount", ("storage:sda1", True)), client.calls)
        self.assertIn(("unmount", "storage:sda1"), client.calls)

    def test_optional_calibration_is_discovered_and_started_through_core(self) -> None:
        client = CalibrationClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        self.assertTrue(model.touch_calibration_status().data["available"])
        self.assertTrue(model.start_touch_calibration().ok)
        self.assertEqual(client.started, TOUCH_CALIBRATION_COMPONENT)


if __name__ == "__main__":
    unittest.main()
