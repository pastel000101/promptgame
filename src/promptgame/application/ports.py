"""application이 쓰는 외부 연결 인터페이스. 구현은 infrastructure가 제공한다."""

from __future__ import annotations

from typing import Protocol


class LlmError(Exception):
    """LLM 서버 호출 실패. kind는 timeout / connection / http."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class LlmClient(Protocol):
    model: str

    def chat(self, messages: list[dict], schema: dict) -> str:
        """메시지를 보내고 응답 본문 문자열을 돌려준다. 실패하면 LlmError."""

    def preload(self) -> None:
        """모델을 미리 적재한다. 실패는 무시해도 된다."""


class TurnLog(Protocol):
    path: str | None

    def write(self, record: dict) -> None:
        """기록 한 줄을 남긴다. 실패해도 예외를 밖으로 내지 않는다."""
