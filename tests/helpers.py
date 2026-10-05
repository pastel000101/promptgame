"""테스트용 상태·계획 구성 도우미."""

from promptgame.domain.plan import MoveSpec, Plan, Step, TargetRef
from promptgame.domain.state import GameState, new_game

ENEMY = TargetRef("enemy")
GOBLIN = TargetRef("goblin")
ORC = TargetRef("orc")


def make_state(player=None, goblin=None, orc=None, **player_fields) -> GameState:
    """기본 전장에서 위치·체력 등을 바꾼 검증용 상태. 위치 None은 기본값, 'dead'는 쓰러진 상태."""
    s = new_game()
    if player:
        s.player.pos = player
    for uid, pos in (("goblin", goblin), ("orc", orc)):
        if pos == "dead":
            s.enemy(uid).hp = 0
        elif pos:
            s.enemy(uid).pos = pos
    for key, value in player_fields.items():
        if key == "hp":
            s.player.hp = value
        else:
            setattr(s, key, value)
    return s


def plan(*steps: Step) -> Plan:
    return Plan(tuple(steps))


def move(**kw) -> Step:
    return Step("move", move=MoveSpec(**kw))


def dash(**kw) -> Step:
    return Step("dash", move=MoveSpec(**kw))


def attack(target=ENEMY, aim="none", power="normal") -> Step:
    return Step("attack", target=target, aim=aim, power=power)
