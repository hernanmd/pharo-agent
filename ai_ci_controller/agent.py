from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .command import run_shell
from .ollama import OllamaClient
from .pharo import PharoMcpClient, PharoUnavailable
from .rag import read_text


MAX_TOOL_OUTPUT = 6_000
MAX_LISTED_FILES = 200
DEFAULT_MAX_ITERATIONS = 12


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], str]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    output: str


@dataclass
class AgentRun:
    messages: list[dict] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    iterations: int = 0
    stopped_early: bool = False

    def transcript(self) -> str:
        if not self.calls:
            return "(the model made no tool calls)"
        blocks: list[str] = []
        for index, call in enumerate(self.calls, start=1):
            arguments = json.dumps(call.arguments, sort_keys=True)
            blocks.append(f"{index}. {call.name}({arguments})\n{indent(call.output)}")
        return "\n\n".join(blocks)

    def tool_names(self) -> list[str]:
        names: list[str] = []
        for call in self.calls:
            if call.name not in names:
                names.append(call.name)
        return names


def run_agent(
    client: OllamaClient,
    *,
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentRun:
    registry = {tool.name: tool for tool in tools}
    schemas = [tool.schema() for tool in tools]
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    run_state = AgentRun(messages=messages)

    if not tools:
        run_state.final_text = client.chat(messages)
        return run_state

    for iteration in range(1, max_iterations + 1):
        run_state.iterations = iteration
        message = client.chat_message(messages, tools=schemas)
        messages.append(strip_message(message))

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            run_state.final_text = str(message.get("content") or "")
            return run_state

        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name = str(function.get("name") or "")
            arguments = normalize_arguments(function.get("arguments"))
            output = dispatch(registry, name, arguments)
            run_state.calls.append(ToolCall(name=name, arguments=arguments, output=output))
            messages.append({"role": "tool", "name": name, "content": output})

    run_state.stopped_early = True
    messages.append(
        {
            "role": "user",
            "content": (
                f"You have reached the {max_iterations} tool-call limit. "
                "Stop investigating and answer now with what you have."
            ),
        }
    )
    run_state.final_text = client.chat(messages)
    return run_state


def dispatch(registry: dict[str, AgentTool], name: str, arguments: dict) -> str:
    tool = registry.get(name)
    if not tool:
        return f"ERROR: unknown tool '{name}'. Available tools: {', '.join(sorted(registry))}"
    try:
        return truncate(tool.handler(arguments))
    except Exception as exc:
        return f"ERROR: {tool.name} failed: {exc}"


def normalize_arguments(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def strip_message(message: dict) -> dict:
    kept = {key: value for key, value in message.items() if key in ("role", "content", "tool_calls")}
    kept.setdefault("role", "assistant")
    kept.setdefault("content", "")
    return kept


def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = text if isinstance(text, str) else str(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[...output truncated at {limit} characters...]"


def indent(text: str, prefix: str = "   | ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines()[:40])


def build_tools(
    *,
    repo_dir: Path,
    pharo: PharoMcpClient | None,
    allowed_commands: list[str],
    timeout: int,
) -> list[AgentTool]:
    tools = [
        AgentTool(
            name="read_file",
            description=(
                "Read a UTF-8 text file from the checked-out repository. "
                "Use this to see the full source of any file listed in the repository map."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative path, e.g. src/MyPackage/MyClass.class.st",
                    }
                },
                "required": ["path"],
            },
            handler=lambda args: read_repo_file(repo_dir, str(args.get("path", ""))),
        ),
        AgentTool(
            name="list_files",
            description="List repository files matching a glob pattern, e.g. 'src/**/*.class.st'.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern relative to the repository root."}
                },
                "required": ["pattern"],
            },
            handler=lambda args: list_repo_files(repo_dir, str(args.get("pattern", "*"))),
        ),
    ]

    if allowed_commands:
        listing = "\n".join(f"- {command}" for command in allowed_commands)
        tools.append(
            AgentTool(
                name="run_check",
                description=(
                    "Run one of the repository's configured verification commands and return its "
                    f"output. Only these exact commands are permitted:\n{listing}"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Must be exactly one of the permitted commands.",
                            "enum": allowed_commands,
                        }
                    },
                    "required": ["command"],
                },
                handler=lambda args: run_allowed_command(
                    repo_dir,
                    str(args.get("command", "")),
                    allowed=allowed_commands,
                    timeout=timeout,
                ),
            )
        )

    if pharo is not None:
        tools.extend(pharo_tools(pharo))

    return tools


