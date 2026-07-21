from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_ci_controller.cli import enforce_protected_paths, parse_review_json, validate_review_findings
from ai_ci_controller.command import run


class ReviewSafetyTests(unittest.TestCase):
    def test_parse_review_json_extracts_object(self) -> None:
        parsed = parse_review_json(
            'Here is the result:\n{"summary":"ok","risk_level":"low","findings":[]}'
        )
        self.assertEqual(parsed["summary"], "ok")
        self.assertEqual(parsed["findings"], [])

    def test_validate_review_findings_drops_unknown_files_and_clamps_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("one\ntwo\n", encoding="utf-8")
            review = {
                "findings": [
                    {"file": "app.py", "line": 100, "severity": "critical"},
                    {"file": "../secret", "line": 1, "severity": "blocking"},
                    {"file": "missing.py", "line": 1, "severity": "warning"},
                ]
            }
            sanitized = validate_review_findings(root, review)
            self.assertEqual(len(sanitized["findings"]), 1)
            self.assertEqual(sanitized["findings"][0]["line"], 2)
            self.assertEqual(sanitized["findings"][0]["severity"], "warning")

    def test_protected_path_guard_catches_new_workflow_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(["git", "init"], cwd=root)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: bad\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Refusing to publish protected path"):
                enforce_protected_paths(root)


if __name__ == "__main__":
    unittest.main()
