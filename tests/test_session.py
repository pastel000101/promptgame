"""세션: 턴 진행, 중복 입력 차단, 상태 보존, 다시 시작, 기록 (대역 클라이언트)."""

import threading
import time

from fakes import FakeClient, MemoryLog, move_spec, reply, step, target
from promptgame.application.interpreter import Interpreter
from promptgame.application.ports import LlmError
from promptgame.application.session import BUSY_NOTICE, ENDED_NOTICE, GameSession


class ManualSpawn:
    """해석 작업을 바로 돌리지 않고 모아 두었다가 run()에서 실행한다."""

    def __init__(self):
        self.jobs = []

    def __call__(self, fn):
        self.jobs.append(fn)

    def run(self):
        jobs, self.jobs = self.jobs, []
        for fn in jobs:
            fn()


def make_session(*replies, seed=7):
    log = MemoryLog()
    spawn = ManualSpawn()
    session = GameSession(Interpreter(FakeClient(*replies)), log, lambda: seed, spawn=spawn, model="fake")
    return session, log, spawn


def finish(session, spawn):
    spawn.run()
    assert session.poll()


def test_turn_runs_and_logs_everything():
    session, log, spawn = make_session(reply(step("move", move=move_spec(direction="S", cells=2))))
    assert session.submit("남쪽으로 두 칸 가") == "started"
    assert session.busy and session.elapsed() is not None
    finish(session, spawn)
    assert session.state.player.pos == (2, 4) and session.state.turn == 2
    assert session.plan_line == "계획 2/4 AP: ① 이동 남쪽으로 2칸 (2) · 남은 AP 2 미사용"
    start, turn = log.records
    assert start["type"] == "game_start" and start["seed"] == 7
    for key in ("sentence", "source", "failure", "attempts", "elapsed_ms", "summary", "plan", "validation", "events",
                "state_before", "state_after", "seed", "raw"):
        assert key in turn
    assert turn["source"] == "llm" and turn["validation"]["accepted"]
    assert any(e["type"] == "move" for e in turn["events"])


def test_duplicate_submit_while_busy_is_dropped():
    session, log, spawn = make_session(reply(step("attack", target=target())), reply(step("wait")))
    session.state.player.pos = (6, 2)
    assert session.submit("고블린을 베어") == "started"
    assert session.submit("고블린을 베어") == "busy"
    assert session.notice == BUSY_NOTICE
    finish(session, spawn)
    assert len([r for r in log.records if r["type"] == "turn"]) == 1
    assert session.state.turn == 2


def test_clarify_and_server_failure_keep_state():
    session, log, spawn = make_session(reply(clarify="ambiguous"), LlmError("timeout"))
    before = session.state.copy()
    rng_state = session.rng.getstate()
    session.submit("음…")
    finish(session, spawn)
    assert session.plan_line == "무엇을 어떻게 할지 더 적어 주세요"
    session.submit("고블린에게 가")
    finish(session, spawn)
    assert session.plan_line.startswith("AI 응답 시간이 초과됐어요")
    assert session.state == before and session.rng.getstate() == rng_state
    assert [r["source"] for r in log.records[1:]] == ["llm", "none"]


def test_fallback_turn_is_marked():
    session, log, spawn = make_session(LlmError("connection"))
    session.submit("방어")
    finish(session, spawn)
    assert session.plan_line.startswith("[폴백] 계획 1/4 AP")
    assert log.records[-1]["source"] == "fallback"


def test_restart_resets_everything_and_discards_pending():
    session, log, spawn = make_session(reply(step("use_item", item="potion")), reply(step("wait")))
    session.state.whirlwind_cooldown = 2
    session.state.enemy("goblin").statuses["burning"] = 2
    session.submit("물약 마셔")
    assert session.submit("다시 시작") == "restart"
    spawn.run()
    assert not session.poll()  # 이전 판의 결과는 버린다
    assert session.state.potions == 1 and session.state.whirlwind_cooldown == 0
    assert session.state.enemy("goblin").statuses == {}
    assert [r["type"] for r in log.records] == ["game_start", "game_start"]


def test_after_game_end_only_restart_is_accepted():
    session, log, spawn = make_session()
    session.state.outcome = "win"
    assert session.submit("고블린을 베어") == "ended" and session.notice == ENDED_NOTICE
    assert session.submit("다시 시작") == "restart" and session.state.outcome is None


def test_interpreter_exception_releases_busy():
    class Boom:
        def interpret(self, sentence, state):
            raise RuntimeError("boom")

    log = MemoryLog()
    spawn = ManualSpawn()
    session = GameSession(Boom(), log, lambda: 1, spawn=spawn)
    session.submit("대기")
    spawn.run()
    session.poll()
    assert not session.busy and log.records[-1]["failure"] == "error"


def test_real_thread_keeps_state_changes_on_poll_thread():
    class Slow:
        def interpret(self, sentence, state):
            time.sleep(0.05)
            return Interpreter(FakeClient(reply(step("guard")))).interpret(sentence, state)

    session = GameSession(Slow(), MemoryLog(), lambda: 3)
    session.submit("방어")
    assert session.state.turn == 1  # 해석 중에는 상태가 바뀌지 않는다
    deadline = time.time() + 2
    while not session.poll():
        assert time.time() < deadline
        time.sleep(0.01)
    assert session.state.turn == 2 and threading.current_thread() is threading.main_thread()
