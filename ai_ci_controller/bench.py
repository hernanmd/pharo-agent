from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import AgentTool, run_agent
from .ollama import OllamaClient
from .pharo import PharoMcpClient, PharoUnavailable
from .prompts import REVIEW_SYSTEM_PROMPT
from .skills import parse_frontmatter
from .tonel import parse_tonel

TASK_KINDS = ("tonel", "selector", "review")
TASK_LIST_KEYS = {"expect_selectors", "expect_class_selectors", "expect_keywords"}
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(?P<code>.*?)```", re.DOTALL)

TONEL_SYSTEM_PROMPT = """You write Pharo Smalltalk in Tonel format.

Reply with the complete Tonel source for the file and nothing else. No commentary,
no explanation. A Tonel class file looks exactly like this:

Class {
\t#name : 'Example',
\t#superclass : 'Object',
\t#instVars : [ 'thing' ],
\t#category : 'Example-Core',
\t#package : 'Example-Core'
}

{ #category : 'accessing' }
Example >> thing [

\t^ thing
]

Every method needs its own { #category : '...' } header. The receiver before >>
must match #name. Class-side methods use "Example class >> selector"."""

SELECTOR_SYSTEM_PROMPT = """You answer questions about the Pharo class library.

Reply with exactly one word: yes or no. No explanation, no punctuation.
If you are not certain, and you have a tool that can check, use the tool first."""


@dataclass(frozen=True)
class BenchTask:
    name: str
    kind: str
    description: str
    prompt: str
    expect: dict

    @property
    def needs_image(self) -> bool:
        return self.kind == "selector"


@dataclass(frozen=True)
class BenchResult:
    task: BenchTask
    status: str
    detail: str
    output: str
    seconds: float

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def skipped(self) -> bool:
        return self.status == "skip"


@dataclass
class BenchReport:
    model: str
    grounded: bool
    results: list[BenchResult] = field(default_factory=list)

    @property
    def scored(self) -> list[BenchResult]:
        return [result for result in self.results if not result.skipped]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.scored if result.passed)

    @property
    def total(self) -> int:
        return len(self.scored)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    @property
    def errors(self) -> list[BenchResult]:
        return [result for result in self.results if result.status == "error"]

    def by_kind(self) -> dict[str, tuple[int, int]]:
        tally: dict[str, tuple[int, int]] = {}
        for result in self.scored:
            hits, total = tally.get(result.task.kind, (0, 0))
            tally[result.task.kind] = (hits + int(result.passed), total + 1)
        return tally


def load_tasks(directory: Path) -> list[BenchTask]:
    if not directory.is_dir():
        return []

    tasks: list[BenchTask] = []
    for path in sorted(directory.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = FRONTMATTER_RE.match(text)
        if not match:
            continue

        fields = parse_frontmatter(match.group("frontmatter"), list_keys=TASK_LIST_KEYS)
        kind = str(fields.get("kind") or "").strip().lower()
        if kind not in TASK_KINDS:
            continue

        tasks.append(
            BenchTask(
                name=str(fields.get("name") or path.stem),
                kind=kind,
                description=str(fields.get("description") or ""),
                prompt=match.group("body").strip(),
                expect={
                    key: value
                    for key, value in fields.items()
                    if key not in {"name", "kind", "description"}
                },
            )
        )
    return tasks


def run_bench(
    client: OllamaClient,
    tasks: list[BenchTask],
    *,
    pharo: PharoMcpClient | None,
    tools: list[AgentTool],
    max_iterations: int = 6,
) -> BenchReport:
    report = BenchReport(model=client.model, grounded=bool(tools))

    for task in tasks:
        if task.needs_image and pharo is None:
            report.results.append(
                BenchResult(
                    task=task,
                    status="skip",
                    detail="needs a live Pharo image to establish ground truth",
                    output="",
                    seconds=0.0,
                )
            )
            continue

        started = time.monotonic()
        try:
            report.results.append(score_task(client, task, pharo=pharo, tools=tools, max_iterations=max_iterations))
        except Exception as exc:
            report.results.append(
                BenchResult(
                    task=task,
                    status="error",
                    detail=f"the harness failed: {exc}",
                    output="",
                    seconds=time.monotonic() - started,
                )
            )
    return report


def score_task(
    client: OllamaClient,
    task: BenchTask,
    *,
    pharo: PharoMcpClient | None,
    tools: list[AgentTool],
    max_iterations: int,
) -> BenchResult:
    started = time.monotonic()

    if task.kind == "tonel":
        output = ask(client, TONEL_SYSTEM_PROMPT, task.prompt, tools=tools, max_iterations=max_iterations)
        status, detail = score_tonel(task, output)
    elif task.kind == "selector":
        output = ask(client, SELECTOR_SYSTEM_PROMPT, task.prompt, tools=tools, max_iterations=max_iterations)
        status, detail = score_selector(task, output, pharo=pharo)
    else:
        output = client.chat(
            [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": task.prompt},
            ],
            json_format=True,
        )
        status, detail = score_review(task, output)

    return BenchResult(
        task=task,
        status=status,
        detail=detail,
        output=output,
        seconds=time.monotonic() - started,
    )


def ask(
    client: OllamaClient,
    system_prompt: str,
    user_prompt: str,
    *,
    tools: list[AgentTool],
    max_iterations: int,
) -> str:
    if not tools:
        return client.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        )
    run_state = run_agent(
        client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=tools,
        max_iterations=max_iterations,
    )
    return run_state.final_text


def score_tonel(task: BenchTask, output: str) -> tuple[str, str]:
    source = extract_code(output)
    if not source.strip():
        return "fail", "produced no source"

    parsed = parse_tonel(f"{task.name}.class.st", source)
    if not parsed.ok:
        return "fail", "does not parse as Tonel: " + "; ".join(parsed.errors[:3])

    expected_class = str(task.expect.get("expect_class") or "").strip()
    if expected_class and parsed.name != expected_class:
        return "fail", f"defined class '{parsed.name}', expected '{expected_class}'"

    expected_superclass = str(task.expect.get("expect_superclass") or "").strip()
    if expected_superclass and parsed.superclass != expected_superclass:
        return "fail", f"superclass '{parsed.superclass}', expected '{expected_superclass}'"

    produced = {method.selector for method in parsed.methods}
    wanted = {str(item) for item in task.expect.get("expect_selectors") or []}
    missing = sorted(wanted - produced)
    if missing:
        return "fail", f"parses, but is missing selector(s): {', '.join(missing)}"

    wanted_class_side = {str(item) for item in task.expect.get("expect_class_selectors") or []}
    produced_class_side = {method.selector for method in parsed.methods if method.class_side}
    missing_class_side = sorted(wanted_class_side - produced_class_side)
    if missing_class_side:
        return "fail", f"parses, but missing class-side selector(s): {', '.join(missing_class_side)}"

    return "pass", f"parses cleanly with {len(parsed.methods)} method(s)"


def score_selector(task: BenchTask, output: str, *, pharo: PharoMcpClient | None) -> tuple[str, str]:
    expression = str(task.expect.get("ground_truth") or "").strip()
    if not expression:
        return "error", "task has no ground_truth expression"
    if pharo is None:
        return "skip", "no image available"

    try:
        truth_text, is_error = pharo.evaluate(expression)
    except PharoUnavailable as exc:
        return "error", f"could not reach the image: {exc}"
    if is_error:
        return "error", f"ground truth expression failed in the image: {truth_text}"

    truth = truth_text.strip().lower() == "true"
    claim = parse_yes_no(output)
    if claim is None:
        return "fail", f"did not answer yes or no (said {output.strip()[:60]!r})"
    if claim != truth:
        wrong = "claimed it exists when it does not" if claim else "claimed it does not exist when it does"
        return "fail", f"{wrong} (image says {truth_text.strip()})"
    return "pass", f"agrees with the image ({truth_text.strip()})"


def score_review(task: BenchTask, output: str) -> tuple[str, str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", output, flags=re.DOTALL)
        if not match:
            return "fail", "did not return JSON"
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return "fail", "did not return parseable JSON"

    findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings, list) or not findings:
        return "fail", "reported no findings"

    expected_file = str(task.expect.get("expect_file") or "").strip()
    files = [str((item or {}).get("file") or "") for item in findings if isinstance(item, dict)]
    if expected_file and not any(expected_file in candidate for candidate in files):
        return "fail", f"flagged {files or ['nothing']}, expected a finding in {expected_file}"

    keywords = [str(item).lower() for item in task.expect.get("expect_keywords") or []]
    if keywords:
        blob = json.dumps(findings).lower()
        hits = [word for word in keywords if word in blob]
        if not hits:
            return "fail", f"found an issue in the right file but never mentioned {keywords}"
        return "pass", f"flagged {expected_file} mentioning {hits}"

    return "pass", f"flagged {expected_file}"


def extract_code(output: str) -> str:
    fences = CODE_FENCE_RE.findall(output)
    if fences:
        for block in fences:
            if "Class {" in block or "Extension {" in block or "Trait {" in block:
                return block
        return fences[0]
    return output


def parse_yes_no(output: str) -> bool | None:
    text = output.strip().lower()
    match = re.search(r"\b(yes|no|true|false)\b", text)
    if not match:
        return None
    return match.group(1) in {"yes", "true"}


def render_scorecard(report: BenchReport) -> str:
    grounding = "with a live Pharo image and repo tools" if report.grounded else "with no tools (raw model)"
    lines = [
        "# Pharo Agent Capability Benchmark",
        "",
        f"Model: `{report.model}`",
        f"Mode: {grounding}",
        "",
    ]

    if report.total:
        lines.append(f"**{report.passed}/{report.total} passed ({report.pass_rate:.0%})**")
    else:
        lines.append("**No tasks were scored.**")
    if report.errors:
        lines.extend(
            [
                "",
                f"{len(report.errors)} task(s) failed inside the harness rather than being scored "
                "(timeout, unreachable image, malformed task). Those say nothing about the model \u2014 "
                "fix them before reading the score.",
            ]
        )
    lines.append("")

    tally = report.by_kind()
    if tally:
        lines.extend(["| Kind | Passed | Measures |", "| --- | --- | --- |"])
        meaning = {
            "tonel": "can it write Pharo that actually parses",
            "selector": "does it hallucinate methods that do not exist",
            "review": "does it find a seeded bug",
        }
        for kind in sorted(tally):
            hits, total = tally[kind]
            lines.append(f"| `{kind}` | {hits}/{total} | {meaning.get(kind, '')} |")
        lines.append("")

    lines.extend(["| Task | Result | Detail | Time |", "| --- | --- | --- | --- |"])
    icons = {"pass": "pass", "fail": "**fail**", "skip": "skip", "error": "**error**"}
    for result in report.results:
        detail = result.detail.replace("|", "\\|")[:140]
        lines.append(
            f"| `{result.task.name}` | {icons.get(result.status, result.status)} | "
            f"{detail} | {result.seconds:.1f}s |"
        )
    lines.append("")

    skipped = [result for result in report.results if result.skipped]
    if skipped:
        lines.extend(
            [
                f"{len(skipped)} task(s) were skipped because no Pharo image was available. "
                "Selector grounding is the measurement that matters most for Pharo, so configure "
                "`PHARO_VM` and `PHARO_IMAGE` before trusting this score.",
                "",
            ]
        )

    lines.append(
        "This score is indicative, not a gate. Local model output varies between runs; "
        "read the trend across runs and models rather than any single number."
    )
    return "\n".join(lines) + "\n"
