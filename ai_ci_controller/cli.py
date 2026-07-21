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
from .model_router import ModelPolicy, ModelSelection, classify_model
from .ollama import OllamaClient
from .prompts import REVIEW_SYSTEM_PROMPT, fix_task_prompt, review_user_prompt
from .rag import build_context_pack
from .validation import assert_validation_passed, render_validation, run_diff_check, run_validation
from .validation import build_validation_commands


DEFAULT_WORK_ROOT = Path.home() / ".cache" / "local-ai-ci-controller"
PROTECTED_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)secrets?(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)\.github/workflows/"),
]


class QuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    repo: str
    model: str | None
    model_small: str | None
    model_medium: str | None
    model_large: str | None
    ollama_base_url: str
    work_root: Path
    test_cmd: str | None
    lint_cmd: str | None
    validation_timeout: int
    max_context_chars: int
    max_context_files: int
    max_diff_chars: int
    daily_limit: int
    quota_workflow_prefix: str
    allow_forks: bool
    auto_syntax: bool
    extra_context: str
    dry_run: bool

    @property
    def configured_validation_commands(self) -> list[str]:
        return [cmd for cmd in [self.lint_cmd, self.test_cmd] if cmd]

    @property
    def model_policy(self) -> ModelPolicy:
        return ModelPolicy(
            default_model=self.model,
            small_model=self.model_small,
            medium_model=self.model_medium,
            large_model=self.model_large,
        )


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
    except QuotaExceeded as exc:
        print(f"ai-ci-controller: {exc}", flush=True)
        return 0
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
    parser.add_argument(
        "--model",
        default=os.environ.get("MODEL") or os.environ.get("LOCAL_AI_MODEL"),
        help="Fallback Ollama model name.",
    )
    parser.add_argument(
        "--model-small",
        default=os.environ.get("MODEL_SMALL") or os.environ.get("LOCAL_AI_MODEL_SMALL"),
        help="Ollama model for tiny and low-risk changes.",
    )
    parser.add_argument(
        "--model-medium",
        default=os.environ.get("MODEL_MEDIUM") or os.environ.get("LOCAL_AI_MODEL_MEDIUM"),
        help="Ollama model for normal code changes.",
    )
    parser.add_argument(
        "--model-large",
        default=os.environ.get("MODEL_LARGE") or os.environ.get("LOCAL_AI_MODEL_LARGE"),
        help="Ollama model for large or high-risk changes.",
    )
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
        "--daily-limit",
        type=int,
        default=int(os.environ.get("AI_CI_DAILY_LIMIT", os.environ.get("LOCAL_AI_DAILY_LIMIT", "0"))),
        help="Maximum Local AI workflow runs per UTC day. 0 disables the quota.",
    )
    parser.add_argument(
        "--quota-workflow-prefix",
        default=os.environ.get("AI_CI_QUOTA_WORKFLOW_PREFIX", "Local AI"),
        help="Workflow name prefix counted toward the daily quota.",
    )
    parser.add_argument(
        "--allow-forks",
        action="store_true",
        default=str_to_bool(os.environ.get("LOCAL_AI_ALLOW_FORKS", "false")),
        help="Allow checkout and validation of fork pull requests. Use only with isolation.",
    )
    parser.add_argument(
        "--no-auto-syntax",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_DISABLE_AUTO_SYNTAX", "false")),
        help="Disable built-in syntax checks for changed files.",
    )
    parser.add_argument(
        "--extra-context",
        default=os.environ.get("AI_CI_EXTRA_CONTEXT", ""),
        help="Extra PR discussion/comment context for the model prompt.",
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
    enforce_trust_policy(pr, config)
    enforce_daily_quota(config)
    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    diff_text = pr_diff(config.repo, args.pr)
    selection = select_model(config, title=pr.title, body=pr.body, diff_text=diff_text, mode="review")
    prompt_diff = limit_text(diff_text, diff_budget(config, selection))
    validation_commands = build_validation_commands(
        repo_dir,
        configured_commands=config.configured_validation_commands,
        diff_text=diff_text,
        auto_syntax=config.auto_syntax,
    )
    validation_results = run_validation(repo_dir, validation_commands, timeout=config.validation_timeout)
    validation_output = render_validation(validation_results)
    discussion_context = join_context(existing_review_context(config.repo, args.pr), config.extra_context)
    context_pack = build_context_pack(
        repo_dir,
        query=f"{pr.title}\n{pr.body}",
        diff_text=diff_text,
        max_files=context_file_budget(config, selection),
        max_chars=context_char_budget(config, selection),
    )
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_model_selection(artifacts_dir, selection)
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")
    (artifacts_dir / "validation.txt").write_text(validation_output, encoding="utf-8")

    client = OllamaClient(config.ollama_base_url, selection.model)
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
                    discussion_context=discussion_context,
                ),
            },
        ],
        json_format=True,
    )
    review = parse_review_json(content)
    safe_review = validate_review_findings(repo_dir, review)
    body = render_review_comment(pr, safe_review, validation_results, selection)
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
    enforce_trust_policy(pr, config)
    enforce_daily_quota(config)
    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    diff_text = pr_diff(config.repo, args.pr)
    selection = select_model(config, title=pr.title, body=pr.body, diff_text=diff_text, mode="fix")
    prompt_diff = limit_text(diff_text, diff_budget(config, selection))
    validation_commands = build_validation_commands(
        repo_dir,
        configured_commands=config.configured_validation_commands,
        diff_text=diff_text,
        auto_syntax=config.auto_syntax,
    )
    pre_validation = run_validation(repo_dir, validation_commands, timeout=config.validation_timeout)
    context_pack = build_context_pack(
        repo_dir,
        query=f"{pr.title}\n{pr.body}",
        diff_text=diff_text,
        max_files=context_file_budget(config, selection),
        max_chars=context_char_budget(config, selection),
    )
    review_text = join_context(existing_review_context(config.repo, args.pr), config.extra_context)
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
    write_model_selection(artifacts_dir, selection)
    task_file = artifacts_dir / "fix-task.md"
    task_file.write_text(task, encoding="utf-8")
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

    run_aider(config, repo_dir, task_file, selection.model)
    enforce_protected_paths(repo_dir)
    final_results = [run_diff_check(repo_dir)]
    final_results.extend(run_validation(repo_dir, validation_commands, timeout=config.validation_timeout))
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
        pr_body=render_fix_pr_body(pr, render_validation(final_results), selection),
        base=fix_base_for(pr, args.base_mode),
    )


