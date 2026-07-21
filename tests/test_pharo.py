import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ai_ci_controller.pharo import PharoConfig, PharoImage, PharoMcpClient, PharoUnavailable


def make_config(**overrides) -> PharoConfig:
    defaults = dict(
        vm="/usr/local/bin/pharo",
        base_image="/images/Pharo.image",
        baseline=None,
        load_script=".ai/pharo-load.st",
        boot_timeout=60,
        call_timeout=30,
    )
    defaults.update(overrides)
    return PharoConfig(**defaults)


@pytest.fixture
def mcp_server():
    state = {"requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or "{}")
            state["requests"].append(payload)

            method = payload.get("method")
            if method == "boom":
                result = {"error": {"code": -32603, "message": "image is on fire"}}
            elif method == "tools/list":
                result = {"result": {"tools": [{"name": "pharo_eval"}, {"name": "pharo_class_source"}]}}
            elif method == "tools/call":
                result = {"result": {"content": [{"type": "text", "text": "42"}], "isError": False}}
            else:
                result = {"result": {"protocolVersion": "2024-11-05"}}

            body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"), **result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/mcp"
    yield state
    server.shutdown()
    server.server_close()


def test_config_is_disabled_without_vm_or_image():
    assert not make_config(vm=None).enabled
    assert not make_config(base_image=None).enabled
    assert make_config().enabled


def test_boot_script_uses_repository_load_script(tmp_path: Path):
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "pharo-load.st").write_text("Metacello new load.", encoding="utf-8")
    image = PharoImage(config=make_config(), repo_dir=tmp_path, work_dir=tmp_path / "w", port=4100)

    script = image.boot_script()

    assert "Metacello new load." in script
    assert "PharoMcpServer startOn: 4100" in script


def test_boot_script_falls_back_to_baseline(tmp_path: Path):
    image = PharoImage(
        config=make_config(baseline="LLMPharoAgent"),
        repo_dir=tmp_path,
        work_dir=tmp_path / "w",
        port=4100,
    )

    script = image.boot_script()

    assert "baseline: 'LLMPharoAgent'" in script
    assert f"repository: 'tonel://{(tmp_path / 'src').as_posix()}'" in script
    assert "PharoMcpServer startOn: 4100" in script


def test_boot_script_without_baseline_still_starts_the_server(tmp_path: Path):
    image = PharoImage(config=make_config(), repo_dir=tmp_path, work_dir=tmp_path / "w", port=4100)

    script = image.boot_script()

    assert "No project load step configured" in script
    assert "PharoMcpServer startOn: 4100" in script


def test_start_rejects_a_missing_image(tmp_path: Path):
    image = PharoImage(
        config=make_config(base_image=str(tmp_path / "nope.image")),
        repo_dir=tmp_path,
        work_dir=tmp_path / "w",
    )

    with pytest.raises(PharoUnavailable, match="PHARO_IMAGE does not exist"):
        image.start()


def test_start_rejects_unconfigured_pharo(tmp_path: Path):
    image = PharoImage(config=make_config(vm=None), repo_dir=tmp_path, work_dir=tmp_path / "w")

    with pytest.raises(PharoUnavailable, match="Pharo is not configured"):
        image.start()


def test_client_initialize_and_list_tools(mcp_server):
    client = PharoMcpClient(endpoint=mcp_server["url"])

    client.initialize()
    tools = client.list_tools()

    assert [tool["name"] for tool in tools] == ["pharo_eval", "pharo_class_source"]
    assert mcp_server["requests"][0]["method"] == "initialize"


def test_client_evaluate_returns_text(mcp_server):
    client = PharoMcpClient(endpoint=mcp_server["url"])

    text, is_error = client.evaluate("6 * 7")

    assert text == "42"
    assert not is_error
    call = mcp_server["requests"][-1]
    assert call["params"]["name"] == "pharo_eval"
    assert call["params"]["arguments"] == {"code": "6 * 7"}


def test_client_raises_on_jsonrpc_error(mcp_server):
    client = PharoMcpClient(endpoint=mcp_server["url"])

    with pytest.raises(PharoUnavailable, match="image is on fire"):
        client.request("boom", {})


def test_client_raises_when_endpoint_is_dead():
    client = PharoMcpClient(endpoint="http://127.0.0.1:1/mcp", timeout=2)

    with pytest.raises(PharoUnavailable):
        client.initialize()


def test_request_ids_increment(mcp_server):
    client = PharoMcpClient(endpoint=mcp_server["url"])

    client.initialize()
    client.list_tools()

    assert [item["id"] for item in mcp_server["requests"]] == [1, 2]
