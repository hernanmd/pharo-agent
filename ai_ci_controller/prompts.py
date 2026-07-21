from __future__ import annotations


REVIEW_SYSTEM_PROMPT = """You are a senior software reviewer running inside CI.
Review only the submitted pull request. Focus on correctness bugs, security issues,
test gaps, regressions, and maintainability problems that can block merge.
Do not make style-only comments. Do not request broad rewrites.
Return strict JSON with this shape:
{
  "summary": "one paragraph",
  "risk_level": "low|medium|high",
  "findings": [
    {
      "severity": "blocking|warning|nit",
      "file": "relative/path",
      "line": 123,
      "title": "short title",
      "evidence": "what in the diff or context proves this",
      "recommendation": "specific fix"
    }
  ],
  "tests_to_run": ["command"]
}
If there are no concrete issues, return an empty findings array."""


FIX_SYSTEM_PROMPT = """You are a coding agent preparing local edits for a draft pull request.
Make the smallest correct change that addresses the task. Preserve the existing architecture.
Update tests when behavior changes. Never edit secrets, credentials, generated lockfiles unless
the task directly requires them, or .github/workflows.
The controller, not you, will run validation, commit, push, and open the draft PR."""


def review_user_prompt(
    *,
    repo: str,
    pr_number: int,
    title: str,
    body: str,
    diff_text: str,
    context_pack: str,
    validation_output: str,
    discussion_context: str,
) -> str:
    return f"""Repository: {repo}
Pull request: #{pr_number}
Title: {title}

PR body:
{body or "(No PR body provided.)"}

Validation output before review:
```text
{validation_output or "(No validation command output was provided.)"}
```

PR discussion, reviews, and recent trigger comment:
```text
{discussion_context or "(No PR discussion context was provided.)"}
```

Diff:
```diff
{diff_text}
```

{context_pack}
"""


def fix_task_prompt(
    *,
    repo: str,
    pr_number: int | None,
    issue_number: int | None,
    title: str,
    body: str,
    diff_text: str,
    context_pack: str,
    review_text: str,
    validation_output: str,
) -> str:
    source = f"PR #{pr_number}" if pr_number is not None else f"issue #{issue_number}"
    return f"""{FIX_SYSTEM_PROMPT}

Implement fixes for {source} in {repo}.

Title:
{title}

Description:
{body or "(No description provided.)"}

Prior review / requested fixes:
{review_text or "(No prior review text supplied.)"}

Current validation output:
```text
{validation_output or "(No validation command output was provided.)"}
```

Relevant diff:
```diff
{diff_text or "(No diff supplied.)"}
```

{context_pack}
"""
