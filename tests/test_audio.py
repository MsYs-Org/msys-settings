from __future__ import annotations

import unittest

from msys_settings.audio import (
    bluetooth_address_request,
    muted_request,
    normalise_audio_devices,
    normalise_audio_state,
    output_request,
    player_request,
    volume_request,
)
from msys_settings.model import SettingsModel


def audio_state() -> dict:
    return {
        "schema": "msys.audio-state.v1",
        "backend": "bluealsa",
        "available": True,
        "reason": None,
        "controller_registered": True,
        "stack": [
            {"name": "private-bus", "pid": 10, "running": True, "returncode": None},
            {"name": "bluealsa", "pid": 11, "running": True, "returncode": None},
        ],
        "outputs": [
            {
                "id": "bluealsa:AA:BB:CC:DD:EE:FF:a2dp",
                "address": "AA:BB:CC:DD:EE:FF",
                "name": "Headphones",
                "profile": "a2dp",
                "connected": True,
                "mixer_control": "Headphones - A2DP",
                "volume_percent": 63,
                "muted": False,
            }
        ],
        "active_output": {
            "id": "bluealsa:AA:BB:CC:DD:EE:FF:a2dp",
            "name": "Headphones",
        },
        "volume_percent": 63,
        "muted": False,
        "player": {
            "enabled": True,
            "server": "10.0.0.2",
            "name": "Kitchen",
            "running": True,
        },
    }


def audio_devices() -> dict:
    return {
        "schema": "msys.audio-devices.v1",
        "devices": [
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "name": "Headphones",
                "alias": "Quiet Headset",
                "icon": "audio-card",
                "paired": True,
                "trusted": True,
                "connected": True,
            }
        ],
    }


class FakeAudioClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def audio_get_state(self, *, refresh: bool = False) -> dict:
        self.calls.append(("get_state", refresh))
        return audio_state()

    def audio_list_devices(self, *, refresh: bool = False) -> dict:
        self.calls.append(("list_devices", refresh))
        return audio_devices()

    def audio_scan(self, *, timeout_ms: int = 15000) -> dict:
        self.calls.append(("scan", timeout_ms))
        return audio_devices()

    def audio_device_action(self, action: str, payload: dict) -> dict:
        self.calls.append((action, payload))
        return {"ok": True, "operation": action, **audio_devices()}

    def audio_set_volume(self, payload: dict) -> dict:
        self.calls.append(("set_volume", payload))
        return audio_state()

    def audio_set_muted(self, payload: dict) -> dict:
        self.calls.append(("set_muted", payload))
        return audio_state()

    def audio_select_output(self, payload: dict) -> dict:
        self.calls.append(("select_output", payload))
        return audio_state()

    def audio_configure_player(self, payload: dict) -> dict:
        self.calls.append(("configure_player", payload))
        return audio_state()


