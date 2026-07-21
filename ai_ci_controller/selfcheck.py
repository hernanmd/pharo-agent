from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .command import run
from .pharo import PharoConfig, PharoImage, PharoUnavailable


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    required: bool

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def blocking(self) -> bool:
        return self.required and self.status == "fail"


def run_selfcheck(
    *,
    ollama_base_url: str,
    models: list[str],
    work_dir: Path,
    repo_dir: Path,
    require_pharo: bool,
    require_aider: bool,
) -> list[Check]:
    checks: list[Check] = [
        binary_check("git", required=True),
        binary_check("gh", required=True),
        binary_check("aider", required=require_aider),
        gh_auth_check(),
    ]

    tags, ollama_check = ollama_reachable(ollama_base_url)
    checks.append(ollama_check)
    if tags is not None:
        checks.extend(model_checks(tags, models))

    checks.extend(pharo_checks(work_dir=work_dir, repo_dir=repo_dir, required=require_pharo))
    return checks


def binary_check(name: str, *, required: bool) -> Check:
    path = shutil.which(name)
    if path:
        return Check(name=f"`{name}` on PATH", status="ok", detail=path, required=required)
    return Check(
        name=f"`{name}` on PATH",
        status="fail" if required else "warn",
        detail="not found",
        required=required,
    )


def gh_auth_check() -> Check:
    if not shutil.which("gh"):
        return Check(name="gh authenticated", status="fail", detail="gh is not installed", required=True)

    result = run(["gh", "auth", "status"], check=False)
    if result.returncode != 0:
        return Check(
            name="gh authenticated",
            status="fail",
            detail="gh auth status failed; run `gh auth login` or set GH_TOKEN",
            required=True,
        )
    account = next(
        (line.strip() for line in result.combined_output.splitlines() if "account" in line.lower()),
        "authenticated",
    )
    return Check(name="gh authenticated", status="ok", detail=account, required=True)


def ollama_reachable(base_url: str) -> tuple[dict | None, Check]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return None, Check(
            name="Ollama reachable",
            status="fail",
            detail=f"{url} did not answer: {exc}",
            required=True,
        )

    count = len(payload.get("models") or [])
    return payload, Check(
        name="Ollama reachable",
        status="ok",
        detail=f"{base_url} serving {count} model(s)",
        required=True,
    )


def model_checks(tags: dict, models: list[str]) -> list[Check]:
    available = {str(item.get("name") or "") for item in tags.get("models") or []}
    bare = {name.split(":", 1)[0] for name in available}

    checks: list[Check] = []
    for model in dict.fromkeys(name for name in models if name):
        present = model in available or model.split(":", 1)[0] in bare
        checks.append(
            Check(
                name=f"model `{model}` pulled",
                status="ok" if present else "fail",
                detail="available" if present else f"run `ollama pull {model}`",
                required=True,
            )
        )
    if not checks:
        checks.append(
            Check(
                name="models configured",
                status="warn",
                detail="no model names were passed to check",
                required=False,
            )
        )
    return checks


def pharo_checks(*, work_dir: Path, repo_dir: Path, required: bool) -> list[Check]:
    config = PharoConfig.from_environment()
    if not config.enabled:
        return [
            Check(
                name="Pharo configured",
                status="fail" if required else "warn",
                detail="PHARO_VM and PHARO_IMAGE are not both set",
                required=required,
            )
        ]

    checks = [
        Check(
            name="Pharo configured",
            status="ok",
            detail=f"vm={config.vm} image={config.base_image}",
            required=required,
        )
    ]

    image = PharoImage(config=config, repo_dir=repo_dir, work_dir=work_dir)
    try:
        image.start()
    except PharoUnavailable as exc:
        checks.append(
            Check(
                name="Pharo image boots",
                status="fail" if required else "warn",
                detail=str(exc).replace("\n", " ")[:400],
                required=required,
            )
        )
        return checks

    try:
        checks.append(
            Check(
                name="Pharo image boots",
                status="ok",
                detail=f"MCP server answering on {image.endpoint}",
                required=required,
            )
        )
        client = image.client()
        client.initialize()
        tools = [str(tool.get("name")) for tool in client.list_tools()]
        missing = [
            name
            for name in ("pharo_eval", "pharo_class_source", "pharo_method_source")
            if name not in tools
        ]
        checks.append(
            Check(
                name="Pharo MCP tools present",
                status="ok" if not missing else "fail",
                detail=", ".join(tools) if not missing else f"missing: {', '.join(missing)}",
                required=required,
            )
        )

        text, is_error = client.evaluate("3 + 4")
        arithmetic_ok = not is_error and text.strip() == "7"
        checks.append(
            Check(
                name="pharo_eval works",
                status="ok" if arithmetic_ok else "fail",
                detail=f"`3 + 4` returned {text.strip()!r}",
                required=required,
            )
        )

        text, is_error = client.evaluate("OrderedCollection new addAll: #(1 2 3); yourself")
        library_ok = not is_error and "1 2 3" in text
        checks.append(
            Check(
                name="Pharo class library loaded",
                status="ok" if library_ok else "fail",
                detail=f"OrderedCollection returned {text.strip()[:80]!r}",
                required=required,
            )
        )
    except PharoUnavailable as exc:
        checks.append(
            Check(name="Pharo MCP usable", status="fail", detail=str(exc)[:300], required=required)
        )
    finally:
        image.stop()

    return checks


def render_checks(checks: list[Check]) -> str:
    icons = {"ok": "ok", "warn": "warn", "fail": "**FAIL**"}
    lines = [
        "# Pharo Agent Runner Self-Check",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        detail = check.detail.replace("|", "\\|")[:160]
        lines.append(f"| {check.name} | {icons.get(check.status, check.status)} | {detail} |")

    blocking = [check for check in checks if check.blocking]
    warnings = [check for check in checks if check.status == "warn"]
    lines.append("")
    if blocking:
        lines.append(f"**{len(blocking)} required check(s) failed.** This runner cannot do the work yet.")
        lines.extend(f"- {check.name}: {check.detail}" for check in blocking)
    else:
        lines.append("All required checks passed.")
    if warnings:
        lines.append("")
        lines.append(f"{len(warnings)} optional check(s) warned:")
        lines.extend(f"- {check.name}: {check.detail}" for check in warnings)
    return "\n".join(lines) + "\n"
