from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOAD_SCRIPT = ".ai/pharo-load.st"
DEFAULT_BOOT_TIMEOUT = 240
DEFAULT_CALL_TIMEOUT = 120
MCP_PROTOCOL_VERSION = "2024-11-05"


class PharoUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PharoConfig:
    vm: str | None
    base_image: str | None
    baseline: str | None
    load_script: str
    boot_timeout: int
    call_timeout: int

    @property
    def enabled(self) -> bool:
        return bool(self.vm and self.base_image)

    @classmethod
    def from_environment(cls) -> PharoConfig:
        return cls(
            vm=os.environ.get("PHARO_VM") or shutil.which("pharo"),
            base_image=os.environ.get("PHARO_IMAGE"),
            baseline=os.environ.get("PHARO_BASELINE"),
            load_script=os.environ.get("PHARO_LOAD_SCRIPT", DEFAULT_LOAD_SCRIPT),
            boot_timeout=int(os.environ.get("PHARO_BOOT_TIMEOUT", str(DEFAULT_BOOT_TIMEOUT))),
            call_timeout=int(os.environ.get("PHARO_CALL_TIMEOUT", str(DEFAULT_CALL_TIMEOUT))),
        )


@dataclass
class PharoImage:
    config: PharoConfig
    repo_dir: Path
    work_dir: Path
    port: int = 0
    process: subprocess.Popen | None = None
    log_path: Path | None = None

    def __enter__(self) -> PharoImage:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def start(self) -> None:
        if not self.config.enabled:
            raise PharoUnavailable(
                "Pharo is not configured. Set PHARO_VM and PHARO_IMAGE on the runner "
                "to give the model a live image."
            )

        base_image = Path(self.config.base_image or "")
        if not base_image.is_file():
            raise PharoUnavailable(f"PHARO_IMAGE does not exist: {base_image}")

        self.work_dir.mkdir(parents=True, exist_ok=True)
        run_image = self.work_dir / "run.image"
        copy_image(base_image, run_image)

        self.port = free_port()
        script_path = self.work_dir / "boot.st"
        script_path.write_text(self.boot_script(), encoding="utf-8")

        self.log_path = self.work_dir / "pharo.log"
        log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                str(self.config.vm),
                "--headless",
                str(run_image),
                "st",
                "--no-quit",
                str(script_path),
            ],
            cwd=str(self.repo_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PHARO_MCP_PORT": str(self.port)},
        )
        self.wait_until_ready()

    def boot_script(self) -> str:
        custom = self.repo_dir / self.config.load_script
        if custom.is_file():
            load = custom.read_text(encoding="utf-8").strip()
        elif self.config.baseline:
            source = (self.repo_dir / "src").as_posix()
            load = (
                "Metacello new\n"
                f"    baseline: '{self.config.baseline}';\n"
                f"    repository: 'tonel://{source}';\n"
                "    onConflict: [ :ex | ex useIncoming ];\n"
                "    onWarning: [ :ex | ex resume ];\n"
                "    load."
            )
        else:
            load = '"No project load step configured."'

        return (
            f"{load}\n\n"
            "[ PharoMcpServer startOn: "
            f"{self.port} ] on: Error do: [ :ex |\n"
            "    Transcript show: '[boot] MCP start failed: ', ex messageText printString; cr ].\n"
        )

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.config.boot_timeout
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise PharoUnavailable(
                    f"Pharo image exited during boot (code {self.process.returncode}).\n"
                    f"{self.tail_log()}"
                )
            try:
                with urllib.request.urlopen(self.endpoint, timeout=5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(2)

        self.stop()
        raise PharoUnavailable(
            f"Pharo MCP server did not become ready within {self.config.boot_timeout}s.\n"
            f"{self.tail_log()}"
        )

    def tail_log(self, *, lines: int = 40) -> str:
        if not self.log_path or not self.log_path.is_file():
            return "(no Pharo log captured)"
        content = self.log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(content[-lines:])

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None

    def client(self) -> PharoMcpClient:
        return PharoMcpClient(endpoint=self.endpoint, timeout=self.config.call_timeout)


@dataclass
class PharoMcpClient:
    endpoint: str
    timeout: int = DEFAULT_CALL_TIMEOUT
    _next_id: int = 1

    def initialize(self) -> dict:
        return self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-ci-controller", "version": "0.2.0"},
            },
        )

    def list_tools(self) -> list[dict]:
        result = self.request("tools/list", {})
        return result.get("tools") or []

    def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        blocks = result.get("content") or []
        text = "\n".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return text, bool(result.get("isError"))

    def evaluate(self, code: str) -> tuple[str, bool]:
        return self.call_tool("pharo_eval", {"code": code})

    def request(self, method: str, params: dict) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise PharoUnavailable(f"Pharo MCP call '{method}' failed: {exc}") from exc

        if not body.strip():
            return {}
        envelope = json.loads(body)
        if "error" in envelope and envelope["error"]:
            error = envelope["error"]
            raise PharoUnavailable(
                f"Pharo MCP call '{method}' returned an error: "
                f"{error.get('message', error)}"
            )
        return envelope.get("result") or {}


def copy_image(base_image: Path, destination: Path) -> None:
    shutil.copyfile(base_image, destination)
    for suffix in (".changes",):
        companion = base_image.with_suffix(suffix)
        if companion.is_file():
            shutil.copyfile(companion, destination.with_suffix(suffix))
    for name in ("PharoV60.sources", "Pharo12.sources", "Pharo13.sources"):
        sources = base_image.parent / name
        if sources.is_file() and not (destination.parent / name).exists():
            shutil.copyfile(sources, destination.parent / name)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
