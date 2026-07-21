from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent import build_tools, pharo_tools, run_agent
from .bench import load_tasks, render_scorecard, run_bench
from .command import require_binary, run
from .conversation import (
    AI_MARKER,
    ReviewThread,
    fetch_conversation,
    post_conversation_comment,
    reply_to_thread,
)
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
from .pharo import PharoConfig, PharoImage, PharoMcpClient, PharoUnavailable
from .prompts import (
    EXPLORE_SYSTEM_PROMPT,
    RESPOND_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    explore_user_prompt,
    fix_task_prompt,
    render_investigation,
    respond_fix_prompt,
    respond_user_prompt,
    review_user_prompt,
)
from .rag import build_context_pack, extract_changed_files
from .repomap import build_repo_map
from .selfcheck import render_checks, run_selfcheck
from .skills import SkillSelection, load_skills, render_skills, select_skills
from .validation import (
    assert_validation_passed,
    build_validation_commands,
    dedupe,
    render_validation,
    run_diff_check,
    run_tonel_check,
    run_validation,
)

DEFAULT_WORK_ROOT = Path.home() / ".cache" / "pharo-agent-ci-controller"
AGENT_ARTIFACT_PATTERNS = [".aider*", ".ai-ci-*"]
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
    max_repo_map_chars: int
    skills_dir: str
    agent_enabled: bool
    agent_max_iterations: int
    daily_limit: int
    quota_workflow_prefix: str
    allow_forks: bool
    auto_syntax: bool
    extra_context: str
    keep_work_dir: bool
    work_retention_days: int
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


@dataclass(frozen=True)
class RunContext:
    skills: SkillSelection
    skills_text: str
    repo_map: str
    investigation: str
    pharo_used: bool

    @property
    def validation_commands(self) -> list[str]:
        return self.skills.validate_commands


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
        elif args.command == "respond-review":
            respond_review(args)
        elif args.command == "sweep-issues":
            return sweep_issues(args)
        elif args.command == "selfcheck":
            return selfcheck(args)
        elif args.command == "bench":
            return bench(args)
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

    respond_parser = add_common(
        subparsers.add_parser(
            "respond-review",
            help="Respond to reviewer feedback on a pull request the AI opened.",
        )
    )
    respond_parser.add_argument("--pr", type=int, required=True, help="Pull request number.")
    respond_parser.add_argument(
        "--any-pr",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_RESPOND_ANY_PR", "false")),
        help="Also respond on human-authored PRs, not just ai/issue-* and ai/fix-pr-* branches.",
    )
    respond_parser.add_argument(
        "--no-amend",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_RESPOND_NO_AMEND", "false")),
        help="Reply in words only. Never push follow-up commits to the PR branch.",
    )

    sweep_parser = add_common(
        subparsers.add_parser(
            "sweep-issues",
            help="Take the most recent open issues and open one draft PR for each.",
        )
    )
    sweep_parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("AI_CI_ISSUE_LIMIT", "5")),
        help="How many recent issues to process. Default 5.",
    )
    sweep_parser.add_argument(
        "--label",
        action="append",
        default=env_list("AI_CI_ISSUE_LABELS"),
        help="Only consider issues carrying this label. Repeatable.",
    )
    sweep_parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_SKIP_EXISTING", "true")),
        help="Skip issues that already have an open ai/issue-N branch or PR.",
    )
    sweep_parser.add_argument(
        "--stop-on-error",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_STOP_ON_ERROR", "false")),
        help="Abort the sweep on the first failing issue instead of continuing.",
    )

    check_parser = add_common(
        subparsers.add_parser(
            "selfcheck",
            help="Verify this runner can actually do the work: Ollama, models, Pharo, aider, gh.",
        )
    )
    check_parser.add_argument(
        "--require-pharo",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_REQUIRE_PHARO", "false")),
        help="Treat a missing or unbootable Pharo image as a failure rather than a warning.",
    )
    check_parser.add_argument(
        "--require-aider",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_REQUIRE_AIDER", "true")),
        help="Treat a missing aider as a failure. On by default.",
    )

    bench_parser = add_common(
        subparsers.add_parser(
            "bench",
            help="Score whether the configured model can actually write and reason about Pharo.",
        )
    )
    bench_parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=Path(os.environ.get("AI_CI_BENCH_TASKS", "benchmarks/tasks")),
        help="Directory of benchmark task markdown files.",
    )
    bench_parser.add_argument(
        "--no-tools",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_BENCH_NO_TOOLS", "false")),
        help="Run the model raw, with no image access. Use to measure what grounding is worth.",
    )
    bench_parser.add_argument(
        "--bench-model",
        default=os.environ.get("AI_CI_BENCH_MODEL"),
        help="Model to benchmark. Defaults to the medium tier, then the fallback model.",
    )
    bench_parser.add_argument(
        "--bench-timeout",
        type=int,
        default=int(os.environ.get("AI_CI_BENCH_TIMEOUT", "120")),
        help="Per-task model timeout in seconds. A rambling model should not hold the whole run.",
    )
    bench_parser.add_argument(
        "--report",
        type=Path,
        default=Path(os.environ.get("AI_CI_BENCH_REPORT", "")) if os.environ.get("AI_CI_BENCH_REPORT") else None,
        help="Write the scorecard markdown to this path as well as stdout.",
    )

    return parser


