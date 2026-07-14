from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PythonCompatibilityTests(unittest.TestCase):
    def test_all_shipped_python_uses_python_310_grammar(self) -> None:
        paths = sorted((ROOT / "files" / "app").rglob("*.py"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    feature_version=(3, 10),
                )


if __name__ == "__main__":
    unittest.main()
