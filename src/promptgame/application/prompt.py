"""AI에 보내는 고정 지시문과 상태 요약 (설계서 §2.3). 매 턴 이전 대화를 누적하지 않는다."""

from __future__ import annotations

import json

from promptgame.domain import level
from promptgame.domain.narrate import DIRECTION_NAMES, TERRAIN_NAMES, name
from promptgame.domain.plan import MoveSpec, Plan, Step, TargetRef
from promptgame.domain.state import DIRECTION_ORDER, GameState, distance, step

_ENEMY = TargetRef("enemy")

# 설계서 §10의 예시 문장과 기대 해석
EXAMPLES: tuple[tuple[str, Plan], ...] = (
    ("신속하게 다가가서 녀석의 머리를 벤다.",
     Plan((Step("dash", move=MoveSpec(toward=_ENEMY)), Step("attack", target=_ENEMY, aim="head")))),
    ("화염구로 오크를 태워.",
     Plan((Step("cast", target=TargetRef("orc"), ability="fireball"),))),
    ("물약 마시고 뒤로 물러나.",
     Plan((Step("use_item", item="potion"), Step("move", move=MoveSpec(away_from=_ENEMY))))),
    ("진흙을 가로질러 돌진해서 고블린을 벤다.",
     Plan((Step("dash", move=MoveSpec(toward=TargetRef("goblin"))), Step("attack", target=TargetRef("goblin"))))),
    ("오크 머리를 힘껏 내려치고 고블린도 벤다.",
     Plan((Step("attack", target=TargetRef("orc"), aim="head", power="strong"), Step("attack", target=TargetRef("goblin"))))),
    ("비틀거리는 고블린을 베고 또 벤다.",
     Plan((Step("attack", target=TargetRef("goblin", "staggered")), Step("attack", target=TargetRef("goblin", "staggered"))))),
)


def plan_json(plan: Plan) -> str:
    return json.dumps({**plan.to_dict(), "clarify": None}, ensure_ascii=False)


def _examples_text() -> str:
    return "\n".join(f"문장: {sentence}\n응답: {plan_json(plan)}" for sentence, plan in EXAMPLES)


SYSTEM_PROMPT = f"""너는 한국어 턴제 전투 게임의 입력 해석기다. 플레이어가 한 문장으로 묘사한 한 턴의 행동을 단계로 나눠 JSON 하나로만 답한다.
가능 여부·비용·명중은 판단하지 않는다. 게임 코드가 검증하고 판정한다.

## 동작 act
- move: 걷기. "가", "이동", "다가가", "접근", "걸어가", "물러나"
- dash: 빠른 접근. "신속하게", "빠르게", "달려가서", "돌진", "뛰어가"
- attack: 무기 공격. "벤다", "베어", "공격", "찌른다", "때린다", "내려친다"
- skill: 스킬 돌려베기(ability "whirlwind"). "돌려베기", "주변을 휘둘러"
- cast: 마법 화염구(ability "fireball"). "화염구", "불덩이", "태워"
- use_item: item "potion"(치유 물약: "물약", "마셔", "회복") 또는 "throwing_knife"(투척 단검: "단검을 던져", "투척")
- guard: 방어 자세. "방어", "막아", "자세를 잡아"
- wait: 대기. "대기", "기다려", "쉬어"

## 방법 수식
- 돌진은 act "dash"로 쓴다.
- power "strong": "힘껏", "세게", "내려친다". 무기 공격에만.
- aim "head" / "arm" / "leg": "머리", "팔", "다리"를 노릴 때. 무기 공격과 투척 단검에만.
- 해당 없으면 aim "none", power "normal".

## 대상 target {{"kind", "relation"}}
- kind: "goblin"(고블린), "orc"(오크), "enemy"(종류를 말하지 않음: "녀석", "그놈", "적", "놈")
- relation: "nearest"(가까운), "farthest"(먼), "last_attacked"(방금·아까 공격한), "lowest_hp"(체력이 적은·약한), "burning"(불타는), "staggered"(비틀거리는), "north"/"south"/"east"/"west"(북·남·동·서쪽의), 해당 없으면 null
- attack, cast, 투척 단검은 target이 필요하다. 그 밖의 동작은 target null.

## 이동 move {{"toward", "away_from", "direction", "cells"}} — toward·away_from·direction 중 하나만 쓴다
- toward: 대상 옆으로 다가간다. 칸 수를 말했으면 cells, 아니면 null.
- away_from: 대상에게서 멀어진다. "뒤로 물러나"는 away_from {{"kind": "enemy", "relation": null}}. cells는 말한 칸 수, 없으면 null.
- direction: "N"(북·위), "E"(동·오른쪽), "S"(남·아래), "W"(서·왼쪽)과 cells(말하지 않으면 null).
- move·dash가 아니면 move null.

## 규칙
- 문장에 적힌 동작·순서·수식을 그대로 단계로 옮긴다. 비용이 넘칠 것 같아도 동작을 빼거나 바꾸지 않는다. 비용 초과는 게임이 거부한다.
- "또", "한 번 더"처럼 반복하면 단계를 따로 쓴다.
- 한 턴은 {level.MAX_STEPS}단계까지다. 동작이 {level.MAX_STEPS}개를 넘으면 일부만 고르지 말고 steps [] 와 clarify "too_many_steps".
- 전투 행동이 아닌 문장(인사, 잡담, 질문)은 steps [] 와 clarify "unrelated".
- 무엇을 할지 정할 수 없으면 steps [] 와 clarify "ambiguous".
- 그 밖에는 clarify null.
- 모든 단계에 act, target, move, aim, power, ability, item을 모두 넣는다.

## 참고: 한 턴 AP {level.AP_PER_TURN}, 비용(해석용 참고일 뿐이다)
이동 칸당 1(진흙 2), 돌진 2칸당 1(최대 4칸), 무기 공격 2, 돌려베기 3, 화염구 2(마나 3), 물약 1, 투척 단검 1, 방어 1, 대기 0, 강타 +1, 조준 +1.

## 예시
{_examples_text()}
"""


