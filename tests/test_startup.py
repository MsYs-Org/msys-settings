from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "files" / "app" / "msys_settings"


class SupervisedStartupTests(unittest.TestCase):
    def test_component_reader_starts_before_initial_page_refresh(self) -> None:
        source = (ROOT / "__main__.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 10))
        self.assertIn("defer_initial_refresh=channel is not None", source)
        handshake = source.index("channel.handshake(")
        reader = source.index("channel.start(app.post_event)")
        refresh = source.index("app.start_initial_refresh()")
        run = source.index("app.run()")
        self.assertLess(handshake, reader)
        self.assertLess(reader, refresh)
        self.assertLess(refresh, run)

    def test_deferred_page_load_is_enabled_once(self) -> None:
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        module = ast.parse(source, feature_version=(3, 10))
        application = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsApplication"
        )
        methods = {
            node.name: node
            for node in application.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("start_initial_refresh", methods)
        show_source = ast.get_source_segment(source, methods["show_page"]) or ""
        start_source = (
            ast.get_source_segment(source, methods["start_initial_refresh"]) or ""
        )
        self.assertIn("if self._initial_refresh_enabled", show_source)
        self.assertIn("if self._initial_refresh_enabled", start_source)
        self.assertIn("self._initial_refresh_enabled = True", start_source)
        self.assertIn("self._pages[self._active_page].on_show()", start_source)


if __name__ == "__main__":
    unittest.main()
