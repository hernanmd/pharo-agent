from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class OllamaClient:
    base_url: str
    model: str
    temperature: float = 0.1
    timeout_seconds: int = 600

    def chat(self, messages: list[dict[str, str]], *, json_format: bool = False) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }
        if json_format:
            payload["format"] = "json"

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url("/api/chat"),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. "
                "Start Ollama on the CI machine and set OLLAMA_BASE_URL if needed."
            ) from exc

        message = response_payload.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Ollama returned an unexpected response: {response_payload!r}")
        return content

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