def add_common(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/REPO.")
    parser.add_argument(
        "--model",
        default=os.environ.get("MODEL") or os.environ.get("PHARO_AGENT_MODEL"),
        help="Fallback Ollama model name.",
    )
    parser.add_argument(
        "--model-small",
        default=os.environ.get("MODEL_SMALL") or os.environ.get("PHARO_AGENT_MODEL_SMALL"),
        help="Ollama model for tiny and low-risk changes.",
    )
    parser.add_argument(
        "--model-medium",
        default=os.environ.get("MODEL_MEDIUM") or os.environ.get("PHARO_AGENT_MODEL_MEDIUM"),
        help="Ollama model for normal code changes.",
    )
    parser.add_argument(
        "--model-large",
        default=os.environ.get("MODEL_LARGE") or os.environ.get("PHARO_AGENT_MODEL_LARGE"),
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
        "--max-repo-map-chars",
        type=int,
        default=int(os.environ.get("MAX_REPO_MAP_CHARS", "40000")),
        help="Maximum characters for the whole-repository structure map. 0 disables it.",
    )
    parser.add_argument(
        "--skills-dir",
        default=os.environ.get("AI_CI_SKILLS_DIR", ".ai/skills"),
        help="Directory inside the target repository holding skill markdown files.",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_DISABLE_AGENT", "false")),
        help="Disable the tool-using investigation pass before review or fix.",
    )
    parser.add_argument(
        "--agent-max-iterations",
        type=int,
        default=int(os.environ.get("AI_CI_AGENT_MAX_ITERATIONS", "12")),
        help="Maximum tool-calling rounds during investigation.",
    )
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=int(os.environ.get("AI_CI_DAILY_LIMIT", os.environ.get("PHARO_AGENT_DAILY_LIMIT", "0"))),
        help="Maximum Pharo Agent workflow runs per UTC day. 0 disables the quota.",
    )
    parser.add_argument(
        "--quota-workflow-prefix",
        default=os.environ.get("AI_CI_QUOTA_WORKFLOW_PREFIX", "Pharo Agent"),
        help="Workflow name prefix counted toward the daily quota.",
    )
    parser.add_argument(
        "--allow-forks",
        action="store_true",
        default=str_to_bool(os.environ.get("PHARO_AGENT_ALLOW_FORKS", "false")),
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
        "--keep-work-dir",
        action="store_true",
        default=str_to_bool(os.environ.get("AI_CI_KEEP_WORK_DIR", "false")),
        help="Keep the disposable clone after the run. Artifacts are always kept.",
    )
    parser.add_argument(
        "--work-retention-days",
        type=int,
        default=int(os.environ.get("AI_CI_WORK_RETENTION_DAYS", "7")),
        help="Delete run directories older than this many days. 0 disables pruning.",
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
    artifacts_dir = make_artifacts_dir(run_dir)

    try:
        diff_text = pr_diff(config.repo, args.pr)
        selection = select_model(config, title=pr.title, body=pr.body, diff_text=diff_text, mode="review")
        prompt_diff = limit_text(diff_text, diff_budget(config, selection))
        context = build_run_context(
            config,
            repo_dir,
            artifacts_dir=artifacts_dir,
            model=selection.model,
            goal=(
                "Understand this pull request well enough to review it. Establish what the "
                "changed code actually does, whether the definitions it calls really exist, "
                "and whether the existing tests cover the change."
            ),
            title=pr.title,
            body=pr.body,
            diff_text=prompt_diff,
        )

        validation_commands = build_validation_commands(
            repo_dir,
            configured_commands=dedupe(context.validation_commands + config.configured_validation_commands),
            diff_text=diff_text,
            auto_syntax=config.auto_syntax,
        )
        validation_results = collect_validation(
            repo_dir,
            commands=validation_commands,
            diff_text=diff_text,
            timeout=config.validation_timeout,
        )
        validation_output = render_validation(validation_results)
        discussion_context = join_context(existing_review_context(config.repo, args.pr), config.extra_context)
        context_pack = build_context_pack(
            repo_dir,
            query=f"{pr.title}\n{pr.body}",
            diff_text=diff_text,
            max_files=context_file_budget(config, selection),
            max_chars=context_char_budget(config, selection),
        )

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
                        skills_text=context.skills_text,
                        repo_map=context.repo_map,
                        investigation=context.investigation,
                    ),
                },
            ],
            json_format=True,
        )
        review = parse_review_json(content)
        safe_review = validate_review_findings(repo_dir, review)
        body = render_review_comment(pr, safe_review, validation_results, selection, context)
        body_file = artifacts_dir / "review-comment.md"
        body_file.write_text(body, encoding="utf-8")

        if config.dry_run:
            print(body)
        else:
            post_pr_comment(config.repo, args.pr, body_file)
            print(f"Posted AI review comment on {config.repo}#{args.pr}")
    finally:
        finalize_run_dir(config, run_dir, repo_dir)


