from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .command import require_binary, run
from .github import (
    PullRequest,
    checkout_base,
    checkout_pr,
    clone_repo,
    create_draft_pr,
    issue_json,
    post_pr_comment,
    pr_diff,
    pr_metadata,
)
from .ollama import OllamaClient
from .prompts import FIX_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, fix_task_prompt, review_user_prompt
from .rag import build_context_pack
from .validation import assert_validation_passed, render_validation, run_diff_check, run_validation


DEFAULT_WORK_ROOT = Path.home() / ".cache" / "local-ai-ci-controller"
PROTECTED_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)secrets?(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)\.github/workflows/"),
]


@dataclass(frozen=True)
class RuntimeConfig:
    repo: str
    model: str
    ollama_base_url: str
    work_root: Path
    test_cmd: str | None
    lint_cmd: str | None
    validation_timeout: int
    max_context_chars: int
    max_context_files: int
    max_diff_chars: int
    dry_run: bool

    @property
    def validation_commands(self) -> list[str]:
        return [cmd for cmd in [self.lint_cmd, self.test_cmd] if cmd]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "review-pr":
            review_pr(args)
        elif args.command == "fix-pr":
            fix_pr(args)
        elif args.command == "issue-pr":
            issue_pr(args)
        else:
            parser.error("No command selected")
    except Exception as exc:
        print(f"ai-ci-controller: {exc}", flush=True)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-ci-controller",
        description="Self-hosted Ollama controller for GitHub PR review and draft fix PRs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_common(
        subparsers.add_parser("review-pr", help="Review a GitHub pull request and post a PR comment.")
    ).add_argument("--pr", type=int, required=True, help="Pull request number to review.")

    fix_parser = add_common(
        subparsers.add_parser("fix-pr", help="Create a draft PR with fixes for an existing PR.")
    )
    fix_parser.add_argument("--pr", type=int, required=True, help="Pull request number to fix.")
    fix_parser.add_argument(
        "--base-mode",
        choices=["auto", "target-base", "pr-head"],
        default=os.environ.get("AI_CI_FIX_BASE_MODE", "auto"),
        help=(
            "Base for the generated fix PR. auto uses pr-head for same-repo PRs and "
            "target-base for fork PRs."
        ),
    )

    issue_parser = add_common(
        subparsers.add_parser("issue-pr", help="Create a draft PR that implements a GitHub issue.")
    )
    issue_parser.add_argument("--issue", type=int, required=True, help="Issue number to implement.")

    return parser


def add_common(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/REPO.")
    parser.add_argument("--model", default=os.environ.get("MODEL"), help="Ollama model name.")
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434",
        help="Ollama base URL.",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("WORK_ROOT", DEFAULT_WORK_ROOT)),
        help="Directory for disposable clones and artifacts.",
    )
    parser.add_argument("--test-cmd", default=os.environ.get("TEST_CMD"), help="Final test command.")
    parser.add_argument("--lint-cmd", default=os.environ.get("LINT_CMD"), help="Final lint command.")
    parser.add_argument(
        "--validation-timeout",
        type=int,
        default=int(os.environ.get("VALIDATION_TIMEOUT", "1200")),
        help="Timeout in seconds for each validation command.",
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=int(os.environ.get("MAX_CONTEXT_CHARS", "70000")),
        help="Maximum retrieved repository context characters.",
    )
    parser.add_argument(
        "--max-context-files",
        type=int,
        default=int(os.environ.get("MAX_CONTEXT_FILES", "24")),
        help="Maximum files in retrieved context pack.",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=int(os.environ.get("MAX_DIFF_CHARS", "120000")),
        help="Maximum diff characters sent to the model prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "0") == "1",
        help="Do not post comments, push branches, or open PRs.",
    )
    return parser


