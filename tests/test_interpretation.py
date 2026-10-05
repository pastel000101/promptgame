"""응답 형식 검증·재시도·서버 실패·폴백·되묻기 (대역 클라이언트, 실제 LLM 아님)."""

import json

import pytest

from fakes import FakeClient, move_spec, reply, step, target
from promptgame.application import fallback
from promptgame.application.intent import Clarify, FormatError, parse_response
from promptgame.application.interpreter import Interpreter
from promptgame.application.ports import LlmError
from promptgame.application.prompt import EXAMPLES, SYSTEM_PROMPT, build_messages, state_summary
from promptgame.domain.plan import Plan
from promptgame.domain.state import new_game


# ---- 형식 검증 ----

def test_parse_valid_plan():
    text = json.dumps(reply(step("dash", move=move_spec(toward=target())), step("attack", target=target(), aim="head")))
    plan = parse_response(text)
    assert isinstance(plan, Plan) and [s.act for s in plan.steps] == ["dash", "attack"]
    assert plan.steps[1].aim == "head"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"steps": []}),
        json.dumps(reply()),  # 단계 0개, clarify 없음
        json.dumps(reply(*[step("wait")] * 4)),  # 단계 4개
        json.dumps(reply(step("fly"))),  # 없는 동작
        json.dumps(reply(step("attack"))),  # 대상 없음
        json.dumps(reply(step("skill", ability="fireball"))),
        json.dumps(reply(step("cast", ability="fireball"))),  # 대상 없음
        json.dumps(reply(step("use_item", item="throwing_knife"))),
        json.dumps(reply(step("move", move=move_spec(direction="N", toward=target())))),  # 둘 다
        json.dumps(reply(step("move", move=move_spec(direction="N", cells=0)))),
        json.dumps(reply(step("attack", target=target("dragon")))),
        json.dumps(reply(step("attack", target=target(), aim="tail"))),
        json.dumps(reply(clarify="maybe")),
    ],
)
def test_parse_rejects_bad_format(payload):
    with pytest.raises(FormatError):
        parse_response(payload)


def test_clarify_wins_over_steps():
    assert parse_response(json.dumps(reply(step("wait"), clarify="too_many_steps"))) == Clarify("too_many_steps")


def test_prompt_contains_examples_and_summary():
    assert len(EXAMPLES) == 6
    for sentence, _ in EXAMPLES:
        assert sentence in SYSTEM_PROMPT
    summary = state_summary(new_game())
    assert "고블린: 체력 10/10" in summary and "동쪽 5칸 (거리 5)" in summary
    assert "주변 지형:" in summary
    messages = build_messages(summary, "대기", retry=True)
    assert messages[0]["role"] == "system" and "형식에 맞지 않았다" in messages[1]["content"]


# ---- 해석기 ----

def test_interpreter_success_single_call():
    client = FakeClient(reply(step("guard")))
    r = Interpreter(client).interpret("방어 자세를 잡아", new_game())
    assert r.source == "llm" and r.attempts == 1 and r.plan.steps[0].act == "guard"
    assert len(client.calls) == 1 and len(client.calls[0]) == 2  # 이전 턴 누적 없음


def test_interpreter_retries_format_once():
    client = FakeClient("{broken", reply(step("wait")))
    r = Interpreter(client).interpret("기다려", new_game())
    assert r.source == "llm" and r.attempts == 2 and r.plan is not None
    assert "형식에 맞지 않았다" in client.calls[1][1]["content"]


def test_interpreter_gives_up_after_second_format_error():
    client = FakeClient("{broken", "still broken")
    r = Interpreter(client).interpret("고블린을 베어", new_game())
    assert r.source == "none" and r.failure == "format" and r.attempts == 2 and r.plan is None
    assert r.message.startswith("이해하지 못했어요") and fallback.GUIDE in r.message


@pytest.mark.parametrize("kind", ["timeout", "connection", "http"])
def test_server_failure_not_retried(kind):
    client = FakeClient(LlmError(kind, "x"))
    r = Interpreter(client).interpret("고블린을 베어", new_game())
    assert r.failure == kind and r.attempts == 1 and len(client.calls) == 1
    assert r.source == "none" and r.plan is None and fallback.GUIDE in r.message


@pytest.mark.parametrize("reason, text", [
    ("ambiguous", "무엇을 어떻게 할지 더 적어 주세요"),
    ("unrelated", "전투 행동으로 이해하지 못했어요"),
    ("too_many_steps", "한 턴에는 3단계까지만 적어 주세요"),
])
def test_clarify_messages(reason, text):
    r = Interpreter(FakeClient(reply(clarify=reason))).interpret("…", new_game())
    assert r.source == "llm" and r.plan is None and r.clarify == reason and r.message == text


# ---- 폴백 정확 일치 ----

@pytest.mark.parametrize("sentence, act", [("대기", "wait"), ("방어", "guard"), ("물약", "use_item"), ("북", "move"), (" 서 ", "move")])
def test_fallback_exact_match_when_server_down(sentence, act):
    r = Interpreter(FakeClient(LlmError("connection"))).interpret(sentence, new_game())
    assert r.source == "fallback" and r.plan.steps[0].act == act and r.failure == "connection"


@pytest.mark.parametrize("sentence", ["북쪽으로 가서 벤다", "대기해", "물약 마셔", "공격하라"])
def test_fallback_ignores_partial_words(sentence):
    r = Interpreter(FakeClient(LlmError("connection"))).interpret(sentence, new_game())
    assert r.source == "none" and r.plan is None


def test_fallback_attack_needs_single_adjacent_enemy():
    s = new_game()
    plan, note = fallback.match("공격", s)
    assert plan is None and "하나일 때만" in note
    s.player.pos = (6, 2)
    plan, note = fallback.match("공격", s)
    assert plan.steps[0].target.kind == "goblin"


def test_fallback_not_used_when_llm_answers():
    r = Interpreter(FakeClient(reply(clarify="unrelated"))).interpret("대기", new_game())
    assert r.source == "llm" and r.plan is None