def fix_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])
    pr = pr_metadata(config.repo, args.pr)
    enforce_trust_policy(pr, config)
    enforce_daily_quota(config)
    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    artifacts_dir = make_artifacts_dir(run_dir)

    try:
        diff_text = pr_diff(config.repo, args.pr)
        selection = select_model(config, title=pr.title, body=pr.body, diff_text=diff_text, mode="fix")
        prompt_diff = limit_text(diff_text, diff_budget(config, selection))
        context = build_run_context(
            config,
            repo_dir,
            artifacts_dir=artifacts_dir,
            model=selection.model,
            goal=(
                "Work out exactly what needs to change to address the review feedback on this "
                "pull request. Confirm every definition you plan to call really exists."
            ),
            title=pr.title,
            body=pr.body,
            diff_text=prompt_diff,
        )

        validation_commands = build_validation_commands(
            repo_dir,
            configured_commands=dedupe(context.validation_commands + config.configured_validation_commands),
            diff_text=diff_text,
            auto_syntax=config.auto_syntax,
        )
        pre_validation = collect_validation(
            repo_dir,
            commands=validation_commands,
            diff_text=diff_text,
            timeout=config.validation_timeout,
        )
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
            skills_text=context.skills_text,
            repo_map=context.repo_map,
            investigation=context.investigation,
        )

        write_model_selection(artifacts_dir, selection)
        task_file = artifacts_dir / "fix-task.md"
        task_file.write_text(task, encoding="utf-8")
        (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

        run_aider(config, repo_dir, task_file, selection.model)
        enforce_protected_paths(repo_dir)
        final_results = [run_diff_check(repo_dir)]
        final_results.extend(
            collect_validation(
                repo_dir,
                commands=validation_commands,
                diff_text=working_diff(repo_dir),
                timeout=config.validation_timeout,
            )
        )
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
            pr_body=render_fix_pr_body(pr, render_validation(final_results), selection, context),
            base=fix_base_for(pr, args.base_mode),
        )
    finally:
        finalize_run_dir(config, run_dir, repo_dir)


def issue_pr(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])
    enforce_daily_quota(config)
    print(implement_issue(config, args.issue))


