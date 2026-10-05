"""AI를 쓸 수 없을 때의 정확 일치 명령표 (설계서 §3).

문장 전체(앞뒤 공백 제외)가 명령과 정확히 같을 때만 처리한다. 단어가 들어 있다는 이유만으로 실행하지 않는다.
"""

from __future__ import annotations

from promptgame.domain.plan import MoveSpec, Plan, Step, TargetRef
from promptgame.domain.state import GameState

_SIMPLE = {
    "대기": Step("wait"),
    "방어": Step("guard"),
    "물약": Step("use_item", item="potion"),
    "북": Step("move", move=MoveSpec(direction="N", cells=1)),
    "동": Step("move", move=MoveSpec(direction="E", cells=1)),
    "남": Step("move", move=MoveSpec(direction="S", cells=1)),
    "서": Step("move", move=MoveSpec(direction="W", cells=1)),
}
ATTACK = "공격"
COMMANDS = ("대기", "방어", "공격", "물약", "북", "남", "동", "서")
GUIDE = "AI 없이 쓸 수 있는 명령: " + " · ".join(COMMANDS)


def match(sentence: str, state: GameState) -> tuple[Plan | None, str | None]:
    """(계획, 안내문). 명령이 아니면 (None, None)."""
    text = sentence.strip()
    if text in _SIMPLE:
        return Plan((_SIMPLE[text],)), None
    if text == ATTACK:
        adjacent = state.adjacent_enemies()
        if len(adjacent) != 1:
            return None, "'공격' 명령은 옆에 적이 하나일 때만 쓸 수 있어요"
        return Plan((Step("attack", target=TargetRef(adjacent[0].kind)),)), None
    return None, None