def review_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh"])
    pr = pr_metadata(config.repo, args.pr)
    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    diff_text = pr_diff(config.repo, args.pr)
    prompt_diff = limit_text(diff_text, config.max_diff_chars)
    validation_results = run_validation(repo_dir, config.validation_commands, timeout=config.validation_timeout)
    validation_output = render_validation(validation_results)
    context_pack = build_context_pack(
        repo_dir,
        query=f"{pr.title}\n{pr.body}",
        diff_text=diff_text,
        max_files=config.max_context_files,
        max_chars=config.max_context_chars,
    )
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")
    (artifacts_dir / "validation.txt").write_text(validation_output, encoding="utf-8")

    client = OllamaClient(config.ollama_base_url, config.model)
    content = client.chat(
        [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": review_user_prompt(
                    repo=config.repo,
                    pr_number=args.pr,
                    title=pr.title,
                    body=pr.body,
                    diff_text=prompt_diff,
                    context_pack=context_pack,
                    validation_output=validation_output,
                ),
            },
        ],
        json_format=True,
    )
    review = parse_review_json(content)
    safe_review = validate_review_findings(repo_dir, review)
    body = render_review_comment(pr, safe_review, validation_results)
    body_file = artifacts_dir / "review-comment.md"
    body_file.write_text(body, encoding="utf-8")

    if config.dry_run:
        print(body)
    else:
        post_pr_comment(config.repo, args.pr, body_file)
        print(f"Posted AI review comment on {config.repo}#{args.pr}")


def fix_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])
    pr = pr_metadata(config.repo, args.pr)
    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    diff_text = pr_diff(config.repo, args.pr)
    prompt_diff = limit_text(diff_text, config.max_diff_chars)
    pre_validation = run_validation(repo_dir, config.validation_commands, timeout=config.validation_timeout)
    context_pack = build_context_pack(
        repo_dir,
        query=f"{pr.title}\n{pr.body}",
        diff_text=diff_text,
        max_files=config.max_context_files,
        max_chars=config.max_context_chars,
    )
    review_text = existing_review_context(config.repo, args.pr)
    task = fix_task_prompt(
        repo=config.repo,
        pr_number=args.pr,
        issue_number=None,
        title=pr.title,
        body=pr.body,
        diff_text=prompt_diff,
        context_pack=context_pack,
        review_text=review_text,
        validation_output=render_validation(pre_validation),
    )
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    task_file = artifacts_dir / "fix-task.md"
    task_file.write_text(task, encoding="utf-8")
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

    run_aider(config, repo_dir, task_file)
    enforce_protected_paths(repo_dir)
    final_results = [run_diff_check(repo_dir)]
    final_results.extend(run_validation(repo_dir, config.validation_commands, timeout=config.validation_timeout))
    (artifacts_dir / "final-validation.txt").write_text(render_validation(final_results), encoding="utf-8")
    assert_validation_passed(final_results)
    ensure_changes(repo_dir)

    stamp = timestamp()
    branch_name = f"ai/fix-pr-{args.pr}-{stamp}"
    commit_and_maybe_publish(
        config=config,
        repo_dir=repo_dir,
        branch_name=branch_name,
        commit_message=f"fix: address AI review for PR #{args.pr}",
        pr_title=f"fix: follow-up for PR #{args.pr}",
        pr_body=render_fix_pr_body(pr, render_validation(final_results)),
        base=fix_base_for(pr, args.base_mode),
    )


def issue_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])
    issue = issue_json(config.repo, args.issue)
    stamp = timestamp()
    run_dir = config.work_root / f"{config.repo.replace('/', '-')}-issue-{args.issue}-{stamp}"
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_repo(config.repo, repo_dir)
    base = default_branch(config.repo)
    branch_name = f"ai/issue-{args.issue}-{stamp}"
    checkout_base(repo_dir, base, branch_name)
    context_pack = build_context_pack(
        repo_dir,
        query=f"{issue.get('title', '')}\n{issue.get('body', '')}",
        diff_text="",
        max_files=config.max_context_files,
        max_chars=config.max_context_chars,
    )
    task = fix_task_prompt(
        repo=config.repo,
        pr_number=None,
        issue_number=args.issue,
        title=issue.get("title") or "",
        body=issue.get("body") or "",
        diff_text="",
        context_pack=context_pack,
        review_text="",
        validation_output="",
    )
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    task_file = artifacts_dir / "issue-task.md"
    task_file.write_text(task, encoding="utf-8")
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

    run_aider(config, repo_dir, task_file)
    enforce_protected_paths(repo_dir)
    final_results = [run_diff_check(repo_dir)]
    final_results.extend(run_validation(repo_dir, config.validation_commands, timeout=config.validation_timeout))
    (artifacts_dir / "final-validation.txt").write_text(render_validation(final_results), encoding="utf-8")
    assert_validation_passed(final_results)
    ensure_changes(repo_dir)

    commit_and_maybe_publish(
        config=config,
        repo_dir=repo_dir,
        branch_name=branch_name,
        commit_message=f"fix: resolve issue #{args.issue}",
        pr_title=issue.get("title") or f"Resolve issue #{args.issue}",
        pr_body=(
            f"Closes #{args.issue}\n\n"
            "This draft PR was generated by the local AI CI controller using a locally hosted model.\n\n"
            "Human review is required before merge.\n\n"
            f"## Validation\n\n```text\n{render_validation(final_results) or '(no validation commands configured)'}\n```"
        ),
        base=base,
    )


