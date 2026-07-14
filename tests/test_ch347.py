from __future__ import annotations

from pathlib import Path
import unittest

from msys_settings.client import CH347_CONTROL, SettingsClient
from msys_settings.ipc import MipcRemoteError
from msys_settings.model import (
    CH347_CONTROL_SCHEMA,
    CH347_DEVICE,
    SettingsModel,
    normalise_ch347_debug_response,
    normalise_ch347_status,
    validate_ch347_calibration,
    validate_ch347_fps,
)


CALIBRATION = {
    "enabled": True,
    "swap_xy": False,
    "invert_x": False,
    "invert_y": True,
    "x_min": 207,
    "x_max": 3859,
    "y_min": 239,
    "y_max": 3836,
    "width": 320,
    "height": 480,
    "z_min": 109,
    "pressure_min": 100,
    "pressure_max": 568,
}


def debug_response(**changes):
    debug = {
        "enabled": False,
        "applied": True,
        "requires_restart": False,
        "provider_generation": 8,
        "fps": 60,
        "max_fps": 60,
        "idle_fps": 1,
        "observed_fps": None,
        "panel_fps": None,
        "frames": None,
        "window_ms": None,
        "status": "unavailable",
        "reason": "no machine-readable counter",
    }
    debug.update(changes)
    return {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "debug": debug,
    }


def status_response(**changes):
    state = {
        "status": "available",
        "reason": "healthy",
        "running": True,
        "component": "org.msys.openstick.ch347:x11-spi-touch-output",
        "component_state": "ready",
        "package_version": "0.1.0",
        "live_processes": 3,
        "configuration_valid": True,
        "configuration_provisioned": True,
        "configuration_errors": [],
        "fps": 60,
        "idle_fps": 1,
        "touch_calibration": dict(CALIBRATION),
        "physical_rotation": "normal",
        "physical_rotation_control": "writable",
        "restart": False,
        "debug": debug_response()["debug"],
    }
    state.update(changes)
    return {
        "schema": CH347_CONTROL_SCHEMA,
        "device": CH347_DEVICE,
        "state": state,
        "mutable": ["physical_rotation"],
    }


class FakeRpc:
    def __init__(self) -> None:
        self.calls = []

    def call(self, target, method, payload=None, **options):
        self.calls.append((target, method, payload or {}, options))
        return {"ok": True}


class Ch347Client:
    def __init__(self) -> None:
        self.calls = []

    def ch347_status(self):
        self.calls.append(("status",))
        return status_response()

    def hal_inventory(self, *, refresh=False):
        raise MipcRemoteError("NO_PROVIDER", "native HAL has no provider routing")

    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        raise MipcRemoteError("NO_PROVIDER", "native HAL has no provider routing")

    def ch347_set_fps(self, fps, idle_fps):
        self.calls.append(("set_fps", fps, idle_fps))
        return {
            "schema": CH347_CONTROL_SCHEMA,
            "device": CH347_DEVICE,
            "fps": fps,
            "idle_fps": idle_fps,
        }

    def ch347_get_debug(self):
        self.calls.append(("get_debug",))
        return debug_response()

    def ch347_set_debug(self, enabled):
        self.calls.append(("set_debug", enabled))
        return debug_response(
            enabled=enabled,
            provider_generation=9,
            status="active" if enabled else "idle",
            reason="debug overlay active" if enabled else "debug overlay disabled",
        )

    def ch347_set_touch_calibration(self, calibration):
        self.calls.append(("set_touch_calibration", calibration))
        return {
            "schema": CH347_CONTROL_SCHEMA,
            "device": CH347_DEVICE,
            "touch_calibration": calibration,
            "status": "available",
        }

    def ch347_restart(self):
        self.calls.append(("restart",))
        return status_response()

    def ch347_set_physical_rotation(self, rotation):
        self.calls.append(("set_physical_rotation", rotation))
        return status_response(physical_rotation=rotation)


class Ch347UnavailableClient(Ch347Client):
    def ch347_status(self):
        raise MipcRemoteError(
            "NO_PROVIDER",
            "CH347 control provider is not installed",
        )


