from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in [self.stdout, self.stderr] if part)


class CommandError(RuntimeError):
    def __init__(self, result: CommandResult):
        self.result = result
        rendered = " ".join(shlex.quote(arg) for arg in result.args)
        super().__init__(
            f"Command failed with exit code {result.returncode}: {rendered}\n"
            f"{result.combined_output}"
        )


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    input_text: str | None = None,
    timeout: int | None = None,
) -> CommandResult:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=process_env,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    result = CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        raise CommandError(result)
    return result


def run_shell(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int | None = None,
) -> CommandResult:
    return run(["bash", "-lc", command], cwd=cwd, env=env, check=check, timeout=timeout)


def require_binary(name: str) -> None:
    result = run(["bash", "-lc", f"command -v {shlex.quote(name)}"], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Required executable not found on PATH: {name}")