def selfcheck(args: argparse.Namespace) -> int:
    models = [
        model
        for model in [args.model, args.model_small, args.model_medium, args.model_large]
        if model
    ]
    work_dir = Path(tempfile.mkdtemp(prefix="pharo-agent-selfcheck-"))
    try:
        checks = run_selfcheck(
            ollama_base_url=args.ollama_base_url,
            models=models,
            work_dir=work_dir,
            repo_dir=Path.cwd(),
            require_pharo=args.require_pharo,
            require_aider=args.require_aider,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    report = render_checks(checks)
    print(report)
    write_step_summary(report)
    return 1 if any(check.blocking for check in checks) else 0


def bench(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.tasks_dir)
    if not tasks:
        print(f"No benchmark tasks found in {args.tasks_dir}.")
        return 1

    model = (
        args.bench_model
        or args.model_medium
        or args.model
        or args.model_large
        or args.model_small
    )
    if not model:
        raise RuntimeError("Set --bench-model, --model, or one of the tier models to benchmark.")

    print(f"Benchmarking `{model}` on {len(tasks)} task(s).")
    work_dir = Path(tempfile.mkdtemp(prefix="pharo-agent-bench-"))
    image: PharoImage | None = None
    pharo_client: PharoMcpClient | None = None
    tools = []

    try:
        if args.no_tools:
            print("Running ungrounded: no image, no tools.")
        else:
            image, pharo_client = start_bare_image(work_dir)
            if pharo_client is not None:
                tools = pharo_tools(pharo_client)

        report = run_bench(
            OllamaClient(args.ollama_base_url, model, timeout_seconds=args.bench_timeout),
            tasks,
            pharo=pharo_client,
            tools=tools,
        )
    finally:
        if image is not None:
            image.stop()
        shutil.rmtree(work_dir, ignore_errors=True)

    scorecard = render_scorecard(report)
    print(scorecard)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(scorecard, encoding="utf-8")
        print(f"Scorecard written to {args.report}")
    write_step_summary(scorecard)
    return 0


def start_bare_image(work_dir: Path) -> tuple[PharoImage | None, PharoMcpClient | None]:
    config = replace(PharoConfig.from_environment(), baseline=None, load_script="")
    if not config.enabled:
        print("Pharo is not configured, so selector tasks will be skipped.")
        return None, None

    try:
        image = PharoImage(config=config, repo_dir=work_dir, work_dir=work_dir / "image")
        image.start()
        client = image.client()
        client.initialize()
        print(f"Grounded against a bare Pharo image on {image.endpoint}")
        return image, client
    except PharoUnavailable as exc:
        print(f"Pharo image unavailable, selector tasks will be skipped: {exc}")
        return None, None


def write_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    except OSError as exc:
        print(f"Could not write the job summary: {exc}")


def respond_review(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    require_tools(["git", "gh"])
    pr = pr_metadata(config.repo, args.pr)
    enforce_trust_policy(pr, config)

    conversation = fetch_conversation(config.repo, args.pr)
    if not args.any_pr and not conversation.is_ai_branch:
        print(
            f"PR #{args.pr} is on branch '{conversation.head_ref}', which the AI did not open. "
            "Pass --any-pr to respond anyway."
        )
        return
    if not conversation.has_pending_work():
        print("Every review thread is either resolved or already answered. Nothing to do.")
        return

    pending = conversation.pending_threads()
    print(
        f"Responding to {len(pending)} thread(s) and "
        f"{len(conversation.pending_reviews())} submitted review(s)."
    )
    enforce_daily_quota(config)

    run_dir, repo_dir = prepare_pr_checkout(config, args.pr)
    artifacts_dir = make_artifacts_dir(run_dir)

    try:
        diff_text = pr_diff(config.repo, args.pr)
        conversation_text = conversation.render()
        (artifacts_dir / "conversation.md").write_text(conversation_text, encoding="utf-8")

        selection = select_model(
            config,
            title=pr.title,
            body=f"{pr.body}\n{conversation_text}",
            diff_text=diff_text,
            mode="respond",
        )
        prompt_diff = limit_text(diff_text, diff_budget(config, selection))
        context = build_run_context(
            config,
            repo_dir,
            artifacts_dir=artifacts_dir,
            model=selection.model,
            goal=(
                "A reviewer left the feedback below on your pull request. For each point, "
                "establish whether it is actually correct before you respond. Read the code "
                "they are pointing at. If a claim can be settled by evaluating an expression "
                "in the live image, evaluate it and keep the exact result as evidence.\n\n"
                f"{limit_text(conversation_text, 20_000)}"
            ),
            title=pr.title,
            body=pr.body,
            diff_text=prompt_diff,
        )
        context_pack = build_context_pack(
            repo_dir,
            query=f"{pr.title}\n{conversation_text}",
            diff_text=diff_text,
            max_files=context_file_budget(config, selection),
            max_chars=context_char_budget(config, selection),
        )
        write_model_selection(artifacts_dir, selection)

        client = OllamaClient(config.ollama_base_url, selection.model)
        content = client.chat(
            [
                {"role": "system", "content": RESPOND_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": respond_user_prompt(
                        repo=config.repo,
                        pr_number=args.pr,
                        title=pr.title,
                        body=pr.body,
                        conversation=conversation_text,
                        diff_text=prompt_diff,
                        context_pack=context_pack,
                        skills_text=context.skills_text,
                        repo_map=context.repo_map,
                        investigation=context.investigation,
                    ),
                },
            ],
            json_format=True,
        )
        plan = parse_response_plan(content, pending)
        (artifacts_dir / "response-plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        amend = apply_agreed_changes(
            config,
            repo_dir,
            artifacts_dir=artifacts_dir,
            plan=plan,
            conversation_text=conversation_text,
            context=context,
            context_pack=context_pack,
            head_ref=conversation.head_ref,
            pr_number=args.pr,
            model=selection.model,
            enabled=not args.no_amend,
        )
        publish_responses(
            config,
            pr_number=args.pr,
            threads={thread.id: thread for thread in pending},
            plan=plan,
            amend=amend,
            selection=selection,
            context=context,
            artifacts_dir=artifacts_dir,
        )
    finally:
        finalize_run_dir(config, run_dir, repo_dir)


def parse_response_plan(content: str, threads: list[ReviewThread]) -> dict[str, Any]:
    payload = parse_review_json(content)
    known = {thread.id for thread in threads}
    responses: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in payload.get("responses") or []:
        if not isinstance(item, dict):
            continue
        thread_id = str(item.get("thread_id") or "").strip()
        if thread_id not in known or thread_id in seen:
            continue
        seen.add(thread_id)

        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in {"agree", "disagree", "needs-clarification"}:
            verdict = "needs-clarification"
        change = str(item.get("change") or "").strip()
        responses.append(
            {
                "thread_id": thread_id,
                "verdict": verdict,
                "reply": str(item.get("reply") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "change": change if verdict == "agree" else "",
            }
        )

    for thread in threads:
        if thread.id in seen:
            continue
        responses.append(
            {
                "thread_id": thread.id,
                "verdict": "needs-clarification",
                "reply": (
                    "I did not manage to form a considered answer to this point in this round. "
                    "Could you restate what you would like changed?"
                ),
                "evidence": "",
                "change": "",
            }
        )

    return {
        "summary": str(payload.get("summary") or "").strip(),
        "review_reply": str(payload.get("review_reply") or "").strip(),
        "responses": responses,
    }


def apply_agreed_changes(
    config: RuntimeConfig,
    repo_dir: Path,
    *,
    artifacts_dir: Path,
    plan: dict[str, Any],
    conversation_text: str,
    context: RunContext,
    context_pack: str,
    head_ref: str,
    pr_number: int,
    model: str,
    enabled: bool,
) -> dict[str, Any]:
    changes = [item["change"] for item in plan["responses"] if item["verdict"] == "agree" and item["change"]]
    if not changes:
        return {"attempted": False, "pushed": False, "sha": "", "detail": "no changes were agreed"}
    if not enabled:
        return {
            "attempted": False,
            "pushed": False,
            "sha": "",
            "detail": "amending is disabled, the agreed changes were not applied",
        }

    try:
        require_tools(["aider"])
        task = respond_fix_prompt(
            repo=config.repo,
            pr_number=pr_number,
            changes=changes,
            conversation=conversation_text,
            context_pack=context_pack,
            skills_text=context.skills_text,
            investigation=context.investigation,
        )
        task_file = artifacts_dir / "respond-task.md"
        task_file.write_text(task, encoding="utf-8")

        run_aider(config, repo_dir, task_file, model)
        enforce_protected_paths(repo_dir)
        diff_text = working_diff(repo_dir)
        if not diff_text.strip():
            return {
                "attempted": True,
                "pushed": False,
                "sha": "",
                "detail": "the model produced no edits for the agreed changes",
            }

        validation_commands = build_validation_commands(
            repo_dir,
            configured_commands=dedupe(context.validation_commands + config.configured_validation_commands),
            diff_text=diff_text,
            auto_syntax=config.auto_syntax,
        )
        results = [run_diff_check(repo_dir)]
        results.extend(
            collect_validation(
                repo_dir,
                commands=validation_commands,
                diff_text=diff_text,
                timeout=config.validation_timeout,
            )
        )
        rendered = render_validation(results)
        (artifacts_dir / "respond-validation.txt").write_text(rendered, encoding="utf-8")
        assert_validation_passed(results)
    except Exception as exc:
        run(["git", "checkout", "--", "."], cwd=repo_dir, check=False)
        run(["git", "clean", "-fd"], cwd=repo_dir, check=False)
        return {
            "attempted": True,
            "pushed": False,
            "sha": "",
            "detail": f"the agreed changes did not pass validation and were discarded: {exc}",
        }

    run(["git", "add", "-A"], cwd=repo_dir)
    run(
        ["git", "commit", "-m", f"fix: address review feedback on #{pr_number}"],
        cwd=repo_dir,
    )
    sha = run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir).stdout.strip()

    if config.dry_run:
        print(f"Dry run enabled. Committed {sha} locally but did not push to {head_ref}.")
        return {"attempted": True, "pushed": False, "sha": sha, "detail": "dry run, not pushed"}

    run(["git", "push", "origin", f"HEAD:{head_ref}"], cwd=repo_dir)
    print(f"Pushed {sha} to {head_ref}")
    return {"attempted": True, "pushed": True, "sha": sha, "detail": f"pushed as {sha}"}


def publish_responses(
    config: RuntimeConfig,
    *,
    pr_number: int,
    threads: dict[str, ReviewThread],
    plan: dict[str, Any],
    amend: dict[str, Any],
    selection: ModelSelection,
    context: RunContext,
    artifacts_dir: Path,
) -> None:
    rendered: list[str] = []
    for item in plan["responses"]:
        thread = threads.get(item["thread_id"])
        if thread is None:
            continue
        body = render_thread_reply(item, amend)
        rendered.append(f"--- {thread.path}:{thread.line} ({item['verdict']}) ---\n{body}")
        if config.dry_run:
            continue
        try:
            reply_to_thread(config.repo, pr_number, thread.root_comment_id, body)
        except RuntimeError as exc:
            print(f"Could not post reply on {thread.path}: {exc}")

    summary = render_response_summary(plan, amend, selection, context)
    (artifacts_dir / "responses.md").write_text(
        summary + "\n\n" + "\n\n".join(rendered) + "\n", encoding="utf-8"
    )

    if config.dry_run:
        print(summary)
        print("\n\n".join(rendered))
        return

    summary_file = artifacts_dir / "response-summary.md"
    summary_file.write_text(summary, encoding="utf-8")
    post_conversation_comment(config.repo, pr_number, summary_file)
    print(f"Responded to review feedback on {config.repo}#{pr_number}")


def render_thread_reply(item: dict[str, Any], amend: dict[str, Any]) -> str:
    verdict = item["verdict"]
    lines: list[str] = []

    if verdict == "agree":
        if amend.get("pushed"):
            lines.append(f"**Agreed** — fixed in `{amend['sha']}`.")
        elif amend.get("attempted"):
            lines.append(f"**Agreed**, but the fix did not land: {amend['detail']}.")
        else:
            lines.append(f"**Agreed** — not applied automatically ({amend['detail']}).")
    elif verdict == "disagree":
        lines.append("**I think this one is not right** — leaving it for you to decide.")
    else:
        lines.append("**Need a steer before changing this.**")

    if item["reply"]:
        lines.extend(["", item["reply"]])
    if item["evidence"]:
        lines.extend(["", "Evidence:", "", "```text", item["evidence"], "```"])
    if verdict == "agree" and item["change"]:
        lines.extend(["", f"Change: {item['change']}"])

    lines.extend(["", AI_MARKER])
    return "\n".join(lines)


def render_response_summary(
    plan: dict[str, Any],
    amend: dict[str, Any],
    selection: ModelSelection,
    context: RunContext,
) -> str:
    counts = {"agree": 0, "disagree": 0, "needs-clarification": 0}
    for item in plan["responses"]:
        counts[item["verdict"]] += 1

    lines = ["## Pharo Agent CI Response", ""]
    if plan["summary"]:
        lines.extend([plan["summary"], ""])
    if plan["review_reply"]:
        lines.extend([plan["review_reply"], ""])

    lines.append(
        f"Responded on {len(plan['responses'])} thread(s): "
        f"{counts['agree']} agreed, {counts['disagree']} disputed, "
        f"{counts['needs-clarification']} needing a steer."
    )
    if amend.get("pushed"):
        lines.append(f"The agreed changes are pushed to this branch as `{amend['sha']}`.")
    elif amend.get("attempted") or counts["agree"]:
        lines.append(f"No commit was pushed: {amend['detail']}.")

    if counts["disagree"]:
        lines.append(
            "Disputed threads are left unresolved on purpose. They need your decision, "
            "not mine."
        )

    lines.extend(
        [
            "",
            f"Model: `{selection.summary()}`",
            f"Skills: `{context.skills.summary()}`",
        ]
    )
    if context.pharo_used:
        lines.append("Claims above were checked against a live Pharo image.")
    lines.extend(
        [
            "",
            "<sub>Generated by the self-hosted Pharo Agent CI controller. Human review is required.</sub>",
            AI_MARKER,
        ]
    )
    return "\n".join(lines)


def sweep_issues(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    require_tools(["git", "gh", "aider"])

    issues = recent_issues(config.repo, limit=args.limit, labels=args.label or [])
    if not issues:
        print("No open issues matched the sweep filters.")
        return 0

    taken = existing_issue_branches(config.repo) if args.skip_existing else set()
    outcomes: list[tuple[int, str, str]] = []

    for issue in issues:
        number = int(issue["number"])
        title = str(issue.get("title") or "")

        if number in taken:
            outcomes.append((number, "skipped", "an ai/issue branch or PR already exists"))
            continue

        try:
            enforce_daily_quota(config)
        except QuotaExceeded as exc:
            outcomes.append((number, "stopped", str(exc)))
            break

        print(f"\n=== issue #{number}: {title} ===", flush=True)
        try:
            detail = implement_issue(config, number)
            outcomes.append((number, "opened", detail))
        except Exception as exc:
            outcomes.append((number, "failed", str(exc)))
            if args.stop_on_error:
                break

    print("\n=== sweep summary ===")
    for number, status, detail in outcomes:
        print(f"#{number}: {status} - {detail}")

    failures = sum(1 for _, status, _ in outcomes if status == "failed")
    return 1 if failures and args.stop_on_error else 0


def implement_issue(config: RuntimeConfig, issue_number: int) -> str:
    issue = issue_json(config.repo, issue_number)
    title = issue.get("title") or ""
    body = issue.get("body") or ""

    stamp = timestamp()
    run_dir = config.work_root / f"{config.repo.replace('/', '-')}-issue-{issue_number}-{stamp}"
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_repo(config.repo, repo_dir)
    ignore_agent_artifacts(repo_dir)
    artifacts_dir = make_artifacts_dir(run_dir)

    try:
        base = default_branch(config.repo)
        branch_name = f"ai/issue-{issue_number}-{stamp}"
        checkout_base(repo_dir, base, branch_name)

        selection = select_model(config, title=title, body=body, diff_text="", mode="issue")
        context = build_run_context(
            config,
            repo_dir,
            artifacts_dir=artifacts_dir,
            model=selection.model,
            goal=(
                "Work out how to implement this issue in this repository. Find the files and "
                "definitions involved, confirm that anything you plan to call really exists, "
                "and identify which tests should cover the change."
            ),
            title=title,
            body=body,
            diff_text="",
        )
        context_pack = build_context_pack(
            repo_dir,
            query=f"{title}\n{body}",
            diff_text="",
            max_files=context_file_budget(config, selection),
            max_chars=context_char_budget(config, selection),
        )
        task = fix_task_prompt(
            repo=config.repo,
            pr_number=None,
            issue_number=issue_number,
            title=title,
            body=body,
            diff_text="",
            context_pack=context_pack,
            review_text="",
            validation_output="",
            skills_text=context.skills_text,
            repo_map=context.repo_map,
            investigation=context.investigation,
        )

        write_model_selection(artifacts_dir, selection)
        task_file = artifacts_dir / "issue-task.md"
        task_file.write_text(task, encoding="utf-8")
        (artifacts_dir / "rag-context.md").write_text(context_pack, encoding="utf-8")

        run_aider(config, repo_dir, task_file, selection.model)
        enforce_protected_paths(repo_dir)

        diff_text = working_diff(repo_dir)
        validation_commands = build_validation_commands(
            repo_dir,
            configured_commands=dedupe(context.validation_commands + config.configured_validation_commands),
            diff_text=diff_text,
            auto_syntax=config.auto_syntax,
        )
        final_results = [run_diff_check(repo_dir)]
        final_results.extend(
            collect_validation(
                repo_dir,
                commands=validation_commands,
                diff_text=diff_text,
                timeout=config.validation_timeout,
            )
        )
        (artifacts_dir / "final-validation.txt").write_text(render_validation(final_results), encoding="utf-8")
        assert_validation_passed(final_results)
        ensure_changes(repo_dir)

        return commit_and_maybe_publish(
            config=config,
            repo_dir=repo_dir,
            branch_name=branch_name,
            commit_message=f"fix: resolve issue #{issue_number}",
            pr_title=title or f"Resolve issue #{issue_number}",
            pr_body=render_issue_pr_body(
                issue_number, render_validation(final_results), selection, context
            ),
            base=base,
        )
    finally:
        finalize_run_dir(config, run_dir, repo_dir)


def build_run_context(
    config: RuntimeConfig,
    repo_dir: Path,
    *,
    artifacts_dir: Path,
    model: str,
    goal: str,
    title: str,
    body: str,
    diff_text: str,
) -> RunContext:
    changed = extract_changed_files(diff_text) or repo_file_list(repo_dir)
    skills = select_skills(load_skills(repo_dir, subdir=config.skills_dir), changed_files=changed)
    skills_text = render_skills(skills)
    if skills.skills:
        print(f"Skills loaded: {skills.summary()}")
    if skills.skipped:
        print(f"Skills skipped: {', '.join(skills.skipped)}")

    repo_map = ""
    if config.max_repo_map_chars > 0:
        repo_map = build_repo_map(repo_dir, max_chars=config.max_repo_map_chars)
        (artifacts_dir / "repo-map.md").write_text(repo_map, encoding="utf-8")

    if skills_text:
        (artifacts_dir / "skills.md").write_text(skills_text, encoding="utf-8")

    investigation, pharo_used = investigate(
        config,
        repo_dir,
        artifacts_dir=artifacts_dir,
        model=model,
        goal=goal,
        title=title,
        body=body,
        diff_text=diff_text,
        skills=skills,
        skills_text=skills_text,
        repo_map=repo_map,
    )

    return RunContext(
        skills=skills,
        skills_text=skills_text,
        repo_map=repo_map,
        investigation=investigation,
        pharo_used=pharo_used,
    )


def investigate(
    config: RuntimeConfig,
    repo_dir: Path,
    *,
    artifacts_dir: Path,
    model: str,
    goal: str,
    title: str,
    body: str,
    diff_text: str,
    skills: SkillSelection,
    skills_text: str,
    repo_map: str,
) -> tuple[str, bool]:
    if not config.agent_enabled:
        return "", False

    allowed_commands = dedupe(skills.validate_commands + config.configured_validation_commands)
    image: PharoImage | None = None
    pharo_client: PharoMcpClient | None = None

    try:
        image, pharo_client = start_pharo(repo_dir, artifacts_dir.parent / "pharo", skills=skills)
        tools = build_tools(
            repo_dir=repo_dir,
            pharo=pharo_client,
            allowed_commands=allowed_commands,
            timeout=config.validation_timeout,
        )
        print(f"Investigation tools: {', '.join(tool.name for tool in tools)}")

        run_state = run_agent(
            OllamaClient(config.ollama_base_url, model),
            system_prompt=EXPLORE_SYSTEM_PROMPT,
            user_prompt=explore_user_prompt(
                goal=goal,
                repo=config.repo,
                title=title,
                body=body,
                diff_text=diff_text,
                repo_map=repo_map,
                skills_text=skills_text,
            ),
            tools=tools,
            max_iterations=config.agent_max_iterations,
        )

        transcript = run_state.transcript()
        (artifacts_dir / "investigation.md").write_text(
            f"# Investigation\n\nBriefing:\n\n{run_state.final_text}\n\n"
            f"Tool calls ({len(run_state.calls)} over {run_state.iterations} rounds):\n\n{transcript}\n",
            encoding="utf-8",
        )
        print(
            f"Investigation: {len(run_state.calls)} tool calls over "
            f"{run_state.iterations} rounds"
            + (" (hit iteration limit)" if run_state.stopped_early else "")
        )
        return (
            render_investigation(run_state.final_text, transcript, tools_used=run_state.tool_names()),
            pharo_client is not None,
        )
    except Exception as exc:
        print(f"Investigation skipped: {exc}")
        return "", False
    finally:
        if image is not None:
            image.stop()


def start_pharo(
    repo_dir: Path,
    work_dir: Path,
    *,
    skills: SkillSelection,
) -> tuple[PharoImage | None, PharoMcpClient | None]:
    pharo_config = PharoConfig.from_environment()
    if not pharo_config.enabled or not wants_pharo(repo_dir, skills):
        return None, None

    try:
        image = PharoImage(config=pharo_config, repo_dir=repo_dir, work_dir=work_dir)
        image.start()
        client = image.client()
        client.initialize()
        print(f"Pharo image ready on {image.endpoint}")
        return image, client
    except PharoUnavailable as exc:
        print(f"Pharo image unavailable, continuing without it: {exc}")
        return None, None


def wants_pharo(repo_dir: Path, skills: SkillSelection) -> bool:
    if any(tool.startswith("pharo_") for tool in skills.tools):
        return True
    return any(repo_dir.rglob("*.class.st"))


def collect_validation(
    repo_dir: Path,
    *,
    commands: list[str],
    diff_text: str,
    timeout: int,
) -> list:
    results = []
    tonel_result = run_tonel_check(repo_dir, diff_text=diff_text)
    if tonel_result is not None:
        results.append(tonel_result)
    results.extend(run_validation(repo_dir, commands, timeout=timeout))
    return results


def working_diff(repo_dir: Path) -> str:
    tracked = run(["git", "diff", "--patch"], cwd=repo_dir).stdout
    untracked = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo_dir).stdout
    synthetic = "".join(
        f"diff --git a/{path} b/{path}\n" for path in untracked.splitlines() if path.strip()
    )
    return tracked + synthetic


def recent_issues(repo: str, *, limit: int, labels: list[str]) -> list[dict]:
    command = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(max(1, limit)),
        "--json",
        "number,title,labels,createdAt",
    ]
    for label in labels:
        command.extend(["--label", label])
    result = run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Could not list issues:\n{result.combined_output}")
    return json.loads(result.stdout or "[]")