def config_from_args(args: argparse.Namespace) -> RuntimeConfig:
    if not args.repo:
        raise RuntimeError("Set --repo or GITHUB_REPOSITORY to OWNER/REPO.")
    if not args.model:
        raise RuntimeError("Set --model or MODEL to the local Ollama model name.")
    return RuntimeConfig(
        repo=args.repo,
        model=args.model,
        ollama_base_url=args.ollama_base_url,
        work_root=args.work_root,
        test_cmd=args.test_cmd,
        lint_cmd=args.lint_cmd,
        validation_timeout=args.validation_timeout,
        max_context_chars=args.max_context_chars,
        max_context_files=args.max_context_files,
        max_diff_chars=args.max_diff_chars,
        dry_run=args.dry_run,
    )


def require_tools(names: list[str]) -> None:
    for name in names:
        require_binary(name)


def prepare_pr_checkout(config: RuntimeConfig, pr_number: int) -> tuple[Path, Path]:
    stamp = timestamp()
    run_dir = config.work_root / f"{config.repo.replace('/', '-')}-pr-{pr_number}-{stamp}"
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_repo(config.repo, repo_dir)
    checkout_pr(repo_dir, pr_number)
    return run_dir, repo_dir


def parse_review_json(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"Model did not return JSON:\n{content}")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise RuntimeError("Model review response was not a JSON object.")
    payload.setdefault("summary", "")
    payload.setdefault("risk_level", "medium")
    payload.setdefault("findings", [])
    payload.setdefault("tests_to_run", [])
    if not isinstance(payload["findings"], list):
        payload["findings"] = []
    return payload


