from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command import CommandResult, run, run_shell


@dataclass(frozen=True)
class ValidationResult:
    name: str
    command: str
    passed: bool
    output: str


def run_validation(repo_dir: Path, commands: list[str], *, timeout: int) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for command in commands:
        result = run_shell(command, cwd=repo_dir, check=False, timeout=timeout)
        results.append(
            ValidationResult(
                name=command,
                command=command,
                passed=result.returncode == 0,
                output=_format_result(result),
            )
        )
    return results


def run_diff_check(repo_dir: Path) -> ValidationResult:
    result = run(["git", "diff", "--check"], cwd=repo_dir, check=False)
    return ValidationResult(
        name="git diff --check",
        command="git diff --check",
        passed=result.returncode == 0,
        output=_format_result(result),
    )


def render_validation(results: list[ValidationResult]) -> str:
    if not results:
        return ""
    blocks: list[str] = []
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        output = result.output.strip() or "(no output)"
        blocks.append(f"$ {result.command}\n[{status}]\n{output}")
    return "\n\n".join(blocks)


def assert_validation_passed(results: list[ValidationResult]) -> None:
    failed = [result for result in results if not result.passed]
    if failed:
        rendered = render_validation(failed)
        raise RuntimeError(f"Validation failed:\n{rendered}")


def _format_result(result: CommandResult, *, limit: int = 16_000) -> str:
    output = result.combined_output
    if len(output) <= limit:
        return output
    return f"{output[: limit // 2]}\n\n[...snipped...]\n\n{output[-limit // 2 :]}"

