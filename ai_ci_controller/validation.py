from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import shutil

from .command import CommandResult, run, run_shell
from .rag import extract_changed_files
from .tonel import validate_paths


MAX_FALLBACK_SCAN_FILES = 400


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


def build_validation_commands(
    repo_dir: Path,
    *,
    configured_commands: list[str],
    diff_text: str,
    auto_syntax: bool,
) -> list[str]:
    commands: list[str] = []
    if auto_syntax:
        commands.extend(detect_syntax_commands(repo_dir, diff_text=diff_text))
    commands.extend(command for command in configured_commands if command)
    return dedupe(commands)


def detect_syntax_commands(repo_dir: Path, *, diff_text: str) -> list[str]:
    changed = extract_changed_files(diff_text)
    files = [repo_dir / path for path in changed] if changed else []
    if not files:
        files = [
            path
            for path in sorted(repo_dir.rglob("*"))
            if path.is_file() and ".git" not in path.parts
        ][:MAX_FALLBACK_SCAN_FILES]

    commands: list[str] = []
    python_files = existing_relative_files(repo_dir, files, {".py"})
    if python_files and shutil.which("python"):
        commands.append(f"python -m py_compile {quote_paths(python_files)}")

    shell_files = existing_relative_files(repo_dir, files, {".sh", ".bash"})
    if shell_files and shutil.which("bash"):
        commands.append("bash -n " + " ".join(shlex.quote(path) for path in shell_files))

    json_files = existing_relative_files(repo_dir, files, {".json"})
    if json_files and shutil.which("python"):
        commands.extend(
            f"python -m json.tool {shlex.quote(path)} >/dev/null"
            for path in json_files[:20]
        )

    js_files = existing_relative_files(repo_dir, files, {".js", ".mjs", ".cjs"})
    if js_files and shutil.which("node"):
        commands.extend(f"node --check {shlex.quote(path)}" for path in js_files[:20])

    return commands


def run_tonel_check(repo_dir: Path, *, diff_text: str) -> ValidationResult | None:
    changed = [path for path in extract_changed_files(diff_text) if path.lower().endswith(".st")]
    if not changed:
        return None

    problems = validate_paths(repo_dir, changed)
    checked = ", ".join(changed[:10])
    if len(changed) > 10:
        checked += f", (+{len(changed) - 10} more)"

    if problems:
        output = "\n".join(problems)
    else:
        output = f"{len(changed)} Tonel file(s) parsed cleanly: {checked}"

    return ValidationResult(
        name="tonel syntax check",
        command="tonel syntax check",
        passed=not problems,
        output=output,
    )


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


def existing_relative_files(repo_dir: Path, files: list[Path], suffixes: set[str]) -> list[str]:
    result: list[str] = []
    for path in files:
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            relative = path.relative_to(repo_dir)
        except ValueError:
            continue
        result.append(str(relative))
    return sorted(set(result))


def quote_paths(paths: list[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def dedupe(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        unique.append(command)
    return unique
