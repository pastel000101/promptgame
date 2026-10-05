"""화면·입력: SDL 이벤트 순서 재현과 창 없는 그리기 (dummy 드라이버)."""

import threading

import pygame
import pytest

from fakes import FakeClient, MemoryLog, reply, step, target
from promptgame.application.interpreter import Interpreter
from promptgame.application.session import GameSession
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
    # IME가 같은 글자를 뒤늦게 확정해도 다음 입력에 섞이지 않는다
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

@pytest.fixture(scope="module")
def screen():
    pygame.init()
    surface = pygame.display.set_mode(render.WINDOW_SIZE)
    yield surface
    pygame.quit()


class Instant:
    def __call__(self, fn):
        fn()


def session_with(*replies, seed=5):
    return GameSession(Interpreter(FakeClient(*replies)), MemoryLog(), lambda: seed, spawn=Instant(), model="fake")


def draw(screen, session, ti=None):
    fonts = render.Fonts()
    render.draw(screen, session, ti or TextInput(), fonts)


def test_draw_initial(screen):
    s = session_with()
    draw(screen, s)
    lines = [t for t, _ in render.panel_lines(s)]
    assert "턴 1 · 시드 5" in lines[0]
    assert any("가방: 치유 물약 1 · 투척 단검 2" in t for t in lines)


def test_draw_accepted_plan_and_results(screen):
    s = session_with(reply(step("move", move={"toward": target("goblin"), "away_from": None, "direction": None, "cells": 2})))
    s.submit("고블린 쪽으로 두 칸 가")
    s.poll()
    assert s.plan_line.startswith("계획 2/4 AP: ① 이동 2칸 → 고블린 쪽 (2)")
    ti = TextInput()
    feed(ti, [committed("화염구"), editing("로")])
    draw(screen, s, ti)


def test_draw_rejected_plan(screen):
    s = session_with(reply(step("attack", target=target("goblin"))))
    s.submit("고블린을 베어")
    s.poll()
    assert s.plan_line.startswith("거부: ① 고블린이 옆에 없어요")
    draw(screen, s)


@pytest.mark.parametrize("outcome, title", [("win", "승리!"), ("lose", "패배")])
def test_draw_outcomes(screen, outcome, title):
    s = session_with()
    s.state.outcome = outcome
    draw(screen, s)
    assert render.result_text(s)[0].startswith(title)


def test_wrap_korean():
    pygame.font.init()
    font = render.Fonts().small
    lines = render.wrap(font, "가" * 200, 300)
    assert len(lines) > 1 and "".join(lines) == "가" * 200


# ---- 이벤트 루프 ----

def test_quit_is_handled_while_ai_is_busy(screen):
    gate = threading.Event()

    class Blocking:
        def interpret(self, sentence, state):
            gate.wait(5)
            return Interpreter(FakeClient(reply(step("wait")))).interpret(sentence, state)

    session = GameSession(Blocking(), MemoryLog(), lambda: 1)
    app = App(session)
    app.screen, app.fonts, app.running = screen, render.Fonts(), True
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
