from __future__ import annotations

import unittest

from ai_ci_controller.model_router import ModelPolicy, classify_model


POLICY = ModelPolicy(
    default_model="fallback-coder",
    small_model="small-coder",
    medium_model="medium-coder",
    large_model="large-coder",
)


class ModelRouterTests(unittest.TestCase):
    def test_tiny_docs_change_uses_small_model(self) -> None:
        selection = classify_model(
            POLICY,
            title="Update README",
            body="Fix wording.",
            diff_text=diff_for("README.md", additions=4),
            mode="review",
        )
        self.assertEqual(selection.tier, "small")
        self.assertEqual(selection.model, "small-coder")

    def test_moderate_code_change_uses_medium_model(self) -> None:
        selection = classify_model(
            POLICY,
            title="Add parser option",
            body="Add a normal code path.",
            diff_text=diff_for("src/parser.py", additions=180, deletions=20),
            mode="review",
        )
        self.assertEqual(selection.tier, "medium")
        self.assertEqual(selection.model, "medium-coder")

    def test_security_change_uses_large_model(self) -> None:
        selection = classify_model(
            POLICY,
            title="Fix auth token handling",
            body="Security-sensitive token validation change.",
            diff_text=diff_for("src/auth/session.py", additions=30, deletions=10),
            mode="review",
        )
        self.assertEqual(selection.tier, "large")
        self.assertEqual(selection.model, "large-coder")

    def test_author_text_does_not_trigger_auth_risk(self) -> None:
        selection = classify_model(
            POLICY,
            title="Update author display",
            body="Adjust contributor author rendering.",
            diff_text=diff_for("src/profile.py", additions=12),
            mode="review",
        )
        self.assertEqual(selection.tier, "small")
        self.assertEqual(selection.model, "small-coder")

    def test_missing_tier_falls_back_to_default_model(self) -> None:
        policy = ModelPolicy(
            default_model="default-coder",
            small_model=None,
            medium_model=None,
            large_model=None,
        )
        selection = classify_model(
            policy,
            title="Update README",
            body="Fix wording.",
            diff_text=diff_for("README.md", additions=2),
            mode="review",
        )
        self.assertEqual(selection.tier, "small/fallback")
        self.assertEqual(selection.model, "default-coder")


def diff_for(path: str, *, additions: int, deletions: int = 0) -> str:
    lines = [
        f"diff --git a/{path} b/{path}",
        "index 0000000..1111111 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
    ]
    lines.extend(f"+added line {index}" for index in range(additions))
    lines.extend(f"-removed line {index}" for index in range(deletions))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    unittest.main()