def existing_issue_branches(repo: str) -> set[int]:
    result = run(
        ["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "200", "--json", "headRefName"],
        check=False,
    )
    if result.returncode != 0:
        return set()

    numbers: set[int] = set()
    for item in json.loads(result.stdout or "[]"):
        match = re.match(r"ai/issue-(\d+)-", str(item.get("headRefName") or ""))
        if match:
            numbers.add(int(match.group(1)))
    return numbers


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
        max_repo_map_chars=args.max_repo_map_chars,
        skills_dir=args.skills_dir,
        agent_enabled=not args.no_agent,
        agent_max_iterations=args.agent_max_iterations,
        daily_limit=args.daily_limit,
        quota_workflow_prefix=args.quota_workflow_prefix,
        allow_forks=args.allow_forks,
        auto_syntax=not args.no_auto_syntax,
        extra_context=args.extra_context,
        keep_work_dir=args.keep_work_dir,
        work_retention_days=args.work_retention_days,
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
        "Set PHARO_AGENT_ALLOW_FORKS=true only after isolating the runner per job."
    )


def enforce_daily_quota(config: RuntimeConfig) -> None:
    if config.daily_limit <= 0:
        return
    start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")
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
        f"Daily Pharo Agent quota: {used}/{config.daily_limit} "
        f"runs since {start} for workflow prefix `{config.quota_workflow_prefix}`."
    )


