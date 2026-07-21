import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ai_ci_controller.cli import (
    build_parser,
    build_run_context,
    collect_validation,
    config_from_args,
    ignore_agent_artifacts,
    wants_pharo,
)
from ai_ci_controller.skills import SkillSelection, load_skills, select_skills


VALID_CLASS = """\
Class {
	#name : 'Demo',
	#superclass : 'Object',
	#package : 'Demo-Core'
}

{ #category : 'accessing' }
Demo >> count [

	^ 0
]
"""

BROKEN_CLASS = VALID_CLASS.replace("Demo >> count [", "Wrong >> count [")

PHARO_SKILL = """\
---
name: pharo
description: Pharo rules
when: ["**/*.class.st"]
tools: [pharo_eval]
validate: ["echo running-pharo-tests"]
---

Check selectors against the live image.
"""


@pytest.fixture
def fake_ollama():
    replies: list[str] = ["Briefing: Demo has one selector, count."]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            body = json.dumps({"message": {"role": "assistant", "content": replies[0]}}).encode()
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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    package = tmp_path / "src" / "Demo-Core"
    package.mkdir(parents=True)
    (package / "Demo.class.st").write_text(VALID_CLASS, encoding="utf-8")
    skills = tmp_path / ".ai" / "skills"
    skills.mkdir(parents=True)
    (skills / "pharo.md").write_text(PHARO_SKILL, encoding="utf-8")
    return tmp_path


def make_config(ollama_url: str, work_root: Path, **overrides):
    argv = [
        "review-pr",
        "--pr",
        "1",
        "--repo",
        "owner/repo",
        "--model",
        "test-model",
        "--ollama-base-url",
        ollama_url,
        "--work-root",
        str(work_root),
    ]
    for key, value in overrides.items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    return config_from_args(build_parser().parse_args(argv))


def test_run_context_assembles_skills_map_and_investigation(fake_ollama, repo: Path, tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    config = make_config(fake_ollama, tmp_path / "work")

    context = build_run_context(
        config,
        repo,
        artifacts_dir=artifacts,
        model="test-model",
        goal="understand the repo",
        title="Add counting",
        body="We need counting.",
        diff_text="diff --git a/src/Demo-Core/Demo.class.st b/src/Demo-Core/Demo.class.st\n+x\n",
    )

    assert context.skills.summary() == "pharo"
    assert "Check selectors against the live image." in context.skills_text
    assert "class Demo < Object" in context.repo_map
    assert "Briefing: Demo has one selector" in context.investigation
    assert context.validation_commands == ["echo running-pharo-tests"]


def test_run_context_writes_artifacts(fake_ollama, repo: Path, tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    config = make_config(fake_ollama, tmp_path / "work")

    build_run_context(
        config,
        repo,
        artifacts_dir=artifacts,
        model="test-model",
        goal="understand the repo",
        title="t",
        body="b",
        diff_text="",
    )

    written = {path.name for path in artifacts.iterdir()}
    assert {"repo-map.md", "skills.md", "investigation.md"} <= written


def test_issue_mode_with_no_diff_still_matches_repo_skills(fake_ollama, repo: Path, tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    config = make_config(fake_ollama, tmp_path / "work")

    context = build_run_context(
        config,
        repo,
        artifacts_dir=artifacts,
        model="test-model",
        goal="implement the issue",
        title="t",
        body="b",
        diff_text="",
    )

    assert context.skills.summary() == "pharo"


def test_agent_can_be_disabled(fake_ollama, repo: Path, tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    argv = [
        "review-pr", "--pr", "1", "--repo", "owner/repo", "--model", "m",
        "--ollama-base-url", fake_ollama, "--work-root", str(tmp_path / "work"), "--no-agent",
    ]
    config = config_from_args(build_parser().parse_args(argv))

    context = build_run_context(
        config,
        repo,
        artifacts_dir=artifacts,
        model="m",
        goal="g",
        title="t",
        body="b",
        diff_text="",
    )

    assert context.investigation == ""
    assert context.repo_map


def test_validation_fails_on_broken_tonel(repo: Path):
    (repo / "src" / "Demo-Core" / "Demo.class.st").write_text(BROKEN_CLASS, encoding="utf-8")
    diff = "diff --git a/src/Demo-Core/Demo.class.st b/src/Demo-Core/Demo.class.st\n+x\n"

    results = collect_validation(repo, commands=[], diff_text=diff, timeout=30)

    assert len(results) == 1
    assert results[0].name == "tonel syntax check"
    assert not results[0].passed
    assert "does not match class 'Demo'" in results[0].output


def test_validation_passes_on_valid_tonel(repo: Path):
    diff = "diff --git a/src/Demo-Core/Demo.class.st b/src/Demo-Core/Demo.class.st\n+x\n"

    results = collect_validation(repo, commands=[], diff_text=diff, timeout=30)

    assert results[0].passed


def test_no_tonel_check_without_st_changes(repo: Path):
    diff = "diff --git a/README.md b/README.md\n+x\n"

    assert collect_validation(repo, commands=[], diff_text=diff, timeout=30) == []


def test_wants_pharo_detects_class_files(repo: Path, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert wants_pharo(repo, SkillSelection(skills=[]))
    assert not wants_pharo(empty, SkillSelection(skills=[]))
    assert wants_pharo(empty, select_skills(load_skills(repo), changed_files=["a.class.st"]))


def test_agent_artifacts_are_git_excluded(tmp_path: Path):
    (tmp_path / ".git" / "info").mkdir(parents=True)

    ignore_agent_artifacts(tmp_path)
    ignore_agent_artifacts(tmp_path)

    content = (tmp_path / ".git" / "info" / "exclude").read_text()
    assert content.count(".aider*") == 1
