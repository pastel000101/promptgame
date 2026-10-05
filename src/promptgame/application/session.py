"""턴 진행과 스레드 경계 (설계서 §3 AI 대기 중).

해석은 백그라운드 스레드에서 상태 사본으로만 하고, 상태 변경·판정·기록은 poll()을 부르는 화면 루프 스레드에서만 한다.

수락된 계획은 바로 실행하지 않는다. 먼저 계획 줄로 보여 주고, 화면이 그 계획을 그린 뒤(mark_displayed)
PLAN_DISPLAY_SECONDS가 지나면 같은 검증 결과로 자동 실행한다. 표시 단계에서는 다시 해석하거나 주사위를 굴리지 않는다.
"""

from __future__ import annotations

import queue
import random
import threading
import time
from collections import deque
from collections.abc import Callable

from promptgame.application.interpreter import Interpretation, Interpreter
from promptgame.application.ports import TurnLog
from promptgame.domain.plan import Plan
from promptgame.domain.resolve import run_validated
from promptgame.domain.validate import Validation, validate_plan
from promptgame.domain.state import GameState, new_game

RESTART = "다시 시작"
BUSY_NOTICE = "이전 명령을 처리하는 중이에요"
ENDED_NOTICE = "판이 끝났어요. '다시 시작'을 입력하세요"
HISTORY_LIMIT = 200
PLAN_DISPLAY_SECONDS = 1.0


class _Planned:
    """검증을 통과해 화면에 보여 줄 계획. 한 번만 실행된다."""

    def __init__(self, plan: Plan, validation: Validation, record: dict):
        self.plan = plan
        self.validation = validation
        self.record = record
        self.shown_at: float | None = None


def _thread_spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


class GameSession:
    def __init__(
        self,
        interpreter: Interpreter,
        log: TurnLog,
        new_seed: Callable[[], int],
        spawn: Callable[[Callable[[], None]], None] = _thread_spawn,
        model: str = "",
        plan_display_seconds: float = PLAN_DISPLAY_SECONDS,
    ):
        self.interpreter = interpreter
        self.log = log
        self.new_seed = new_seed
        self.spawn = spawn
        self.model = model
        self.plan_display_seconds = plan_display_seconds
        self._planned: _Planned | None = None
        self.history: deque[str] = deque(maxlen=HISTORY_LIMIT)
        self._results: queue.Queue = queue.Queue()
        self._pending: tuple[int, int] | None = None
        self._busy_since: float | None = None
        self._request_no = 0
        self.game_id = 0
        self.plan_line = ""
        self.notice = ""
        self.start_new_game()

    # ---- 판 ----
    def start_new_game(self) -> None:
        self.game_id += 1
        self.seed = self.new_seed()
        self.rng = random.Random(self.seed)
        self.state: GameState = new_game()
        self._pending = None
        self._busy_since = None
        self._planned = None
        self.plan_line = ""
        self.notice = ""
        self.history.clear()
        self.history.append(f"새 판 시작 · 시드 {self.seed}. 한 턴의 행동을 문장으로 적고 Enter를 누르세요")
        self.log.write({"type": "game_start", "game": self.game_id, "seed": self.seed, "model": self.model,
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "state": self.state.to_dict()})

    @property
    def busy(self) -> bool:
        """해석 중이거나 보여 준 계획을 아직 실행하지 않았으면 참. 이때 새 문장은 받지 않는다."""
        return self._pending is not None or self._planned is not None

    @property
    def phase(self) -> str:
        if self._pending is not None:
            return "interpreting"
        if self._planned is not None:
            return "planned"
        return "idle"

    def mark_displayed(self) -> None:
        """화면이 현재 계획 줄을 그린 뒤 부른다. 이때부터 표시 시간을 잰다."""
        if self._planned is not None and self._planned.shown_at is None:
            self._planned.shown_at = time.perf_counter()

    def elapsed(self) -> float | None:
        return None if self._busy_since is None else time.perf_counter() - self._busy_since

    # ---- 입력 ----
    def submit(self, sentence: str) -> str:
        """문장을 받는다. 결과: started / restart / busy / ended / empty."""
        text = sentence.strip()
        if not text:
            return "empty"
        if text == RESTART:
            self.start_new_game()
            return "restart"
        if self.busy:
            self.notice = BUSY_NOTICE
            return "busy"
        if self.state.outcome is not None:
            self.notice = ENDED_NOTICE
            return "ended"
        self._request_no += 1
        token = (self.game_id, self._request_no)
        self._pending = token
        self._busy_since = time.perf_counter()
        self.notice = ""
        self.history.append(f"> {text}")
        snapshot = self.state.copy()

        def work() -> None:
            try:
                interpretation = self.interpreter.interpret(text, snapshot)
            except Exception as exc:  # 해석기 내부 오류가 입력을 영구히 막지 않게 한다
                interpretation = Interpretation(source="none", failure="error", message="해석 중 오류가 났어요", errors=[repr(exc)])
            self._results.put((token, text, interpretation))

        self.spawn(work)
        return "started"

    def poll(self) -> bool:
        """보여 준 계획의 실행 시점이 됐으면 실행하고, 끝난 해석을 적용한다. 화면 루프 스레드에서 부른다."""
        applied = self._execute_if_due()
        while True:
            try:
                token, text, interpretation = self._results.get_nowait()
            except queue.Empty:
                return applied
            if token != self._pending:
                continue  # 다시 시작 전에 보낸 요청의 결과
            self._pending = None
            self._busy_since = None
            self._apply(text, interpretation)
            applied = True

    def _apply(self, text: str, interp: Interpretation) -> None:
        before = self.state.to_dict()
        record = {
            "type": "turn",
            "game": self.game_id,
            "seed": self.seed,
            "turn": self.state.turn,
            "sentence": text,
            "summary": interp.summary,
            **interp.to_dict(),
            "validation": None,
            "events": [],
            "state_before": before,
        }
        if interp.plan is not None:
            validation = validate_plan(self.state, interp.plan)  # 난수를 쓰지 않는다
            self.plan_line = ("[폴백] " if interp.source == "fallback" else "") + validation.line()
            self.history.append(self.plan_line)
            record["validation"] = validation.to_dict()
            if validation.accepted:
                self._planned = _Planned(interp.plan, validation, record)
                return
        else:
            self.plan_line = interp.message or ""
            self.history.append(self.plan_line)
        self._write(record)

    def _execute_if_due(self) -> bool:
        planned = self._planned
        if planned is None or planned.shown_at is None:
            return False
        if time.perf_counter() - planned.shown_at < self.plan_display_seconds:
            return False
        self._planned = None  # 먼저 비워 같은 계획이 두 번 실행되지 않게 한다
        result = run_validated(self.state, planned.plan, planned.validation, self.rng)
        self.history.extend(e.text for e in result.events)
        planned.record["events"] = [{"text": e.text, **e.data} for e in result.events]
        self._write(planned.record)
        return True

    def _write(self, record: dict) -> None:
        record["state_after"] = self.state.to_dict()
        record["outcome"] = self.state.outcome
        self.log.write(record)