def prepare_pr_checkout(config: RuntimeConfig, pr_number: int) -> tuple[Path, Path]:
    prune_work_root(config)
    stamp = timestamp()
    run_dir = config.work_root / f"{config.repo.replace('/', '-')}-pr-{pr_number}-{stamp}"
    repo_dir = run_dir / "repo"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_repo(config.repo, repo_dir)
    checkout_pr(repo_dir, pr_number)
    ignore_agent_artifacts(repo_dir)
    return run_dir, repo_dir


def make_artifacts_dir(run_dir: Path) -> Path:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def ignore_agent_artifacts(repo_dir: Path) -> None:
    exclude_file = repo_dir / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text(encoding="utf-8") if exclude_file.is_file() else ""
    missing = [pattern for pattern in AGENT_ARTIFACT_PATTERNS if pattern not in existing]
    if not missing:
        return
    with exclude_file.open("a", encoding="utf-8") as handle:
        handle.write("\n# added by ai-ci-controller\n")
        handle.write("\n".join(missing) + "\n")


def finalize_run_dir(config: RuntimeConfig, run_dir: Path, repo_dir: Path) -> None:
    if config.keep_work_dir:
        print(f"Work directory kept at {run_dir}")
        return
    shutil.rmtree(repo_dir, ignore_errors=True)
    shutil.rmtree(run_dir / "pharo", ignore_errors=True)


