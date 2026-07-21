import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ai_ci_controller.agent import build_tools, run_agent, safe_path
from ai_ci_controller.ollama import OllamaClient
from ai_ci_controller.pharo import PharoMcpClient


class RecordingServer:
    def __init__(self, handler_factory):
        self.requests: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def json_handler(respond):
    def factory(owner):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or "{}")
                owner.requests.append(payload)
                body = json.dumps(respond(owner, payload)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        return Handler

    return factory


def tool_call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


@pytest.fixture
def fake_ollama():
    scripted: list[dict] = []

    def respond(owner, _payload):
        message = scripted[min(len(owner.requests) - 1, len(scripted) - 1)]
        return {"message": message}

    server = RecordingServer(json_handler(respond))
    server.scripted = scripted
    yield server
    server.shutdown()


@pytest.fixture
def fake_pharo():
    def respond(_owner, payload):
        method = payload.get("method")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05"}}
        if method == "tools/call":
            params = payload.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "pharo_eval" and "bogusSelector" in arguments.get("code", ""):
                return {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "content": [{"type": "text", "text": "MessageNotUnderstood: bogusSelector"}],
                        "isError": True,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {"content": [{"type": "text", "text": f"ok:{name}:{sorted(arguments)}"}]},
            }
        return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {}}

    server = RecordingServer(json_handler(respond))
    yield server
    server.shutdown()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Demo.class.st").write_text("Class { #name : 'Demo' }\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    return tmp_path


def test_agent_runs_tools_then_answers(fake_ollama, fake_pharo, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("pharo_class_source", {"className": "OrderedCollection"})]},
            {"role": "assistant", "content": "", "tool_calls": [tool_call("read_file", {"path": "src/Demo.class.st"})]},
            {"role": "assistant", "content": "Briefing: Demo is a class."},
        ]
    )
    pharo = PharoMcpClient(endpoint=f"{fake_pharo.base_url}/mcp")
    tools = build_tools(repo_dir=repo, pharo=pharo, allowed_commands=[], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert result.final_text == "Briefing: Demo is a class."
    assert result.iterations == 3
    assert result.tool_names() == ["pharo_class_source", "read_file"]
    assert "ok:pharo_class_source" in result.calls[0].output
    assert "#name : 'Demo'" in result.calls[1].output
    assert not result.stopped_early


def test_tool_results_are_fed_back_to_the_model(fake_ollama, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("read_file", {"path": "README.md"})]},
            {"role": "assistant", "content": "done"},
        ]
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=[], timeout=10)

    run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    final_messages = fake_ollama.requests[-1]["messages"]
    tool_messages = [message for message in final_messages if message["role"] == "tool"]
    assert tool_messages and tool_messages[0]["content"] == "hello\n"


def test_pharo_errors_are_surfaced_not_swallowed(fake_ollama, fake_pharo, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("pharo_eval", {"code": "1 bogusSelector"})]},
            {"role": "assistant", "content": "that selector does not exist"},
        ]
    )
    pharo = PharoMcpClient(endpoint=f"{fake_pharo.base_url}/mcp")
    tools = build_tools(repo_dir=repo, pharo=pharo, allowed_commands=[], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert "ERROR: MessageNotUnderstood" in result.calls[0].output


def test_iteration_limit_forces_an_answer(fake_ollama, repo: Path):
    fake_ollama.scripted.append(
        {"role": "assistant", "content": "", "tool_calls": [tool_call("read_file", {"path": "README.md"})]}
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=[], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=2,
    )

    assert result.stopped_early
    assert result.iterations == 2
    assert fake_ollama.requests[-1]["messages"][-1]["role"] == "user"
    assert "tool-call limit" in fake_ollama.requests[-1]["messages"][-1]["content"]


def test_unknown_tool_is_reported_to_the_model(fake_ollama, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("delete_everything", {})]},
            {"role": "assistant", "content": "understood"},
        ]
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=[], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert "unknown tool 'delete_everything'" in result.calls[0].output


def test_run_check_rejects_commands_outside_the_allowlist(fake_ollama, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("run_check", {"command": "rm -rf /"})]},
            {"role": "assistant", "content": "blocked"},
        ]
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=["echo hello"], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert "is not a permitted command" in result.calls[0].output


def test_run_check_executes_allowlisted_commands(fake_ollama, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call("run_check", {"command": "echo hello"})]},
            {"role": "assistant", "content": "ran"},
        ]
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=["echo hello"], timeout=30)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert "[exit 0]" in result.calls[0].output
    assert "hello" in result.calls[0].output


def test_run_check_is_absent_when_nothing_is_allowlisted(repo: Path):
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=[], timeout=10)

    assert "run_check" not in {tool.name for tool in tools}


def test_read_file_cannot_escape_the_repository(repo: Path):
    assert safe_path(repo, "../../etc/passwd") is None
    assert safe_path(repo, "src/../../../etc/passwd") is None
    assert safe_path(repo, "src/Demo.class.st") is not None


def test_absolute_paths_are_reinterpreted_as_repository_relative(repo: Path):
    resolved = safe_path(repo, "/etc/passwd")

    assert resolved is not None
    assert resolved == (repo / "etc" / "passwd").resolve()


def test_string_encoded_arguments_are_parsed(fake_ollama, repo: Path):
    fake_ollama.scripted.extend(
        [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": json.dumps({"path": "README.md"})}}]},
            {"role": "assistant", "content": "done"},
        ]
    )
    tools = build_tools(repo_dir=repo, pharo=None, allowed_commands=[], timeout=10)

    result = run_agent(
        OllamaClient(fake_ollama.base_url, "test-model"),
        system_prompt="explore",
        user_prompt="go",
        tools=tools,
        max_iterations=5,
    )

    assert result.calls[0].output == "hello\n"