def issue_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])
    enforce_daily_quota(config)
    issue = issue_json(config.repo, args.issue)
    stamp = timestamp()
    run_dir = config.work_root / f"{config.repo.replace('/', '-')}-issue-{args.issue}-{stamp}"
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_repo(config.repo, repo_dir)
    base = default_branch(config.repo)
    branch_name = f"ai/issue-{args.issue}-{stamp}"
    checkout_base(repo_dir, base, branch_name)
    selection = select_model(
        config,
        title=issue.get("title") or "",
        body=issue.get("body") or "",
        diff_text="",
        mode="issue",
    )
    context_pack = build_context_pack(
        repo_dir,
        query=f"{issue.get('title', '')}\n{issue.get('body', '')}",
        diff_text="",
        max_files=context_file_budget(config, selection),
        max_chars=context_char_budget(config, selection),
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
    write_model_selection(artifacts_dir, selection)
    task_file = artifacts_dir / "issue-task.md"
    task_file.write_text(task, encoding="utf-8")
    (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

    run_aider(config, repo_dir, task_file, selection.model)
    enforce_protected_paths(repo_dir)
    validation_commands = build_validation_commands(
        repo_dir,
        configured_commands=config.configured_validation_commands,
        diff_text=run(["git", "diff", "--patch"], cwd=repo_dir).stdout,
        auto_syntax=config.auto_syntax,
    )
    final_results = [run_diff_check(repo_dir)]
    final_results.extend(run_validation(repo_dir, validation_commands, timeout=config.validation_timeout))
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
            f"Model selection: `{selection.summary()}`\n\n"
            "Human review is required before merge.\n\n"
            f"## Validation\n\n```text\n{render_validation(final_results) or '(no validation commands configured)'}\n```"
        ),
        base=base,
    )


def config_from_args(args: argparse.Namespace) -> RuntimeConfig:
    if not args.repo:
        raise RuntimeError("Set --repo or GITHUB_REPOSITORY to OWNER/REPO.")
    if not any([args.model, args.model_small, args.model_medium, args.model_large]):
        raise RuntimeError(
            "Set --model/MODEL or at least one tier model: MODEL_SMALL, MODEL_MEDIUM, MODEL_LARGE."
        )
    return RuntimeConfig(
        repo=args.repo,
        model=args.model,
        model_small=args.model_small,
        model_medium=args.model_medium,
        model_large=args.model_large,
        ollama_base_url=args.ollama_base_url,
        work_root=args.work_root,
        test_cmd=args.test_cmd,
        lint_cmd=args.lint_cmd,
        validation_timeout=args.validation_timeout,
        max_context_chars=args.max_context_chars,
        max_context_files=args.max_context_files,
        max_diff_chars=args.max_diff_chars,
        daily_limit=args.daily_limit,
        quota_workflow_prefix=args.quota_workflow_prefix,
        allow_forks=args.allow_forks,
        auto_syntax=not args.no_auto_syntax,
        extra_context=args.extra_context,
        dry_run=args.dry_run,
    )


