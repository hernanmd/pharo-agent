import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_ci_controller.selfcheck import Check, binary_check, model_checks, ollama_reachable, render_checks


@pytest.fixture
def ollama():
    payload = {
        "models": [
            {"name": "qwen2.5-coder:7b"},
            {"name": "llama3.1:8b"},
        ]
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_binary_check_finds_a_real_binary():
    check = binary_check("python", required=True)

    assert check.ok
    assert not check.blocking


def test_missing_required_binary_blocks():
    check = binary_check("definitely-not-a-real-binary-xyz", required=True)

    assert check.status == "fail"
    assert check.blocking


def test_missing_optional_binary_only_warns():
    check = binary_check("definitely-not-a-real-binary-xyz", required=False)

    assert check.status == "warn"
    assert not check.blocking


def test_ollama_reachable_reports_model_count(ollama):
    tags, check = ollama_reachable(ollama)

    assert check.ok
    assert "2 model(s)" in check.detail
    assert len(tags["models"]) == 2


def test_ollama_unreachable_blocks():
    tags, check = ollama_reachable("http://127.0.0.1:1")

    assert tags is None
    assert check.blocking


def test_model_checks_detect_a_pulled_model(ollama):
    tags, _ = ollama_reachable(ollama)

    checks = model_checks(tags, ["qwen2.5-coder:7b"])

    assert len(checks) == 1
    assert checks[0].ok


def test_model_checks_match_on_the_bare_name(ollama):
    tags, _ = ollama_reachable(ollama)

    checks = model_checks(tags, ["qwen2.5-coder"])

    assert checks[0].ok


def test_model_checks_flag_a_missing_model(ollama):
    tags, _ = ollama_reachable(ollama)

    checks = model_checks(tags, ["mistral:7b"])

    assert checks[0].blocking
    assert "ollama pull mistral:7b" in checks[0].detail


def test_model_checks_deduplicate(ollama):
    tags, _ = ollama_reachable(ollama)

    checks = model_checks(tags, ["qwen2.5-coder:7b", "qwen2.5-coder:7b", ""])

    assert len(checks) == 1


def test_model_checks_warn_when_nothing_was_configured(ollama):
    tags, _ = ollama_reachable(ollama)

    checks = model_checks(tags, [])

    assert checks[0].status == "warn"
    assert not checks[0].blocking


def test_render_reports_all_clear():
    checks = [Check(name="a", status="ok", detail="fine", required=True)]

    assert "All required checks passed." in render_checks(checks)


def test_render_lists_blocking_failures():
    checks = [
        Check(name="ollama", status="fail", detail="not answering", required=True),
        Check(name="pharo", status="warn", detail="not configured", required=False),
    ]

    rendered = render_checks(checks)

    assert "1 required check(s) failed" in rendered
    assert "cannot do the work yet" in rendered
    assert "1 optional check(s) warned" in rendered


def test_render_escapes_pipes_so_the_table_survives():
    checks = [Check(name="x", status="ok", detail="a | b", required=True)]

    assert "a \\| b" in render_checks(checks)


def test_warnings_never_block():
    checks = [Check(name="pharo", status="warn", detail="not set", required=False)]

    assert not any(check.blocking for check in checks)
    assert "All required checks passed." in render_checks(checks)