class AudioStateTests(unittest.TestCase):
    def test_bluetooth_device_catalog_is_typed_bounded_and_sorted(self) -> None:
        payload = audio_devices()
        payload["devices"].insert(
            0,
            {
                "address": "11:22:33:44:55:66",
                "name": "Speaker",
                "alias": "Speaker",
                "icon": "audio-card",
                "paired": False,
                "trusted": False,
                "connected": False,
            },
        )
        view = normalise_audio_devices(payload)
        self.assertEqual(view["devices"][0]["name"], "Headphones")
        payload["scan"] = {
            "discovery_started": True,
            "duration_ms": 15000,
            "transport": "private-bluez",
            "result": "devices-found",
            "diagnostic": "discovery-complete",
        }
        view = normalise_audio_devices(payload)
        self.assertEqual(view["scan"]["duration_ms"], 15000)
        self.assertEqual(
            bluetooth_address_request("aa:bb:cc:dd:ee:ff"),
            {"address": "AA:BB:CC:DD:EE:FF"},
        )
        payload["devices"][0]["connected"] = "yes"
        with self.assertRaisesRegex(ValueError, "connected"):
            normalise_audio_devices(payload)
        payload["devices"][0]["connected"] = False
        payload["scan"]["duration_ms"] = 30001
        with self.assertRaisesRegex(ValueError, "scan metadata"):
            normalise_audio_devices(payload)
        with self.assertRaises(ValueError):
            bluetooth_address_request("AA; reboot")

    def test_model_routes_bluetooth_lifecycle_through_audio_role(self) -> None:
        client = FakeAudioClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        self.assertTrue(model.audio_devices(refresh=True).ok)
        self.assertTrue(model.audio_scan_devices(6000).ok)
        for action in ("pair", "connect", "disconnect", "forget"):
            self.assertTrue(
                model.audio_device_action(action, "aa:bb:cc:dd:ee:ff").ok
            )
        self.assertEqual(
            client.calls,
            [
                ("get_state", True),
                ("list_devices", True),
                ("scan", 6000),
                ("pair", {"address": "AA:BB:CC:DD:EE:FF"}),
                ("connect", {"address": "AA:BB:CC:DD:EE:FF"}),
                ("disconnect", {"address": "AA:BB:CC:DD:EE:FF"}),
                ("forget", {"address": "AA:BB:CC:DD:EE:FF"}),
            ],
        )

    def test_model_does_not_list_or_scan_without_registered_controller(self) -> None:
        client = FakeAudioClient()
        state = audio_state()
        state.update(
            {
                "available": False,
                "reason": "controller-not-registered",
                "controller_registered": False,
                "outputs": [],
                "active_output": None,
                "volume_percent": None,
                "muted": None,
            }
        )
        client.audio_get_state = lambda **_kwargs: state  # type: ignore[method-assign]
        result = SettingsModel(client).audio_devices(refresh=True)  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertFalse(result.data["controller_registered"])
        self.assertEqual(result.data["devices"], [])
        self.assertEqual(client.calls, [])

    def test_state_is_bounded_and_marks_the_active_output(self) -> None:
        state = normalise_audio_state(audio_state())
        self.assertTrue(state["available"])
        self.assertEqual(state["backend"], "bluealsa")
        self.assertEqual(state["active_output"], state["outputs"][0]["id"])
        self.assertTrue(state["outputs"][0]["active"])
        self.assertEqual(state["outputs"][0]["volume_percent"], 63)
        self.assertTrue(state["player"]["running"])

    def test_invalid_volume_duplicate_outputs_and_unknown_active_are_rejected(self) -> None:
        invalid = audio_state()
        invalid["volume_percent"] = True
        with self.assertRaisesRegex(ValueError, "active volume"):
            normalise_audio_state(invalid)

        duplicate = audio_state()
        duplicate["outputs"].append(dict(duplicate["outputs"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            normalise_audio_state(duplicate)

        unknown = audio_state()
        unknown["active_output"] = {"id": "missing"}
        with self.assertRaisesRegex(ValueError, "not in the output list"):
            normalise_audio_state(unknown)

    def test_mutation_payloads_are_typed_and_bounded(self) -> None:
        self.assertEqual(volume_request(45, "output-1"), {"percent": 45, "output": "output-1"})
        self.assertEqual(muted_request(True), {"muted": True})
        self.assertEqual(output_request("output-1"), {"id": "output-1"})
        self.assertEqual(
            player_request(True, "10.0.0.2", "Kitchen"),
            {"enabled": True, "server": "10.0.0.2", "name": "Kitchen"},
        )
        for operation in (
            lambda: volume_request(True),
            lambda: volume_request(101),
            lambda: muted_request(1),
            lambda: output_request(""),
            lambda: player_request(True, "host --bad", "Kitchen"),
            lambda: player_request(True, "", ""),
        ):
            with self.assertRaises(ValueError):
                operation()

    def test_model_routes_only_typed_audio_role_operations(self) -> None:
        client = FakeAudioClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        self.assertTrue(model.audio_state(refresh=True).ok)
        self.assertTrue(model.audio_set_volume(70, "output-1").ok)
        self.assertTrue(model.audio_set_muted(True, "output-1").ok)
        self.assertTrue(model.audio_select_output("output-1").ok)
        self.assertTrue(model.audio_configure_player(True, "server", "Desk").ok)
        self.assertEqual(
            client.calls,
            [
                ("get_state", True),
                ("set_volume", {"percent": 70, "output": "output-1"}),
                ("set_muted", {"muted": True, "output": "output-1"}),
                ("select_output", {"id": "output-1"}),
                (
                    "configure_player",
                    {"enabled": True, "server": "server", "name": "Desk"},
                ),
            ],
        )

    def test_model_rejects_bad_input_before_the_client(self) -> None:
        client = FakeAudioClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        result = model.audio_set_volume(200)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "AUDIO_BAD_PAYLOAD")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
