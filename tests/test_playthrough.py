"""대본 플레이: 기본 전장에서 정해진 계획 순서로 승리·패배까지 진행한다 (AI 없음)."""

import random

from helpers import attack, move, plan
from promptgame.domain.plan import TargetRef
from promptgame.domain.state import distance
from promptgame.domain.plan import Step
from promptgame.domain.resolve import play_turn
from promptgame.domain.state import new_game
from promptgame.domain.validate import validate_plan


def scripted_plan(s):
    """인접하면 두 번 베고, 아니면 가장 가까운 적에게 이번 턴에 갈 수 있는 만큼 걸어간다."""
    if s.player.hp <= 8 and s.potions:
        return plan(Step("use_item", item="potion"), Step("guard"))
    target = TargetRef(min(s.alive_enemies(), key=lambda e: distance(s.player.pos, e.pos)).kind)
    if s.adjacent_enemies():
        return plan(attack(target), attack(target))
    for cells in range(4, 0, -1):
        p = plan(move(toward=target, cells=cells))
        if validate_plan(s, p).accepted:
            return p
    return plan(Step("guard"))


def test_scripted_win():
    s = new_game()
    rng = random.Random(7)
    for _ in range(40):
        result = play_turn(s, scripted_plan(s), rng)
        assert result.accepted
        if s.outcome:
            break
    assert s.outcome == "win"


def test_scripted_loss_by_waiting():
    s = new_game()
    rng = random.Random(7)
    for _ in range(60):
        play_turn(s, plan(Step("wait")), rng)
        if s.outcome:
            break
    assert s.outcome == "lose" and s.player.hp == 0
