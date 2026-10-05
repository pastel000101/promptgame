"""Ollama HTTP 클라이언트 (/api/chat, JSON 스키마 강제, think false, temperature 0)."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from promptgame.application.ports import LlmError

KEEP_ALIVE = "30m"


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise LlmError("http", f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise LlmError("timeout", str(exc.reason)) from exc
            raise LlmError("connection", str(exc.reason)) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LlmError("timeout", str(exc)) from exc
        except (ConnectionError, OSError) as exc:
            raise LlmError("connection", str(exc)) from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LlmError("http", "응답 본문이 JSON이 아님") from exc

    def chat(self, messages: list[dict], schema: dict) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0},
        }
        reply = self._post("/api/chat", body, self.timeout)
        message = reply.get("message") if isinstance(reply, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LlmError("http", "응답에 message.content가 없음")
        return message["content"]

    def preload(self) -> None:
        """모델을 메모리에 올린다. 첫 적재가 길 수 있어 시간 제한을 넉넉히 둔다."""
        try:
            self._post("/api/generate", {"model": self.model, "keep_alive": KEEP_ALIVE}, max(self.timeout, 120))
        except LlmError:
            pass