def prune_work_root(config: RuntimeConfig) -> None:
    if config.work_retention_days <= 0 or not config.work_root.is_dir():
        return
    cutoff = time.time() - config.work_retention_days * 86_400
    for path in config.work_root.iterdir():
        if not path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def repo_file_list(repo_dir: Path, *, limit: int = 5_000) -> list[str]:
    result = run(["git", "ls-files"], cwd=repo_dir, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.splitlines()[:limit]
    return [
        str(path.relative_to(repo_dir))
        for path in list(repo_dir.rglob("*"))[:limit]
        if path.is_file() and ".git" not in path.parts
    ]


def parse_review_json(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"Model did not return JSON:\n{content}") from exc
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
    context: RunContext,
) -> str:
    findings = review.get("findings") or []
    lines = [
        "## Pharo Agent CI Review",
        "",
        review.get("summary") or "No summary returned.",
        "",
        f"Risk level: `{review.get('risk_level', 'medium')}`",
        f"Model: `{model_selection.summary()}`",
        f"Skills: `{context.skills.summary()}`",
    ]
    if context.pharo_used:
        lines.append("Verified against a live Pharo image.")
    lines.append("")

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
            "<sub>Generated by the self-hosted Pharo Agent CI controller. Human review is required.</sub>",
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
) -> str:
    run(["git", "switch", "-c", branch_name], cwd=repo_dir, check=False)
    run(["git", "add", "-A"], cwd=repo_dir)
    run(["git", "commit", "-m", commit_message], cwd=repo_dir)
    if config.dry_run:
        stat = run(["git", "show", "--stat", "--oneline", "HEAD"], cwd=repo_dir).stdout
        print("Dry run enabled. Created local commit but did not push or open a PR.")
        print(stat)
        return f"dry run, local commit on {branch_name}"
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
    return pr_url


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
    context: RunContext,
) -> str:
    return (
        f"Follow-up fixes for #{pr.number}.\n\n"
        "This draft PR was generated by the Pharo Agent CI controller using a locally hosted model.\n\n"
        f"{render_provenance(model_selection, context)}\n\n"
        "Human review is required before merge.\n\n"
        f"Source PR: {pr.url}\n\n"
        "## Validation\n\n"
        f"```text\n{validation_output or '(no validation commands configured)'}\n```"
    )


def render_issue_pr_body(
    issue_number: int,
    validation_output: str,
    model_selection: ModelSelection,
    context: RunContext,
) -> str:
    return (
        f"Closes #{issue_number}\n\n"
        "This draft PR was generated by the Pharo Agent CI controller using a locally hosted model.\n\n"
        f"{render_provenance(model_selection, context)}\n\n"
        "Human review is required before merge.\n\n"
        f"## Validation\n\n```text\n{validation_output or '(no validation commands configured)'}\n```"
    )


def render_provenance(model_selection: ModelSelection, context: RunContext) -> str:
    lines = [
        f"Model selection: `{model_selection.summary()}`",
        f"Skills applied: `{context.skills.summary()}`",
    ]
    if context.pharo_used:
        lines.append("The agent verified its assumptions against a live Pharo image before editing.")
    return "\n\n".join(lines)


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
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


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


def env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def str_to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
