from pathlib import Path
import unittest

from msys_settings.ui import _configure_if_changed, _replace_after


ROOT = Path(__file__).resolve().parents[1]


class FakeWidget:
    def __init__(self, **options: object) -> None:
        self.options = dict(options)
        self.configure_calls: list[dict[str, object]] = []

    def cget(self, name: str) -> object:
        return self.options[name]

    def configure(self, **options: object) -> None:
        self.configure_calls.append(dict(options))
        self.options.update(options)


class FakeScheduler:
    def __init__(self) -> None:
        self.next_id = 0
        self.cancelled: list[str] = []
        self.scheduled: list[tuple[int, object]] = []

    def after(self, delay: int, callback: object) -> str:
        self.next_id += 1
        self.scheduled.append((delay, callback))
        return f"after-{self.next_id}"

    def after_cancel(self, identifier: str) -> None:
        self.cancelled.append(identifier)


class RepaintTests(unittest.TestCase):
    def test_configure_if_changed_suppresses_identical_widget_updates(self) -> None:
        widget = FakeWidget(state="disabled", background="#101419")
        self.assertFalse(_configure_if_changed(widget, state="disabled"))
        self.assertEqual(widget.configure_calls, [])
        self.assertTrue(_configure_if_changed(widget, state="normal"))
        self.assertEqual(widget.configure_calls, [{"state": "normal"}])
        self.assertFalse(_configure_if_changed(widget, state="normal"))

    def test_replace_after_keeps_only_the_latest_short_debounce(self) -> None:
        scheduler = FakeScheduler()
        callback = object()
        first = _replace_after(scheduler, None, 50, callback)  # type: ignore[arg-type]
        second = _replace_after(scheduler, first, 55, callback)  # type: ignore[arg-type]
        self.assertEqual(first, "after-1")
        self.assertEqual(second, "after-2")
        self.assertEqual(scheduler.cancelled, ["after-1"])
        self.assertEqual([delay for delay, _callback in scheduler.scheduled], [50, 55])

    def test_ui_hot_paths_use_incremental_updates(self) -> None:
        source = (ROOT / "files/app/msys_settings/ui.py").read_text(encoding="utf-8")
        appearance = source.split("class AppearancePage", 1)[1].split(
            "class RolesPage", 1
        )[0]
        navigation = source.split("def _schedule_navigation_filter", 1)[1].split(
            "def show_page", 1
        )[0]
        radio = source.split("def _update_network_actions", 1)[1].split(
            "def apply_power", 1
        )[0]
        self.assertNotIn('canvas.delete("all")', appearance)
        self.assertIn("canvas.coords(", appearance)
        self.assertIn("self._preview_signature", appearance)
        self.assertIn("visible == self._nav_visible", navigation)
        self.assertIn("_configure_if_changed(", radio)


if __name__ == "__main__":
    unittest.main()
