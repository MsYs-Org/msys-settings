from __future__ import annotations

import queue
import threading
import unittest

from msys_settings.ui import SettingsApplication


class SettingsNavigationTests(unittest.TestCase):
    @staticmethod
    def application(active: str, history: list[str]) -> SettingsApplication:
        app = object.__new__(SettingsApplication)
        app._active_page = active
        app._page_history = list(history)
        app._pages = {"home": object(), "wifi": object(), "bluetooth": object()}

        def show_page(name: str, *, record_history: bool = True) -> None:
            if record_history and name != app._active_page:
                app._page_history.append(app._active_page)
            app._active_page = name

        app.show_page = show_page  # type: ignore[method-assign]
        return app

    def test_back_returns_to_exact_previous_page(self) -> None:
        app = self.application("bluetooth", ["home", "wifi"])
        self.assertTrue(app.navigate_back())
        self.assertEqual(app._active_page, "wifi")
        self.assertEqual(app._page_history, ["home"])

    def test_secondary_page_without_history_returns_home(self) -> None:
        app = self.application("bluetooth", [])
        self.assertTrue(app.navigate_back())
        self.assertEqual(app._active_page, "home")

    def test_root_page_is_not_handled_so_system_can_restore_previous_task(self) -> None:
        app = self.application("home", [])
        self.assertFalse(app.navigate_back())
        self.assertEqual(app._active_page, "home")

    def test_regional_mutation_is_marshalled_to_the_tk_thread(self) -> None:
        app = object.__new__(SettingsApplication)
        app._ui_queue = queue.Queue()
        replies: list[dict[str, object]] = []
        worker = threading.Thread(
            target=lambda: replies.append(
                app.handle_call({
                    "method": "set_language",
                    "payload": {"language": "zh-CN"},
                })
            )
        )
        worker.start()
        kind, request, reply = app._ui_queue.get(timeout=1)
        self.assertEqual(kind, "regional")
        self.assertEqual(request, ("set_language", {"language": "zh-CN"}))
        reply.put({"ok": True, "language": "zh-CN"})
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies, [{"ok": True, "language": "zh-CN"}])

    def test_regional_mutation_rejects_non_object_payload_without_queueing(self) -> None:
        app = object.__new__(SettingsApplication)
        app._ui_queue = queue.Queue()
        result = app.handle_call({"method": "set_timezone", "payload": "UTC"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BAD_REQUEST")
        self.assertTrue(app._ui_queue.empty())


if __name__ == "__main__":
    unittest.main()
