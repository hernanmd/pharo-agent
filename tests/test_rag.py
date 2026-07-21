from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_ci_controller.rag import build_context_pack, extract_changed_files


class RagTests(unittest.TestCase):
    def test_extract_changed_files_from_patch(self) -> None:
        diff = """diff --git a/src/app.py b/src/app.py
index 0000000..1111111 100644
--- a/src/app.py
+++ b/src/app.py
diff --git a/tests/test_app.py b/tests/test_app.py
"""
        self.assertEqual(extract_changed_files(diff), ["src/app.py", "tests/test_app.py"])

    def test_context_pack_prioritizes_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "README.md").write_text("Project docs\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("def important_fix():\n    return 1\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_important_fix():\n    pass\n", encoding="utf-8")
            context = build_context_pack(
                root,
                query="important fix",
                diff_text="diff --git a/src/app.py b/src/app.py\n",
                max_files=3,
                max_chars=10_000,
            )
            self.assertIn("## src/app.py", context)
            self.assertIn("## README.md", context)


if __name__ == "__main__":
    unittest.main()

