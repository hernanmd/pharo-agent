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


EXPLORE_SYSTEM_PROMPT = """You are investigating a repository before any code is written.

You have tools. Use them instead of guessing. In particular:
- Never assume a method, function, or selector exists. Look it up first.
- When a live Pharo image is available, pharo_eval is ground truth. Run small
  expressions to confirm behaviour before you rely on it.
- Read the actual files you intend to change with read_file. The repository map
  lists names and signatures, not bodies.
- Prefer three cheap lookups over one confident guess.

Work through the task, then stop calling tools and write a plain-text briefing of
what you established: the facts you verified, the specific files and definitions
involved, and anything you tried that did not work. Do not write the final patch
or the final review here. A later step will do that using your briefing."""


RESPOND_SYSTEM_PROMPT = """You are the author of a pull request, responding to a reviewer.

For each review thread, decide honestly which of these is true:

- "agree": the reviewer is right and the code should change. Say what you will
  change, concretely. Do not restate the comment back at them.
- "disagree": you have evidence the comment is mistaken. Give the evidence. If a
  Pharo expression was evaluated in the live image, quote the exact expression and
  the exact result. "I checked and it works" is not evidence; the expression and
  its output are.
- "needs-clarification": the comment is ambiguous enough that guessing would waste
  everyone's time. Ask one specific question.

Rules:
- Be brief. A reviewer reads many of these. Two or three sentences per thread.
- Never agree to something you could not verify just to be agreeable. A confidently
  wrong change is worse than an honest disagreement.
- Never claim you made a change. The controller applies changes and reports what
  actually landed.
- If a thread is marked outdated, check whether the code already changed before
  responding.

Return strict JSON with this shape:
{
  "summary": "one short paragraph covering the round as a whole",
  "review_reply": "reply to the overall submitted review body, or empty string",
  "responses": [
    {
      "thread_id": "the exact thread id given to you",
      "verdict": "agree|disagree|needs-clarification",
      "reply": "what to post on that thread",
      "evidence": "the expression and result, file and line, or empty string",
      "change": "for agree: the specific edit to make. Otherwise empty string."
    }
  ]
}
Include one response per thread you were given, and no others."""


def respond_user_prompt(
    *,
    repo: str,
    pr_number: int,
    title: str,
    body: str,
    conversation: str,
    diff_text: str,
    context_pack: str,
    skills_text: str = "",
    repo_map: str = "",
    investigation: str = "",
) -> str:
    return f"""Repository: {repo}
Pull request: #{pr_number}
Title: {title}

This pull request was opened by you. A reviewer has now responded and you are
replying to their feedback.

PR body:
{body or "(No PR body provided.)"}

{skills_text}

{investigation}

# Feedback awaiting your response

{conversation}

Current diff of this pull request:
```diff
{diff_text}
```

{repo_map}

{context_pack}
"""


def respond_fix_prompt(
    *,
    repo: str,
    pr_number: int,
    changes: list[str],
    conversation: str,
    context_pack: str,
    skills_text: str = "",
    investigation: str = "",
) -> str:
    numbered = "\n".join(f"{index}. {change}" for index, change in enumerate(changes, start=1))
    return f"""{FIX_SYSTEM_PROMPT}

You are amending pull request #{pr_number} in {repo} in response to review feedback.

Apply exactly these changes, which you already agreed to, and nothing else:

{numbered}

Do not address feedback you disagreed with. Do not refactor anything the reviewer
did not raise. Keep the change minimal and reviewable, because the reviewer will
read this as a follow-up commit on an open pull request.

{skills_text}

{investigation}

# The review feedback these changes come from

{conversation}

{context_pack}
"""


def explore_user_prompt(
    *,
    goal: str,
    repo: str,
    title: str,
    body: str,
    diff_text: str,
    repo_map: str,
    skills_text: str,
) -> str:
    diff_block = f"Diff under consideration:\n```diff\n{diff_text}\n```" if diff_text else ""
    return f"""Repository: {repo}

Your investigation goal:
{goal}

Title:
{title}

Description:
{body or "(No description provided.)"}

{skills_text}

{repo_map}

{diff_block}
"""


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
    skills_text: str = "",
    repo_map: str = "",
    investigation: str = "",
) -> str:
    return f"""Repository: {repo}
Pull request: #{pr_number}
Title: {title}

PR body:
{body or "(No PR body provided.)"}

{skills_text}

Validation output before review:
```text
{validation_output or "(No validation command output was provided.)"}
```

PR discussion, reviews, and recent trigger comment:
```text
{discussion_context or "(No PR discussion context was provided.)"}
```

{investigation}

Diff:
```diff
{diff_text}
```

{repo_map}

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
    skills_text: str = "",
    repo_map: str = "",
    investigation: str = "",
) -> str:
    source = f"PR #{pr_number}" if pr_number is not None else f"issue #{issue_number}"
    return f"""{FIX_SYSTEM_PROMPT}

Implement fixes for {source} in {repo}.

Title:
{title}

Description:
{body or "(No description provided.)"}

{skills_text}

{investigation}

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

{repo_map}

{context_pack}
"""


def render_investigation(briefing: str, transcript: str, *, tools_used: list[str]) -> str:
    if not briefing.strip() and not transcript.strip():
        return ""
    tools = ", ".join(tools_used) if tools_used else "none"
    return f"""## Verified Investigation

An agent explored this repository before this step, using these tools: {tools}.
The facts below were checked against the real repository and, where available, a
live Pharo image. Prefer them over your own assumptions.

{briefing.strip() or "(The agent produced no written briefing.)"}

<details>
<summary>Tool call transcript</summary>

```text
{transcript}
```

</details>
"""
