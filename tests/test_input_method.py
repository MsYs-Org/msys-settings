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


if __name__ == "__main__":
    unittest.main()