def pharo_tools(pharo: PharoMcpClient) -> list[AgentTool]:
    return [
        AgentTool(
            name="pharo_eval",
            description=(
                "Evaluate a Smalltalk expression in the live Pharo image and return the printString "
                "of the result. Use this to check that a selector exists, inspect real behaviour, and "
                "verify your code actually works before you propose it. "
                "Example: 'OrderedCollection new addAll: #(1 2 3); yourself'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Smalltalk source to evaluate."}
                },
                "required": ["code"],
            },
            handler=lambda args: pharo_call(pharo, "pharo_eval", {"code": str(args.get("code", ""))}),
        ),
        AgentTool(
            name="pharo_class_source",
            description=(
                "Return the real class definition and the full selector list of a class in the image. "
                "Use this before calling any selector you are not certain exists."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "className": {"type": "string", "description": "Class name, e.g. OrderedCollection."}
                },
                "required": ["className"],
            },
            handler=lambda args: pharo_call(
                pharo, "pharo_class_source", {"className": str(args.get("className", ""))}
            ),
        ),
        AgentTool(
            name="pharo_method_source",
            description="Return the real source code of one method in the live image.",
            parameters={
                "type": "object",
                "properties": {
                    "className": {"type": "string"},
                    "selector": {"type": "string", "description": "Selector, e.g. addAll: or printOn:"},
                },
                "required": ["className", "selector"],
            },
            handler=lambda args: pharo_call(
                pharo,
                "pharo_method_source",
                {
                    "className": str(args.get("className", "")),
                    "selector": str(args.get("selector", "")),
                },
            ),
        ),
    ]


def pharo_call(pharo: PharoMcpClient, name: str, arguments: dict) -> str:
    try:
        text, is_error = pharo.call_tool(name, arguments)
    except PharoUnavailable as exc:
        return f"ERROR: the Pharo image is not reachable: {exc}"
    return f"ERROR: {text}" if is_error else text


def read_repo_file(repo_dir: Path, relative: str) -> str:
    path = safe_path(repo_dir, relative)
    if path is None:
        return f"ERROR: '{relative}' is outside the repository."
    if not path.is_file():
        return f"ERROR: '{relative}' does not exist."
    content = read_text(path, limit=120_000)
    if not content:
        return f"ERROR: '{relative}' is empty or not a text file."
    return content


def list_repo_files(repo_dir: Path, pattern: str) -> str:
    pattern = pattern.strip() or "*"
    try:
        matches = sorted(
            str(path.relative_to(repo_dir))
            for path in repo_dir.glob(pattern)
            if path.is_file() and ".git" not in path.parts
        )
    except (ValueError, NotImplementedError) as exc:
        return f"ERROR: invalid pattern '{pattern}': {exc}"

    if not matches:
        return f"No files matched '{pattern}'."
    shown = matches[:MAX_LISTED_FILES]
    footer = f"\n[...{len(matches) - len(shown)} more matches...]" if len(matches) > len(shown) else ""
    return "\n".join(shown) + footer


def run_allowed_command(repo_dir: Path, command: str, *, allowed: list[str], timeout: int) -> str:
    command = command.strip()
    if command not in allowed:
        permitted = "\n".join(f"- {item}" for item in allowed)
        return f"ERROR: '{command}' is not a permitted command. Permitted:\n{permitted}"
    result = run_shell(command, cwd=repo_dir, check=False, timeout=timeout)
    status = "exit 0" if result.returncode == 0 else f"exit {result.returncode}"
    return f"$ {command}\n[{status}]\n{result.combined_output}"


def safe_path(repo_dir: Path, relative: str) -> Path | None:
    relative = relative.strip().lstrip("/")
    if not relative:
        return None
    candidate = (repo_dir / relative).resolve()
    try:
        candidate.relative_to(repo_dir.resolve())
    except ValueError:
        return None
    return candidate
