from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_ci_controller.validation import build_validation_commands


class ValidationCommandTests(unittest.TestCase):
    def test_build_validation_commands_includes_changed_python_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

            commands = build_validation_commands(
                root,
                configured_commands=["pytest -q"],
                diff_text="diff --git a/src/app.py b/src/app.py\n",
                auto_syntax=True,
            )

            self.assertTrue(commands[0].startswith("python -m py_compile "))
            self.assertIn("src/app.py", commands[0])
            self.assertEqual(commands[-1], "pytest -q")


if __name__ == "__main__":
    unittest.main()

