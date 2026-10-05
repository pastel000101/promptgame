"""턴 진행과 스레드 경계 (설계서 §3 AI 대기 중).

해석은 백그라운드 스레드에서 상태 사본으로만 하고, 상태 변경·판정·기록은 poll()을 부르는 화면 루프 스레드에서만 한다.
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
from promptgame.domain.resolve import play_turn
from promptgame.domain.state import GameState, new_game

RESTART = "다시 시작"
BUSY_NOTICE = "이전 명령을 처리하는 중이에요"
ENDED_NOTICE = "판이 끝났어요. '다시 시작'을 입력하세요"
HISTORY_LIMIT = 200


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
    ):
        self.interpreter = interpreter
        self.log = log
        self.new_seed = new_seed
        self.spawn = spawn
        self.model = model
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
        self.plan_line = ""
        self.notice = ""
        self.history.clear()
        self.history.append(f"새 판 시작 · 시드 {self.seed}. 한 턴의 행동을 문장으로 적고 Enter를 누르세요")
        self.log.write({"type": "game_start", "game": self.game_id, "seed": self.seed, "model": self.model,
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "state": self.state.to_dict()})

    @property
    def busy(self) -> bool:
        return self._pending is not None

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
        """끝난 해석을 적용한다. 화면 루프 스레드에서 부른다."""
        applied = False
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
            result = play_turn(self.state, interp.plan, self.rng)
            self.plan_line = ("[폴백] " if interp.source == "fallback" else "") + result.validation.line()
            self.history.append(self.plan_line)
            self.history.extend(e.text for e in result.events)
            record["validation"] = result.validation.to_dict()
            record["events"] = [{"text": e.text, **e.data} for e in result.events]
        else:
            self.plan_line = interp.message or ""
            self.history.append(self.plan_line)
        record["state_after"] = self.state.to_dict()
        record["outcome"] = self.state.outcome
        self.log.write(record)
