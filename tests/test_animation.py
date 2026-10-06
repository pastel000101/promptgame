"""연출 큐·표시 상태·투영 (설계서 §4.2~§4.4). 판정은 domain이 끝낸 뒤이며, 연출은 난수·피해를 건드리지 않는다."""

import random

import pytest

from helpers import ENEMY, GOBLIN, ORC, attack, dash, make_state, move, plan
from promptgame.domain import level
from promptgame.domain.plan import Step, TargetRef
from promptgame.domain.resolve import play_turn
from promptgame.domain.state import new_game
from promptgame.presentation import animation as anim
from promptgame.presentation.camera import Camera
from promptgame.presentation.display import DisplayState


def run_turn(state, p, seed):
    """실제 판정을 돌리고, 판정 전 표시 상태 위에서 연출을 끝까지 재생한다."""
    display = DisplayState.from_game(state)
    rng = random.Random(seed)
    rng_before = rng.getstate()
    result = play_turn(state, p, rng)
    rng_after = rng.getstate()
    animator = anim.Animator(display, Camera.default())
    animator.start(result.events, state.terrain)
    cues = list(animator.cues)
    animator.run_to_end()
    assert rng.getstate() == rng_after and rng_after != rng_before  # 연출은 난수를 쓰지 않는다
    assert display.matches(state, strict=False)  # 위치·체력·생존은 연출만으로 실제 상태와 같다
    display.sync(state)  # 턴 끝 상태 지속 감소는 앱이 실제 상태로 동기화한다
    return result, cues, display, animator


def types(cues):
    return [type(c).__name__ for c in cues if not isinstance(c, (anim.Delay, anim.EnemyActive, anim.TurnEndCue))]


def test_e1_cue_order_and_display_matches_state():
    s = make_state(player=(7, 5), orc=(2, 6))
    result, cues, display, animator = run_turn(s, plan(dash(toward=ENEMY), attack(ENEMY, aim="head")), 5643)
    assert types(cues) == ["MoveCue", "AttackCue", "HitCue", "BannerCue", "AttackCue", "MissCue", "MoveCue"]
    assert cues[0].dash and cues[0].path == [(7, 4), (7, 3)]
    assert display.matches(s)
    assert display.units["goblin"].hp == 3 and display.units["goblin"].statuses == {}
    assert not display.dashed
    assert display.units["orc"].pos == (2.0, 5.0)
    assert animator.played_lines[0].startswith("① 돌진") and animator.played_lines[-1].startswith("적 턴: 오크 이동")


def test_e2_fireball_cue_and_burn():
    s = make_state(orc=(2, 6))
    result, cues, display, animator = run_turn(s, plan(Step("cast", target=ORC, ability="fireball")), 186)
    names = types(cues)
    assert names[:2] == ["ProjectileCue", "HitCue"]
    assert cues[0].kind == "fireball" and cues[0].hit
    assert "BurnCue" in names and names.index("BannerCue") < names.index("BurnCue")
    assert display.matches(s)
    assert display.units["orc"].statuses["burning"] == 1


def test_e6_hit_cancels_and_death_lies_down():
    s = make_state(player=(7, 3), orc=(6, 5))
    s.enemy("goblin").hp = 3
    s.enemy("goblin").statuses["stagger"] = 1
    staggered = TargetRef("goblin", "staggered")
    result, cues, display, animator = run_turn(s, plan(attack(staggered), attack(staggered)), 55)
    names = types(cues)
    assert names[:4] == ["AttackCue", "HitCue", "DeathCue", "TextCue"]
    assert display.units["goblin"].lying and not display.units["goblin"].alive
    assert display.matches(s)


def test_e6_miss_keeps_second_attack():
    s = make_state(player=(7, 3), orc=(6, 5))
    s.enemy("goblin").hp = 3
    s.enemy("goblin").statuses["stagger"] = 1
    staggered = TargetRef("goblin", "staggered")
    result, cues, display, animator = run_turn(s, plan(attack(staggered), attack(staggered)), 19)
    names = types(cues)
    assert names[:4] == ["AttackCue", "MissCue", "AttackCue", "HitCue"]
    assert display.matches(s)


def test_move_cue_interpolates_through_cells():
    s = new_game()
    display = DisplayState.from_game(s)
    result = play_turn(s, plan(move(toward=GOBLIN, cells=3)), random.Random(1))
    animator = anim.Animator(display, Camera.default())
    animator.start(result.events, s.terrain)
    seen = set()
    while animator.running and animator.index == 0:
        animator.update(1 / 60)
        seen.add((round(display.player.gx, 1), round(display.player.gy, 1)))
    assert len(seen) > 6  # 칸 사이의 중간 위치가 보인다
    animator.run_to_end()
    assert display.matches(s, strict=False)


def test_whirlwind_potion_guard_wait_knife_cues():
    s = make_state(player=(6, 5), goblin=(7, 5), orc=(6, 6), hp=10)
    result, cues, display, _ = run_turn(s, plan(Step("skill", ability="whirlwind"), Step("use_item", item="potion")), 3)
    names = types(cues)
    assert names[0] == "WhirlCue" and "PotionCue" in names
    assert display.matches(s)
    s = make_state(player=(7, 5), goblin=(7, 2), orc=(1, 6))
    result, cues, display, _ = run_turn(s, plan(Step("use_item", item="throwing_knife", target=GOBLIN), Step("guard")), 3)
    names = types(cues)
    assert names[0] == "ProjectileCue" and cues[0].kind == "knife" and "GuardCue" in names
    assert display.guarding is False  # 적 턴이 끝나며 해제된 실제 상태와 같다
    assert display.matches(s)
    assert any(isinstance(c, anim.TurnEndCue) for c in cues)


def test_lose_outcome_cue():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead", hp=1)
    result, cues, display, _ = run_turn(s, plan(Step("wait")), next(seed for seed in range(1, 999) if random.Random(seed).randint(1, 100) <= 5))
    names = types(cues)
    assert names[-2:] == ["DeathCue", "OutcomeCue"]
    assert display.player.lying and display.matches(s)


def test_camera_projection_is_monotonic():
    cam = Camera.default()
    far = cam.cell_width(1)
    near = cam.cell_width(6)
    assert near > far > 0
    assert cam.foot(2, 2)[1] < cam.foot(2, 6)[1]
    assert cam.foot(2, 3)[0] < cam.foot(7, 3)[0]
    for y in range(1, 7):
        for x in range(1, 9):
            px, py = cam.foot(x, y)
            assert -400 < px < 1700 and 100 < py < 760


def test_display_sync_resets_transforms():
    s = new_game()
    d = DisplayState.from_game(s)
    d.player.dx = 20
    d.player.upper = 30
    d.sync(s)
    assert d.player.dx == 0 and d.player.upper == 0 and d.matches(s)