def validate_review_findings(repo_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    safe_findings: list[dict[str, Any]] = []
    for finding in review.get("findings", []):
        if not isinstance(finding, dict):
            continue
        relative = str(finding.get("file") or "").strip()
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            continue
        file_path = repo_dir / relative
        if not file_path.exists() or not file_path.is_file():
            continue
        line = finding.get("line")
        try:
            line_number = int(line)
        except (TypeError, ValueError):
            line_number = 1
        total_lines = max(1, len(file_path.read_text(encoding="utf-8", errors="ignore").splitlines()))
        finding["line"] = min(max(1, line_number), total_lines)
        finding["severity"] = str(finding.get("severity") or "warning").lower()
        if finding["severity"] not in {"blocking", "warning", "nit"}:
            finding["severity"] = "warning"
        safe_findings.append(finding)
    sanitized = dict(review)
    sanitized["findings"] = safe_findings[:20]
    return sanitized


def render_review_comment(
    pr: PullRequest,
    review: dict[str, Any],
    validation_results: list,
) -> str:
    findings = review.get("findings") or []
    lines = [
        "## Local AI CI Review",
        "",
        review.get("summary") or "No summary returned.",
        "",
        f"Risk level: `{review.get('risk_level', 'medium')}`",
        "",
    ]
    if findings:
        lines.append("### Findings")
        lines.append("")
        for finding in findings:
            lines.extend(
                [
                    f"- `{finding.get('severity', 'warning')}` "
                    f"{finding.get('file', '?')}:{finding.get('line', 1)} - "
                    f"{finding.get('title', 'Finding')}",
                    f"  Evidence: {finding.get('evidence', '').strip() or 'Not provided.'}",
                    f"  Recommendation: {finding.get('recommendation', '').strip() or 'Not provided.'}",
                ]
            )
        lines.append("")
    else:
        lines.extend(["No concrete blocking findings were identified.", ""])

    if validation_results:
        lines.append("### Validation")
        lines.append("")
        for result in validation_results:
            status = "passed" if result.passed else "failed"
            lines.append(f"- `{result.command}`: {status}")
        lines.append("")

    tests_to_run = review.get("tests_to_run") or []
    if tests_to_run:
        lines.append("### Suggested Additional Validation")
        lines.append("")
        for command in tests_to_run[:10]:
            lines.append(f"- `{command}`")
        lines.append("")

    lines.extend(
        [
            "<sub>Generated by a self-hosted local AI controller. Human review is required.</sub>",
            f"<sub>Source PR: {pr.url}</sub>",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def existing_review_context(repo: str, pr_number: int) -> str:
    result = run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--comments",
            "--json",
            "comments,reviews",
        ],
        check=False,
    )
    if result.returncode != 0:
        return ""
    payload = json.loads(result.stdout)
    blocks: list[str] = []
    for comment in payload.get("comments") or []:
        author = (comment.get("author") or {}).get("login") or "unknown"
        body = comment.get("body") or ""
        if body:
            blocks.append(f"Comment by {author}:\n{body}")
    for review in payload.get("reviews") or []:
        author = (review.get("author") or {}).get("login") or "unknown"
        body = review.get("body") or ""
        state = review.get("state") or "COMMENTED"
        if body:
            blocks.append(f"Review by {author} ({state}):\n{body}")
    return "\n\n".join(blocks[-12:])


def run_aider(config: RuntimeConfig, repo_dir: Path, task_file: Path) -> None:
    args = [
        "aider",
        "--model",
        f"ollama_chat/{config.model}",
        "--message-file",
        str(task_file),
        "--no-auto-commits",
    ]
    if config.test_cmd:
        args.extend(["--test-cmd", config.test_cmd, "--auto-test"])
    if os.environ.get("UNATTENDED", "0") == "1":
        args.append("--yes")
    run(args, cwd=repo_dir, timeout=config.validation_timeout)


def enforce_protected_paths(repo_dir: Path) -> None:
    modified_paths = changed_paths(repo_dir)
    blocked = [
        path
        for path in modified_paths
        if any(pattern.search(path) for pattern in PROTECTED_PATH_PATTERNS)
    ]
    if blocked:
        rendered = "\n".join(f"- {path}" for path in blocked)
        raise RuntimeError(f"Refusing to publish protected path changes:\n{rendered}")


def changed_paths(repo_dir: Path) -> list[str]:
    paths: set[str] = set()
    commands = [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    for command in commands:
        result = run(command, cwd=repo_dir)
        for line in result.stdout.splitlines():
            if line:
                paths.add(line)
    return sorted(paths)


def ensure_changes(repo_dir: Path) -> None:
    result = run(["git", "status", "--porcelain"], cwd=repo_dir)
    if not result.stdout.strip():
        raise RuntimeError("The model produced no local changes.")


def commit_and_maybe_publish(
    *,
    config: RuntimeConfig,
    repo_dir: Path,
    branch_name: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
    base: str,
) -> None:
    run(["git", "switch", "-c", branch_name], cwd=repo_dir, check=False)
    run(["git", "add", "-A"], cwd=repo_dir)
    run(["git", "commit", "-m", commit_message], cwd=repo_dir)
    if config.dry_run:
        print("Dry run enabled. Created local commit but did not push or open a PR.")
        print(run(["git", "show", "--stat", "--oneline", "HEAD"], cwd=repo_dir).stdout)
        return
    run(["git", "push", "--set-upstream", "origin", branch_name], cwd=repo_dir)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(pr_body)
        body_path = Path(handle.name)
    try:
        pr_url = create_draft_pr(
            config.repo,
            base=base,
            head=branch_name,
            title=pr_title,
            body_file=body_path,
        )
    finally:
        body_path.unlink(missing_ok=True)
    print(f"Created draft pull request: {pr_url}")


def fix_base_for(pr: PullRequest, mode: str) -> str:
    if mode == "target-base":
        return pr.base_ref
    if mode == "pr-head":
        if not pr.same_repository:
            raise RuntimeError("--base-mode pr-head is only supported for same-repository PRs.")
        return pr.head_ref
    if pr.same_repository and pr.head_ref:
        return pr.head_ref
    return pr.base_ref


def render_fix_pr_body(pr: PullRequest, validation_output: str) -> str:
    return (
        f"Follow-up fixes for #{pr.number}.\n\n"
        "This draft PR was generated by the local AI CI controller using a locally hosted model.\n\n"
        "Human review is required before merge.\n\n"
        f"Source PR: {pr.url}\n\n"
        "## Validation\n\n"
        f"```text\n{validation_output or '(no validation commands configured)'}\n```"
    )


def default_branch(repo: str) -> str:
    payload = json.loads(
        run(
            [
                "gh",
                "repo",
                "view",
                repo,
                "--json",
                "defaultBranchRef",
            ]
        ).stdout
    )
    return (payload.get("defaultBranchRef") or {}).get("name") or "main"


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def limit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return f"{text[:head]}\n\n[...snipped by controller...]\n\n{text[-tail:]}"

