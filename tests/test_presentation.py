"""화면·입력: SDL 이벤트 순서 재현과 창 없는 그리기 (dummy 드라이버). 자산이 없을 때의 대체 도형도 확인한다."""

import threading

import pygame
import pytest

from fakes import FakeClient, MemoryLog, move_spec, reply, step, target
from promptgame.application.interpreter import Interpreter
from promptgame.application.session import GameSession
from promptgame.presentation import assets as assets_mod
from promptgame.presentation import render
from promptgame.presentation.app import App
from promptgame.presentation.text_input import TextInput


def editing(text):
    return pygame.event.Event(pygame.TEXTEDITING, text=text, start=0, length=len(text))


def committed(text):
    return pygame.event.Event(pygame.TEXTINPUT, text=text)


def key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="")


def feed(ti, events):
    out = []
    for e in events:
        r = ti.handle(e)
        if r is not None:
            out.append(r)
    return out


# ---- 한글 조합·삭제·제출 ----

def test_composition_is_shown_separately():
    ti = TextInput()
    feed(ti, [editing("ㄱ"), editing("고"), editing("곱")])
    assert ti.text == "" and ti.composition == "곱"
    feed(ti, [committed("고"), editing("ㅂ")])
    assert ti.text == "고" and ti.composition == "ㅂ"


def test_backspace_during_composition_keeps_committed_text():
    ti = TextInput()
    feed(ti, [committed("고블"), editing("린"), key(pygame.K_BACKSPACE), editing("리")])
    assert ti.text == "고블" and ti.composition == "리"


def test_backspace_without_composition_deletes_one():
    ti = TextInput()
    feed(ti, [committed("베어"), key(pygame.K_BACKSPACE)])
    assert ti.text == "베"


def test_enter_during_composition_commits_then_submits():
    ti = TextInput()
    out = feed(ti, [committed("고블린을 베"), editing("어"), key(pygame.K_RETURN)])
    assert out == ["고블린을 베어"] and ti.text == "" and ti.composition == ""
    feed(ti, [committed("어")])
    assert ti.text == ""


def test_enter_after_commit_submits_trimmed():
    ti = TextInput()
    out = feed(ti, [committed("  대기  "), key(pygame.K_RETURN), key(pygame.K_RETURN)])
    assert out == ["대기"]


def test_escape_clears():
    ti = TextInput()
    feed(ti, [committed("오크"), editing("를"), key(pygame.K_ESCAPE)])
    assert ti.text == "" and ti.composition == ""


# ---- 창 없는 그리기 ----

class Instant:
    def __call__(self, fn):
        fn()


def session_with(*replies, seed=5):
    return GameSession(Interpreter(FakeClient(*replies)), MemoryLog(), lambda: seed, spawn=Instant(), model="fake",
                       plan_display_seconds=0)


@pytest.fixture
def app_factory():
    pygame.init()
    surface = pygame.Surface(render.WINDOW_SIZE)

    def make(session, **kw):
        app = App(session, **kw)
        app.open(headless_surface=surface)
        return app

    yield make
    pygame.quit()


def pixel_mean(surface, rect):
    sub = surface.subsurface(rect)
    total = [0, 0, 0]
    n = 0
    for x in range(0, sub.get_width(), 8):
        for y in range(0, sub.get_height(), 8):
            c = sub.get_at((x, y))
            total[0] += c.r
            total[1] += c.g
            total[2] += c.b
            n += 1
    return tuple(v / n for v in total)


def test_draw_initial_uses_backdrop_and_no_grid_lines(app_factory):
    app = app_factory(session_with())
    app.frame([])
    assert not app.assets.missing  # 저장소의 자산이 모두 읽혔다
    scene = app.screen.subsurface((0, 0, render.SCENE_SIZE[0], render.SCENE_SIZE[1]))
    whites = 0  # 지면 중앙에 흰 격자선이 없다
    for x in range(400, 900, 3):
        for y in range(350, 600, 3):
            c = scene.get_at((x, y))
            if c.r > 245 and c.g > 245 and c.b > 245:
                whites += 1
    assert whites < 20