def require_tools(names: list[str]) -> None:
    for name in names:
        require_binary(name)


def enforce_trust_policy(pr: PullRequest, config: RuntimeConfig) -> None:
    if pr.same_repository or config.allow_forks:
        return
    raise RuntimeError(
        f"Refusing to check out fork PR #{pr.number} from {pr.head_repo_name_with_owner}. "
        "Set LOCAL_AI_ALLOW_FORKS=true only after isolating the runner per job."
    )


def enforce_daily_quota(config: RuntimeConfig) -> None:
    if config.daily_limit <= 0:
        return
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    result = run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            config.repo,
            "--created",
            f">={start}",
            "--limit",
            "300",
            "--json",
            "databaseId,workflowName,createdAt,status",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect today's workflow quota:\n{result.combined_output}")
    runs = json.loads(result.stdout or "[]")
    used = sum(
        1
        for item in runs
        if str(item.get("workflowName") or "").startswith(config.quota_workflow_prefix)
    )
    if used > config.daily_limit:
        raise QuotaExceeded(
            f"daily quota reached for `{config.quota_workflow_prefix}` workflows: "
            f"{used}/{config.daily_limit} runs since {start}. Skipping this job."
        )
    print(
        f"Daily Local AI quota: {used}/{config.daily_limit} "
        f"runs since {start} for workflow prefix `{config.quota_workflow_prefix}`."
    )


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
    model_selection: ModelSelection,
) -> str:
    findings = review.get("findings") or []
    lines = [
        "## Local AI CI Review",
        "",
        review.get("summary") or "No summary returned.",
        "",
        f"Risk level: `{review.get('risk_level', 'medium')}`",
        f"Model: `{model_selection.summary()}`",
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
    return limit_text("\n\n".join(blocks[-12:]), 40_000)


def run_aider(config: RuntimeConfig, repo_dir: Path, task_file: Path, model: str) -> None:
    args = [
        "aider",
        "--model",
        f"ollama_chat/{model}",
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


def render_fix_pr_body(
    pr: PullRequest,
    validation_output: str,
    model_selection: ModelSelection,
) -> str:
    return (
        f"Follow-up fixes for #{pr.number}.\n\n"
        "This draft PR was generated by the local AI CI controller using a locally hosted model.\n\n"
        f"Model selection: `{model_selection.summary()}`\n\n"
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


def select_model(
    config: RuntimeConfig,
    *,
    title: str,
    body: str,
    diff_text: str,
    mode: str,
) -> ModelSelection:
    selection = classify_model(
        config.model_policy,
        title=title,
        body=body,
        diff_text=diff_text,
        mode=mode,
    )
    print(f"Selected model: {selection.summary()}")
    return selection


def write_model_selection(artifacts_dir: Path, selection: ModelSelection) -> None:
    (artifacts_dir / "model-selection.json").write_text(selection.to_json(), encoding="utf-8")


def context_char_budget(config: RuntimeConfig, selection: ModelSelection) -> int:
    tier = base_tier(selection)
    if tier == "small":
        return min(config.max_context_chars, 30_000)
    if tier == "medium":
        return min(config.max_context_chars, 70_000)
    return config.max_context_chars


def context_file_budget(config: RuntimeConfig, selection: ModelSelection) -> int:
    tier = base_tier(selection)
    if tier == "small":
        return min(config.max_context_files, 10)
    if tier == "medium":
        return min(config.max_context_files, 20)
    return config.max_context_files


def diff_budget(config: RuntimeConfig, selection: ModelSelection) -> int:
    tier = base_tier(selection)
    if tier == "small":
        return min(config.max_diff_chars, 40_000)
    if tier == "medium":
        return min(config.max_diff_chars, 90_000)
    return config.max_diff_chars


def base_tier(selection: ModelSelection) -> str:
    return selection.tier.split("/", 1)[0]


def limit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return f"{text[:head]}\n\n[...snipped by controller...]\n\n{text[-tail:]}"


def join_context(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def str_to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
