from __future__ import annotations

from pathlib import Path
import unittest

from msys_settings.client import CH347_CONTROL, SettingsClient
from msys_settings.ipc import MipcRemoteError
from msys_settings.model import (
    CH347_DEBUG_OVERLAY_ITEMS,
    CH347_CONTROL_SCHEMA,
    CH347_DEVICE,
    SettingsModel,
    normalise_ch347_debug_response,
    normalise_ch347_status,
    validate_ch347_debug_overlay,
    validate_ch347_debug_request,
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
        "sent_frames": None,
        "zero_damage": None,
        "full_refreshes": None,
        "large_refreshes": None,
        "sent_pixels": None,
        "last_sent_pixels": None,
        "last_rects": None,
        "status": "unavailable",
        "reason": "no machine-readable counter",
        "overlay": {
            "enabled": False,
            "alpha": 176,
            "scale": 1,
            "items": ["fps", "dirty", "bytes"],
            "interval_ms": 1000,
        },
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

    def ch347_set_debug(self, settings):
        self.calls.append(("set_debug", settings))
        enabled = settings if isinstance(settings, bool) else settings.get("enabled", False)
        overlay = (
            settings.get("overlay")
            if isinstance(settings, dict)
            else debug_response()["debug"]["overlay"]
        )
        return debug_response(
            enabled=enabled,
            overlay=overlay,
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
        client.ch347_set_debug({
            "enabled": False,
            "overlay": {
                "enabled": True,
                "alpha": 176,
                "scale": 1,
                "items": ["fps"],
                "interval_ms": 1000,
            },
        })
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
        self.assertTrue(rpc.calls[6][3]["idempotent"])
        self.assertNotIn("idempotent", rpc.calls[2][3])
        self.assertNotIn("idempotent", rpc.calls[4][3])
        self.assertEqual(
            rpc.calls[7][2],
            {"touch_calibration": {"invert_x": True}},
        )
        self.assertEqual(rpc.calls[4][2], {"enabled": True})
        self.assertEqual(rpc.calls[5][2]["overlay"]["items"], ["fps"])

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
        changed_overlay = model.ch347_set_debug({
            "enabled": True,
            "overlay": {
                "enabled": True,
                "alpha": 128,
                "scale": 2,
                "items": ["fps", "memory"],
                "interval_ms": 500,
            },
        })
        touch = model.ch347_set_touch_calibration(dict(CALIBRATION))
        restart = model.ch347_restart()
        self.assertTrue(fps.ok)
        self.assertTrue(debug.ok)
        self.assertIsNone(debug.data["debug"]["observed_fps"])
        self.assertTrue(changed_debug.ok)
        self.assertTrue(changed_debug.data["debug"]["enabled"])
        self.assertEqual(changed_debug.data["debug"]["provider_generation"], 9)
        self.assertTrue(changed_overlay.ok)
        self.assertEqual(changed_overlay.data["debug"]["overlay"]["alpha"], 128)
        self.assertTrue(changed_overlay.data["debug"]["overlay"]["available"])
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
        self.assertFalse(model.ch347_set_debug({"overlay": {"enabled": True}}).ok)
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
        for field in (
            "sent_frames",
            "zero_damage",
            "full_refreshes",
            "large_refreshes",
            "sent_pixels",
            "last_sent_pixels",
            "last_rects",
        ):
            self.assertIsNone(unavailable["debug"][field])

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

    def test_debug_response_accepts_complete_cumulative_dirty_counters(self) -> None:
        response = normalise_ch347_debug_response(debug_response(
            sent_frames=120,
            zero_damage=45,
            full_refreshes=2,
            large_refreshes=7,
            sent_pixels=9_876_543,
            last_sent_pixels=1_024,
            last_rects=3,
        ))
        self.assertEqual(
            {field: response["debug"][field] for field in (
                "sent_frames",
                "zero_damage",
                "full_refreshes",
                "large_refreshes",
                "sent_pixels",
                "last_sent_pixels",
                "last_rects",
            )},
            {
                "sent_frames": 120,
                "zero_damage": 45,
                "full_refreshes": 2,
                "large_refreshes": 7,
                "sent_pixels": 9_876_543,
                "last_sent_pixels": 1_024,
                "last_rects": 3,
            },
        )

    def test_old_debug_response_normalises_missing_dirty_counters_to_none(self) -> None:
        legacy = debug_response()
        for field in (
            "sent_frames",
            "zero_damage",
            "full_refreshes",
            "large_refreshes",
            "sent_pixels",
            "last_sent_pixels",
            "last_rects",
        ):
            legacy["debug"].pop(field)
        normalised = normalise_ch347_debug_response(legacy)["debug"]
        self.assertTrue(all(normalised[field] is None for field in (
            "sent_frames",
            "zero_damage",
            "full_refreshes",
            "large_refreshes",
            "sent_pixels",
            "last_sent_pixels",
            "last_rects",
        )))

    def test_old_debug_response_marks_overlay_unavailable_with_safe_defaults(self) -> None:
        legacy = debug_response()
        legacy["debug"].pop("overlay")
        overlay = normalise_ch347_debug_response(legacy)["debug"]["overlay"]
        self.assertFalse(overlay["available"])
        self.assertFalse(overlay["enabled"])
        self.assertEqual(overlay["alpha"], 176)
        self.assertEqual(overlay["scale"], 1)
        self.assertEqual(overlay["items"], ["fps", "dirty", "bytes"])
        self.assertEqual(overlay["interval_ms"], 1000)

    def test_debug_overlay_contract_is_strict_and_canonical(self) -> None:
        selected = validate_ch347_debug_overlay({
            "enabled": True,
            "alpha": 0,
            "scale": 2,
            "items": ["memory", "fps"],
            "interval_ms": 250,
        })
        self.assertEqual(selected["items"], ["fps", "memory"])
        self.assertEqual(set(CH347_DEBUG_OVERLAY_ITEMS), {
            "fps", "dirty", "bytes", "bbox", "memory",
        })
        self.assertEqual(validate_ch347_debug_request(False), {"enabled": False})
        for overlay in (
            {"enabled": False, "alpha": 256, "scale": 1, "items": ["fps"], "interval_ms": 1000},
            {"enabled": False, "alpha": 176, "scale": 3, "items": ["fps"], "interval_ms": 1000},
            {"enabled": False, "alpha": 176, "scale": 1, "items": [], "interval_ms": 1000},
            {"enabled": False, "alpha": 176, "scale": 1, "items": ["fps", "fps"], "interval_ms": 1000},
            {"enabled": False, "alpha": 176, "scale": 1, "items": ["fake"], "interval_ms": 1000},
            {"enabled": False, "alpha": 176, "scale": 1, "items": ["fps"], "interval_ms": 249},
        ):
            with self.subTest(overlay=overlay), self.assertRaises((TypeError, ValueError)):
                validate_ch347_debug_overlay(overlay)

    def test_malformed_dirty_counters_are_rejected(self) -> None:
        maximum = 18_446_744_073_709_551_615
        for field in (
            "sent_frames",
            "zero_damage",
            "full_refreshes",
            "large_refreshes",
            "sent_pixels",
            "last_sent_pixels",
            "last_rects",
        ):
            for value in (True, -1, "1", maximum + 1):
                with self.subTest(field=field, value=value):
                    with self.assertRaises((TypeError, ValueError)):
                        normalise_ch347_debug_response(debug_response(**{field: value}))
            boundary = normalise_ch347_debug_response(
                debug_response(**{field: maximum})
            )
            self.assertEqual(boundary["debug"][field], maximum)

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
            {"overlay": {"enabled": False}},
            {"overlay": {
                "enabled": False,
                "alpha": 176,
                "scale": 1,
                "items": ["fps", "unknown"],
                "interval_ms": 1000,
            }},
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