class Ch347Tests(unittest.TestCase):
    def test_client_uses_typed_interface_and_long_timeouts(self) -> None:
        rpc = FakeRpc()
        client = SettingsClient(rpc)  # type: ignore[arg-type]
        client.ch347_status()
        client.ch347_get_fps()
        client.ch347_set_fps(60, 1)
        client.ch347_get_debug()
        client.ch347_set_debug(True)
        client.ch347_get_touch_calibration()
        client.ch347_set_touch_calibration({"invert_x": True})
        client.ch347_set_physical_rotation("right")
        client.ch347_restart()

        self.assertTrue(all(call[0] == CH347_CONTROL for call in rpc.calls))
        self.assertEqual(
            [call[1] for call in rpc.calls],
            [
                "status",
                "get_fps",
                "set_fps",
                "get_debug",
                "set_debug",
                "get_touch_calibration",
                "set_touch_calibration",
                "set_physical_rotation",
                "restart",
            ],
        )
        self.assertTrue(all(call[3]["timeout"] >= 30.0 for call in rpc.calls))
        self.assertTrue(rpc.calls[0][3]["idempotent"])
        self.assertTrue(rpc.calls[1][3]["idempotent"])
        self.assertTrue(rpc.calls[3][3]["idempotent"])
        self.assertTrue(rpc.calls[5][3]["idempotent"])
        self.assertNotIn("idempotent", rpc.calls[2][3])
        self.assertNotIn("idempotent", rpc.calls[4][3])
        self.assertEqual(
            rpc.calls[6][2],
            {"touch_calibration": {"invert_x": True}},
        )
        self.assertEqual(rpc.calls[4][2], {"enabled": True})

    def test_model_exposes_status_and_validated_typed_writes(self) -> None:
        client = Ch347Client()
        model = SettingsModel(client)  # type: ignore[arg-type]
        status = model.ch347_status()
        self.assertTrue(status.ok)
        self.assertTrue(status.data["state"]["running"])
        self.assertEqual(status.data["state"]["fps"], 60)

        fps = model.ch347_set_fps(30, 0)
        debug = model.ch347_get_debug()
        changed_debug = model.ch347_set_debug(True)
        touch = model.ch347_set_touch_calibration(dict(CALIBRATION))
        restart = model.ch347_restart()
        self.assertTrue(fps.ok)
        self.assertTrue(debug.ok)
        self.assertIsNone(debug.data["debug"]["observed_fps"])
        self.assertTrue(changed_debug.ok)
        self.assertTrue(changed_debug.data["debug"]["enabled"])
        self.assertEqual(changed_debug.data["debug"]["provider_generation"], 9)
        self.assertTrue(touch.ok)
        self.assertTrue(restart.ok)
        self.assertIn(("set_fps", 30, 0), client.calls)
        self.assertIn(("get_debug",), client.calls)
        self.assertIn(("set_debug", True), client.calls)
        self.assertEqual(
            next(call for call in client.calls if call[0] == "set_touch_calibration")[1],
            CALIBRATION,
        )

        rotation = model.physical_rotation()
        self.assertTrue(rotation.ok)
        self.assertTrue(rotation.data["writable"])
        self.assertEqual(rotation.data["value"], "normal")
        changed_rotation = model.set_physical_rotation(CH347_DEVICE, "left")
        self.assertTrue(changed_rotation.ok)
        self.assertIn(("set_physical_rotation", "left"), client.calls)

    def test_invalid_values_never_reach_provider(self) -> None:
        client = Ch347Client()
        model = SettingsModel(client)  # type: ignore[arg-type]
        self.assertFalse(model.ch347_set_fps(0, 0).ok)
        self.assertFalse(model.ch347_set_fps(30, 31).ok)
        self.assertFalse(model.ch347_set_debug(1).ok)
        invalid = dict(CALIBRATION, x_min=4000, x_max=3000)
        result = model.ch347_set_touch_calibration(invalid)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INVALID_CH347_CONFIG")
        self.assertEqual(client.calls, [])

    def test_debug_response_keeps_measurements_optional_and_never_invents_fps(self) -> None:
        unavailable = normalise_ch347_debug_response(debug_response())
        self.assertEqual(unavailable["debug"]["status"], "unavailable")
        self.assertIsNone(unavailable["debug"]["observed_fps"])
        self.assertIsNone(unavailable["debug"]["panel_fps"])
        self.assertIsNone(unavailable["debug"]["frames"])
        self.assertIsNone(unavailable["debug"]["window_ms"])

        measured = normalise_ch347_debug_response(debug_response(
            observed_fps=23.5,
            panel_fps=1.25,
            frames=20,
            window_ms=None,
            status="active",
            reason="sample counter does not expose its window",
        ))
        self.assertEqual(measured["debug"]["observed_fps"], 23.5)
        self.assertEqual(measured["debug"]["panel_fps"], 1.25)
        self.assertEqual(measured["debug"]["frames"], 20)
        self.assertIsNone(measured["debug"]["window_ms"])

        boundary = normalise_ch347_debug_response(debug_response(
            observed_fps=1000.0,
            panel_fps=1000.0,
            frames=4_294_967_295,
            status="active",
        ))
        self.assertEqual(boundary["debug"]["frames"], 4_294_967_295)

    def test_malformed_debug_response_is_rejected(self) -> None:
        for changes in (
            {"enabled": 1},
            {"max_fps": 0},
            {"max_fps": 30},
            {"observed_fps": "60"},
            {"panel_fps": "1.25"},
            {"observed_fps": 1000.1},
            {"panel_fps": 1000.1},
            {"frames": 4_294_967_296},
            {"status": "pretend-active"},
            {"provider_generation": True},
            {"reason": "x" * 1025},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises((TypeError, ValueError)):
                    normalise_ch347_debug_response(debug_response(**changes))

    def test_unavailable_provider_is_a_structured_result(self) -> None:
        result = SettingsModel(Ch347UnavailableClient()).ch347_status()  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "NO_PROVIDER")
        self.assertIn("not installed", result.message)

    def test_missing_rotation_capability_is_not_presented_as_readonly_success(self) -> None:
        client = Ch347Client()
        response = status_response(physical_rotation_control="unavailable")
        response["mutable"] = []
        client.ch347_status = lambda: response  # type: ignore[method-assign]
        result = SettingsModel(client).physical_rotation()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertFalse(result.data["available"])
        self.assertFalse(result.data["writable"])

    def test_malformed_typed_response_is_rejected(self) -> None:
        malformed = status_response()
        malformed["schema"] = "org.example.wrong.v1"
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            normalise_ch347_status(malformed)

    def test_contract_ranges_and_boolean_types_are_strict(self) -> None:
        self.assertEqual(validate_ch347_fps(240, 60), (240, 60))
        self.assertEqual(
            validate_ch347_calibration(dict(CALIBRATION), require_all=True),
            CALIBRATION,
        )
        with self.assertRaises(TypeError):
            validate_ch347_fps(True, 0)
        with self.assertRaises(TypeError):
            validate_ch347_calibration(
                dict(CALIBRATION, enabled=1),
                require_all=True,
            )
        with self.assertRaises(ValueError):
            validate_ch347_calibration(
                dict(CALIBRATION, width=8193),
                require_all=True,
            )

    def test_ui_keeps_generic_editor_and_adds_confirmed_typed_controls(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "files/app/msys_settings/ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class Ch347ControlDialog", source)
        self.assertIn("self.app.model.ch347_status", source)
        self.assertIn("self.app.model.ch347_set_fps", source)
        self.assertIn("self.app.model.ch347_get_debug", source)
        self.assertIn("self.app.model.ch347_set_debug", source)
        self.assertIn("self.app.model.ch347_set_touch_calibration", source)
        self.assertIn("self.app.model.ch347_restart", source)
        self.assertIn('default=messagebox.NO', source)
        self.assertIn('self.state = tk.Text(', source)
        self.assertIn('hal_state_changes(', source)
        layout_page = source.split("class LayoutPage", 1)[1].split(
            "class AppearancePage", 1
        )[0]
        self.assertIn('text=app.tr("display.debug_title")', layout_page)
        self.assertIn("self.refresh_debug", layout_page)
        self.assertIn("debug.get(\"observed_fps\")", layout_page)
        self.assertIn('self.app.tr("display.debug_confirm_title")', layout_page)
        self.assertIn("default=messagebox.NO", layout_page)


if __name__ == "__main__":
    unittest.main()