def _status_text(statuses: dict[str, int]) -> str:
    names = {"stagger": "비틀거림", "burning": "불타는", "arm_injury": "팔 부상", "leg_injury": "다리 부상"}
    parts = []
    for key, value in statuses.items():
        parts.append(names[key] if key == "arm_injury" else f"{names[key]} {value}턴")
    return ", ".join(parts) if parts else "없음"


def _relative_text(dx: int, dy: int) -> str:
    parts = []
    if dy:
        parts.append(f"{'북쪽' if dy < 0 else '남쪽'} {abs(dy)}칸")
    if dx:
        parts.append(f"{'서쪽' if dx < 0 else '동쪽'} {abs(dx)}칸")
    return "·".join(parts)


def _terrain_line(state: GameState) -> str:
    parts = []
    for d in DIRECTION_ORDER:
        pos = state.player.pos
        found = None
        for n in range(1, 5):
            pos = step(pos, d)
            t = state.terrain(pos)
            if t != level.FLOOR:
                found = f"{DIRECTION_NAMES[d]} {n}칸째 {TERRAIN_NAMES[t]}"
                break
        parts.append(found or f"{DIRECTION_NAMES[d]} 4칸까지 바닥")
    return " · ".join(parts)


def state_summary(state: GameState) -> str:
    p = state.player
    player_status = []
    if state.dashed:
        player_status.append("돌진 직후")
    if state.guarding:
        player_status.append("방어 자세")
    cooldown = "사용 가능" if state.whirlwind_cooldown == 0 else f"재사용 대기 {state.whirlwind_cooldown}턴"
    lines = [
        f"플레이어(용병): 위치 ({p.pos[0]},{p.pos[1]}), 체력 {p.hp}/{p.max_hp}, 마나 {state.mana}, AP {state.ap}, "
        f"상태 {', '.join(player_status) or '없음'}, 돌려베기 {cooldown}, 가방: 치유 물약 {state.potions}, 투척 단검 {state.knives}",
        "적:",
    ]
    for e in state.alive_enemies():
        dx, dy = e.pos[0] - p.pos[0], e.pos[1] - p.pos[1]
        lines.append(f"- {name(e.kind)}: 체력 {e.hp}/{e.max_hp}, 상태 {_status_text(e.statuses)}, "
                     f"{_relative_text(dx, dy)} (거리 {distance(p.pos, e.pos)})")
    last = state.last_attacked
    lines.append(f"마지막으로 공격한 적: {name(last) if last and state.enemy(last).alive else '없음'}")
    lines.append(f"주변 지형: {_terrain_line(state)}")
    return "\n".join(lines)


RETRY_NOTICE = "이전 응답이 형식에 맞지 않았다. 지정한 JSON 형식으로만 다시 답하라."


def build_messages(summary: str, sentence: str, retry: bool = False) -> list[dict]:
    user = f"상황:\n{summary}\n\n문장: {sentence}"
    if retry:
        user += f"\n\n{RETRY_NOTICE}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
