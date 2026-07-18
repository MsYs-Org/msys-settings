from __future__ import annotations

import unittest

from msys_settings.model import SettingsModel


class InputClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def input_method_status(self):
        self.calls.append("status")
        return dict(self.payload)

    def toggle_input_method(self):
        self.calls.append("toggle")
        return dict(self.payload)

    def show_input_method(self):
        self.calls.append("show")
        response = dict(self.payload)
        response["visible"] = True
        return response

    def hide_input_method(self):
        self.calls.append("hide")
        response = dict(self.payload)
        response["visible"] = False
        return response

    def set_input_method_mode(self, mode):
        self.calls.append(("set_mode", mode))
        response = dict(self.payload)
        response["mode"] = mode
        return response


class InputMethodModelTests(unittest.TestCase):
    def test_typed_visible_state_is_preserved(self) -> None:
        client = InputClient({
            "ok": True,
            "schema": "msys.input-method-state.v1",
            "visible": True,
            "layout": "letters",
            "locale": "zh-CN",
            "mode": "zh",
        })
        model = SettingsModel(client)  # type: ignore[arg-type]
        result = model.input_method_status()
        self.assertTrue(result.ok)
        self.assertTrue(result.data["visible"])
        self.assertEqual(result.data["mode"], "zh")
        self.assertEqual(client.calls, ["status"])

    def test_malformed_state_is_not_shown_as_an_available_switch(self) -> None:
        model = SettingsModel(InputClient({
            "schema": "msys.input-method-state.v1",
            "visible": "yes",
        }))  # type: ignore[arg-type]
        result = model.toggle_input_method()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INPUT_METHOD_BAD_RESPONSE")

    def test_explicit_show_and_hide_do_not_depend_on_stale_toggle_state(self) -> None:
        client = InputClient({
            "schema": "msys.input-method-state.v1",
            "visible": False,
            "layout": "letters",
            "locale": "zh-CN",
            "mode": "zh",
        })
        model = SettingsModel(client)  # type: ignore[arg-type]
        shown = model.show_input_method()
        hidden = model.hide_input_method()
        self.assertTrue(shown.ok)
        self.assertTrue(shown.data["visible"])
        self.assertTrue(hidden.ok)
        self.assertFalse(hidden.data["visible"])
        self.assertEqual(client.calls, ["show", "hide"])

    def test_mode_selection_uses_existing_role_method(self) -> None:
        client = InputClient({
            "schema": "msys.input-method-state.v1",
            "visible": False,
            "layout": "letters",
            "locale": "en-US",
            "mode": "en",
        })
        result = SettingsModel(client).set_input_method_mode("zh")  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertEqual(result.data["mode"], "zh")
        self.assertEqual(client.calls, [("set_mode", "zh")])

    def test_invalid_mode_is_rejected_without_rpc(self) -> None:
        client = InputClient({})
        result = SettingsModel(client).set_input_method_mode("emoji")  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INPUT_METHOD_BAD_PAYLOAD")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