def test_draw_plan_preview_then_animation_then_idle(app_factory):
    s = session_with(reply(step("move", move=move_spec(toward=target("goblin"), cells=2))))
    app = app_factory(s)
    app.frame([committed("고블린 쪽으로 두 칸 가"), key(pygame.K_RETURN)])
    assert s.phase == "planned"
    assert s.plan_line.startswith("계획 2/4 AP")
    app.frame([])  # 표시 뒤 자동 실행 → 연출 시작
    assert s.phase == "animating" and s.state.turn == 2
    assert s.submit("대기") == "busy"  # 연출 중 입력 차단
    for _ in range(400):
        app.frame([], 1 / 30)
        if s.phase == "idle":
            break
    assert s.phase == "idle" and app.display.matches(s.state)


def test_restart_during_animation_resets_display(app_factory):
    s = session_with(reply(step("guard")))
    app = app_factory(s)
    app.frame([committed("방어"), key(pygame.K_RETURN)])
    app.frame([])
    assert s.phase == "animating"
    app.frame([committed("다시 시작"), key(pygame.K_RETURN)])
    assert s.phase == "idle" and s.state.turn == 1 and not app.animator.running
    assert app.display.matches(s.state)


def test_draw_rejected_and_outcomes(app_factory):
    s = session_with(reply(step("attack", target=target("goblin"))))
    app = app_factory(s)
    app.frame([committed("고블린을 베어"), key(pygame.K_RETURN)])
    assert s.plan_line.startswith("거부: ① 고블린이 옆에 없어요")
    for outcome in ("win", "lose"):
        s.state.outcome = outcome
        app.frame([])
        assert render.result_text(s)[0].startswith("승리" if outcome == "win" else "패배")


def test_debug_grid_only_when_enabled(app_factory):
    s = session_with()
    app = app_factory(s)
    app.frame([])
    before = pixel_mean(app.screen, (300, 300, 700, 300))
    app.frame([key(pygame.K_F3)])
    assert app.debug
    after = pixel_mean(app.screen, (300, 300, 700, 300))
    assert after != before


def test_missing_assets_fall_back_to_shapes(app_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(assets_mod, "ASSET_DIR", tmp_path)
    app = app_factory(session_with())
    assert "backdrop.png" in app.assets.missing and "units/seorin.png" in app.assets.missing
    app.frame([])  # 대체 도형으로 그려진다


def test_wrap_korean():
    pygame.font.init()
    fonts = assets_mod.Fonts()
    lines = render.wrap(fonts.small, "가" * 200, 300)
    assert len(lines) > 1 and "".join(lines) == "가" * 200


# ---- 이벤트 루프 ----

def test_quit_is_handled_while_ai_is_busy(app_factory):
    gate = threading.Event()

    class Blocking:
        def interpret(self, sentence, state):
            gate.wait(5)
            return Interpreter(FakeClient(reply(step("wait")))).interpret(sentence, state)

    session = GameSession(Blocking(), MemoryLog(), lambda: 1)
    app = app_factory(session)
    app.frame([committed("대기"), key(pygame.K_RETURN)])
    assert session.busy
    app.frame([committed("대기"), key(pygame.K_RETURN)])  # 처리 중 두 번째 제출
    assert session.notice == "이전 명령을 처리하는 중이에요"
    app.frame([pygame.event.Event(pygame.QUIT)])
    assert not app.running
    gate.set()


def test_main_runs_a_few_frames(monkeypatch, tmp_path):
    from promptgame import main as main_module

    monkeypatch.setenv("PROMPTGAME_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("PROMPTGAME_OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PROMPTGAME_SEED", "3")
    assert main_module.main(max_frames=3) == 0
    assert list(tmp_path.glob("turns-*.jsonl"))
