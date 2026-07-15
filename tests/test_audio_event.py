from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

from msys_settings.ui import AudioPage, SettingsApplication


class _Root:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay: int, callback: object) -> None:
        self.after_calls.append((delay, callback))


class _EventPage:
    def __init__(self) -> None:
        self.refreshes = 0

    def external_change(self) -> None:
        self.refreshes += 1


class _BluetoothEventPage:
    def __init__(self) -> None:
        self.refreshes = 0

    def external_audio_change(self) -> None:
        self.refreshes += 1


class AudioEventTests(unittest.TestCase):
    def test_audio_changed_is_refresh_signal_not_status_text(self) -> None:
        audio = _EventPage()
        bluetooth = _BluetoothEventPage()
        app = object.__new__(SettingsApplication)
        app._closed = False
        app._ui_queue = queue.Queue()
        app._ui_queue.put(
            ("event", {"topic": "msys.audio.changed", "payload": {}}, None)
        )
        app._pages = {"audio": audio, "bluetooth": bluetooth}
        app.root = _Root()
        statuses: list[tuple[str, bool]] = []
        app.set_status = lambda message, error=False: statuses.append((message, error))

        with (
            patch("msys_settings.ui.AudioPage", _EventPage),
            patch("msys_settings.ui.BluetoothPage", _BluetoothEventPage),
        ):
            app._poll_queue()

        self.assertEqual(audio.refreshes, 1)
        self.assertEqual(bluetooth.refreshes, 1)
        self.assertEqual(statuses, [])
        self.assertEqual(len(app.root.after_calls), 1)

    def test_inactive_audio_page_becomes_stale_without_global_status(self) -> None:
        app = type("App", (), {"_active_page": "bluetooth"})()
        page = object.__new__(AudioPage)
        page.app = app
        page._loaded = True

        page.external_change()

        self.assertFalse(page._loaded)


if __name__ == "__main__":
    unittest.main()
