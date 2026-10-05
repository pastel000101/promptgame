"""문장 해석: LLM 호출, 형식 검증, 재시도 1회, 폴백 (설계서 §2.3, §3)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from promptgame.application import fallback
from promptgame.application.intent import RESPONSE_SCHEMA, Clarify, FormatError, parse_response
from promptgame.application.ports import LlmClient, LlmError
from promptgame.application.prompt import build_messages, state_summary
from promptgame.domain.plan import Plan
from promptgame.domain.state import GameState

CLARIFY_MESSAGES = {
    "ambiguous": "무엇을 어떻게 할지 더 적어 주세요",
    "unrelated": "전투 행동으로 이해하지 못했어요",
    "too_many_steps": "한 턴에는 3단계까지만 적어 주세요",
}
SERVER_MESSAGES = {
    "timeout": "AI 응답 시간이 초과됐어요",
    "connection": "AI 서버에 연결하지 못했어요",
    "http": "AI 서버가 오류를 돌려줬어요",
}


@dataclass
class Interpretation:
    source: str  # llm / fallback / none
    plan: Plan | None = None
    clarify: str | None = None
    failure: str | None = None  # format / timeout / connection / http
    attempts: int = 0
    elapsed_ms: float = 0.0
    message: str | None = None
    summary: str = ""
    raw: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "plan": self.plan.to_dict() if self.plan else None,
            "clarify": self.clarify,
            "failure": self.failure,
            "attempts": self.attempts,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "message": self.message,
            "raw": self.raw,
            "errors": self.errors,
        }


class Interpreter:
    def __init__(self, client: LlmClient):
        self.client = client

    def interpret(self, sentence: str, state: GameState) -> Interpretation:
        summary = state_summary(state)
        result = Interpretation(source="none", summary=summary)
        started = time.perf_counter()
        try:
            for attempt in (1, 2):
                result.attempts = attempt
                text = self.client.chat(build_messages(summary, sentence, retry=attempt == 2), RESPONSE_SCHEMA)
                result.raw.append(text)
                try:
                    parsed = parse_response(text)
                except FormatError as exc:
                    result.errors.append(str(exc))
                    continue
                result.source = "llm"
                if isinstance(parsed, Clarify):
                    result.clarify = parsed.reason
                    result.message = CLARIFY_MESSAGES[parsed.reason]
                else:
                    result.plan = parsed
                return self._finish(result, started)
            result.failure = "format"
            reason = "이해하지 못했어요"
        except LlmError as exc:
            result.failure = exc.kind
            result.errors.append(str(exc))
            reason = SERVER_MESSAGES.get(exc.kind, "AI 호출에 실패했어요")
        self._finish(result, started)
        plan, note = fallback.match(sentence, state)
        if plan is not None:
            result.source = "fallback"
            result.plan = plan
            return result
        result.message = f"{reason}. {note or fallback.GUIDE}"
        return result

    @staticmethod
    def _finish(result: Interpretation, started: float) -> Interpretation:
        result.elapsed_ms = (time.perf_counter() - started) * 1000
        return result
