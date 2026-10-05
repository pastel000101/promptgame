"""규칙·비용·판정·적 턴 고정 시드 테스트 (설계서 §1, §2.4~§2.6)."""

import random

import pytest

from helpers import ENEMY, GOBLIN, ORC, attack, dash, make_state, move, plan
from promptgame.domain import level
from promptgame.domain.plan import Step, TargetRef
from promptgame.domain.resolve import enemy_turn, play_turn
from promptgame.domain.state import has_sight, new_game
from promptgame.domain.targeting import TargetError, resolve_target
from promptgame.domain.validate import validate_plan


def first_roll_seed(predicate):
    for seed in range(1, 10_000):
        if predicate(random.Random(seed).randint(1, 100)):
            return seed
    raise AssertionError("seed not found")


HIT = first_roll_seed(lambda d: d <= 5)
MISS = first_roll_seed(lambda d: d > 95)


# ---- 시작 상태 ----

def test_new_game_matches_design():
    s = new_game()
    assert s.player.pos == (2, 2) and s.enemy("goblin").pos == (7, 2) and s.enemy("orc").pos == (6, 6)
    assert (s.player.hp, s.mana, s.ap, s.potions, s.knives, s.turn) == (20, 6, 4, 1, 2, 1)
    assert (s.enemy("goblin").hp, s.enemy("orc").hp) == (10, 18)


# ---- 동작 8종: 비용·명중·피해·효과 ----

def test_move_costs_mud_two():
    s = make_state(player=(4, 3), goblin=(8, 6), orc=(1, 6))
    v = validate_plan(s, plan(move(direction="E", cells=2)))
    assert v.accepted and v.total_ap == 4  # 진흙 2칸
    assert v.checks[0].path == [(5, 3), (6, 3)]


def test_dash_two_cells_per_ap_and_max_four():
    s = make_state(player=(1, 6), goblin=(8, 1), orc=(8, 3))
    v = validate_plan(s, plan(dash(direction="E", cells=4)))
    assert v.accepted and v.total_ap == 2
    v = validate_plan(s, plan(dash(direction="E", cells=5)))
    assert not v.accepted and v.rejection.code == "dash_range"


def test_dash_cannot_enter_bush():
    s = make_state(player=(2, 4), goblin=(8, 1), orc=(8, 6))
    v = validate_plan(s, plan(dash(direction="E", cells=1)))
    assert not v.accepted and "덤불" in v.rejection.message


def test_dash_penalizes_attack_and_evasion():
    s = make_state(player=(7, 5), goblin=(7, 2), orc=(2, 6))
    v = validate_plan(s, plan(dash(toward=GOBLIN), attack(GOBLIN)))
    assert v.checks[1].chances["goblin"] == 85 - 10 - 20  # 돌진 −10, 고블린 회피 20
    r = play_turn(s, plan(dash(toward=GOBLIN), attack(GOBLIN)), random.Random(MISS))
    goblin_attack = [e for e in r.events if e.data.get("type") == "enemy_attack"][0]
    assert goblin_attack.data["chance"] == 60 - (15 - 10)


def test_weapon_attack_damage_and_armor():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead")
    r = play_turn(s, plan(attack(ORC)), random.Random(HIT))
    assert r.events[0].data["chance"] == 85 - 5
    assert s.enemy("orc").hp == 18 - (5 - 2)


def test_strong_modifier():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead")
    v = validate_plan(s, plan(attack(ORC, power="strong")))
    assert v.total_ap == 3 and v.checks[0].chances["orc"] == 85 - 10 - 5
    play_turn(s, plan(attack(ORC, power="strong")), random.Random(HIT))
    assert s.enemy("orc").hp == 18 - (5 + 3 - 2)


@pytest.mark.parametrize("aim, status", [("head", "stagger"), ("arm", "arm_injury"), ("leg", "leg_injury")])
def test_aim_modifiers(aim, status):
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead")
    v = validate_plan(s, plan(attack(ORC, aim=aim)))
    assert v.total_ap == 3 and v.checks[0].chances["orc"] == 85 - 20 - 5
    r = play_turn(s, plan(attack(ORC, aim=aim)), random.Random(HIT))
    dmg = (7 if aim == "head" else 5) - 2
    assert r.events[0].data["damage"] == dmg
    assert r.events[0].data["effects"]


def test_arm_injury_reduces_enemy_damage():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead")
    s.enemy("orc").statuses["arm_injury"] = 1
    events = enemy_turn(s, random.Random(HIT))
    assert events[0].data["damage"] == (6 - 2) - 1


def test_leg_injury_stops_movement_for_two_turns():
    s = make_state(player=(2, 2), goblin="dead", orc=(6, 6))
    s.enemy("orc").statuses["leg_injury"] = 2
    for _ in range(2):
        play_turn(s, plan(Step("wait")), random.Random(1))
        assert s.enemy("orc").pos == (6, 6)
    play_turn(s, plan(Step("wait")), random.Random(1))
    assert s.enemy("orc").pos != (6, 6)


def test_whirlwind_hits_each_adjacent_and_cooldown():
    s = make_state(player=(6, 5), goblin=(7, 5), orc=(6, 6))
    p = plan(Step("skill", ability="whirlwind"))
    v = validate_plan(s, p)
    assert v.total_ap == 3
    assert v.checks[0].chances == {"goblin": 85 - 10 - 20, "orc": 85 - 10 - 5}
    r = play_turn(s, p, random.Random(1))
    assert len([e for e in r.events if e.data.get("type") == "player_attack"]) == 2
    # 다음 두 턴은 사용할 수 없고 그다음 턴에 다시 쓸 수 있다
    for _ in range(2):
        assert validate_plan(s, p).rejection.code == "cooldown"
        s.player.hp = 20
        play_turn(s, plan(Step("wait")), random.Random(1))
    s.player.hp = 20
    assert validate_plan(s, p).accepted


def test_whirlwind_rejects_aim_or_strong():
    s = make_state(player=(6, 5), goblin=(7, 5), orc=(6, 6))
    v = validate_plan(s, plan(Step("skill", ability="whirlwind", aim="head", power="strong")))
    assert not v.accepted and v.rejection.code == "modifier"


def test_fireball_needs_mana_range_and_sight():
    s = make_state(player=(2, 2), orc=(2, 6), mana=2)
    assert validate_plan(s, plan(Step("cast", ability="fireball", target=ORC))).rejection.code == "no_mana"
    s = make_state(player=(2, 1), orc=(2, 6))
    assert validate_plan(s, plan(Step("cast", ability="fireball", target=ORC))).rejection.code == "out_of_range"


def test_s4_bush_between_blocks_fireball_but_target_bush_does_not():
    s = make_state(player=(2, 4), orc=(4, 4))  # (3,4) 덤불이 중간, 오크 칸도 덤불
    v = validate_plan(s, plan(Step("cast", ability="fireball", target=ORC)))
    assert not v.accepted and v.rejection.code == "no_sight" and "덤불" in v.rejection.message
    s = make_state(player=(4, 6), orc=(4, 4))  # 중간 (4,5)는 덤불
    assert not has_sight(s, (4, 6), (4, 4))
    s = make_state(player=(4, 2), orc=(4, 4), goblin=(8, 1))  # 중간 (4,3)은 바닥, 대상 칸만 덤불
    v = validate_plan(s, plan(Step("cast", ability="fireball", target=ORC)))
    assert v.accepted and v.checks[0].chances["orc"] == 85 + 10 - 5 - 15


def test_fireball_burn_ticks_ignore_armor_and_can_win():
    s = make_state(player=(2, 2), orc=(2, 5), goblin="dead")
    s.enemy("orc").hp = 2
    s.enemy("orc").statuses["burning"] = 1
    r = play_turn(s, plan(Step("guard")), random.Random(1))
    assert s.outcome == "win"
    assert r.events[-1].data == {"type": "outcome", "outcome": "win"}


def test_potion_heals_to_max_and_consumes():
    s = make_state(hp=15)
    play_turn(s, plan(Step("use_item", item="potion")), random.Random(1))
    assert s.potions == 0
    assert s.player.hp <= 20


def test_throwing_knife_range_and_aim():
    s = make_state(player=(7, 5), goblin=(7, 2), orc=(1, 6))
    v = validate_plan(s, plan(Step("use_item", item="throwing_knife", target=GOBLIN, aim="leg")))
    assert v.accepted and v.total_ap == 2 and v.checks[0].chances["goblin"] == 85 - 20 - 20
    s = make_state(player=(7, 6), goblin=(7, 2), orc=(1, 6))
    assert validate_plan(s, plan(Step("use_item", item="throwing_knife", target=GOBLIN))).rejection.code == "out_of_range"
    v = validate_plan(make_state(player=(7, 5), goblin=(7, 2)), plan(Step("use_item", item="throwing_knife", target=GOBLIN, power="strong")))
    assert v.rejection.code == "modifier"


def test_guard_raises_evasion_until_enemy_turn_end():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead")
    r = play_turn(s, plan(Step("guard")), random.Random(1))
    assert r.events[-1].data["chance"] == 55 - (15 + 20)
    assert not s.guarding


def test_wait_ends_turn_and_must_be_last():
    s = new_game()
    r = play_turn(s, plan(Step("wait")), random.Random(1))
    assert r.accepted and s.turn == 2
    assert validate_plan(new_game(), plan(Step("wait"), Step("guard"))).rejection.code == "wait_not_last"


# ---- 대상 확정 (§2.4) ----

def test_s8_ambiguous_then_explicit_kind():
    s = make_state(player=(5, 5), goblin=(5, 4), orc=(6, 5))
    v = validate_plan(s, plan(attack(ENEMY)))
    assert v.rejection.code == "ambiguous" and set(v.rejection.candidates) == {"goblin", "orc"}
    assert validate_plan(s, plan(attack(GOBLIN))).accepted


def test_last_attacked_breaks_tie():
    s = make_state(player=(5, 5), goblin=(5, 4), orc=(6, 5), last_attacked="orc")
    assert resolve_target(s, ENEMY).uid == "orc"


def test_relation_without_matching_status():
    s = new_game()
    result = resolve_target(s, TargetRef("enemy", "burning"))
    assert isinstance(result, TargetError) and result.message == "그런 상태의 적이 없어요"


def test_relationless_enemy_stays_same_after_move():
    # 처음에는 고블린(거리 2)이 가장 가깝고, 남쪽으로 한 칸 가면 오크(거리 2)가 더 가까워진다.
    s = make_state(player=(6, 1), goblin=(8, 1), orc=(6, 4))
    v = validate_plan(s, plan(move(direction="S"), Step("use_item", item="throwing_knife", target=ENEMY)))
    assert v.accepted
    assert v.targets[ENEMY] == "goblin" and v.checks[1].label == "단검 투척 → 고블린"


def test_retreat_tie_prefers_opposite_of_larger_axis():
    s = make_state(player=(4, 6), orc=(5, 6))
    v = validate_plan(s, plan(move(away_from=ORC)))
    assert v.checks[0].path == [(3, 6)]


# ---- 상태 불변: 거부·모호·자원 중복·결합 불가 ----

@pytest.mark.parametrize(
    "state_kwargs, steps",
    [
        ({"player": (5, 5), "goblin": (5, 4), "orc": (6, 5)}, [attack(ENEMY)]),
        ({"hp": 6}, [Step("use_item", item="potion"), Step("use_item", item="potion")]),
        ({"player": (7, 5), "goblin": (7, 2), "orc": (1, 6)},
         [Step("use_item", item="throwing_knife", target=GOBLIN)] * 3),
        ({"player": (6, 5), "goblin": (7, 5), "orc": (6, 6)}, [Step("skill", ability="whirlwind", aim="head", power="strong")]),
        ({"player": (5, 5), "goblin": (5, 4), "orc": (6, 5)}, [attack(ORC, aim="head", power="strong"), attack(GOBLIN)]),
        ({}, [Step("cast", ability="fireball", target=GOBLIN), Step("cast", ability="fireball", target=GOBLIN), Step("cast", ability="fireball", target=GOBLIN)]),
    ],
    ids=["ambiguous", "potion_twice", "knife_three_times", "whirlwind_combo", "ap_over", "mana_and_ap"],
)
def test_rejected_plans_keep_state_and_rng(state_kwargs, steps):
    s = make_state(**state_kwargs)
    before = s.copy()
    rng = random.Random(123)
    rng_state = rng.getstate()
    r = play_turn(s, plan(*steps), rng)
    assert not r.accepted and r.events == []
    assert s == before and rng.getstate() == rng_state


def test_potion_twice_rejected_reason():
    v = validate_plan(make_state(hp=6), plan(Step("use_item", item="potion"), Step("use_item", item="potion")))
    assert v.rejection.index == 1 and v.rejection.message == "치유 물약이 없어요"


# ---- 적 턴 ----

def test_enemy_turn_order_and_pursuit():
    s = new_game()
    r = play_turn(s, plan(Step("wait")), random.Random(1))
    kinds = [e.data["enemy"] for e in r.events if e.data.get("type") == "enemy_move"]
    assert kinds == ["goblin", "orc"]
    assert s.enemy("orc").pos == (6, 5)  # 오크 이동력 1


def test_staggered_enemy_does_not_move_and_has_penalty():
    s = make_state(player=(5, 6), orc=(6, 6), goblin=(8, 1))
    s.enemy("goblin").statuses["stagger"] = 1
    s.enemy("orc").statuses["stagger"] = 1
    events = enemy_turn(s, random.Random(1))
    assert s.enemy("goblin").pos == (8, 1)
    assert events[0].data["chance"] == 55 - 20 - 15


def test_enemy_moves_around_occupied_cell():
    s = make_state(player=(1, 1), goblin=(8, 6), orc=(1, 3))
    s.enemies[0].pos = (2, 1)  # 고블린이 (2,1)을 차지해 오크는 남은 인접 칸 (1,2)로 온다
    enemy_turn(s, random.Random(MISS))
    assert s.enemy("orc").pos == (1, 2)


def test_enemy_without_path_stays():
    s = make_state(player=(1, 1), goblin=(2, 1), orc=(6, 6))
    s.grid = tuple(row if y != 2 else "##########" for y, row in enumerate(s.grid))  # 플레이어 주변 막기
    events = enemy_turn(s, random.Random(MISS))
    assert s.enemy("orc").pos == (6, 6)
    assert all(e.data.get("enemy") != "orc" for e in events)


# ---- 승패와 재현 ----

def test_enemy_attack_can_lose():
    s = make_state(player=(5, 6), orc=(6, 6), goblin="dead", hp=1)
    r = play_turn(s, plan(Step("wait")), random.Random(HIT))
    assert s.outcome == "lose" and r.events[-1].data["outcome"] == "lose"


def test_same_seed_same_plans_same_result():
    plans = [plan(dash(toward=GOBLIN)), plan(move(toward=GOBLIN, cells=2)), plan(attack(GOBLIN), attack(GOBLIN))]

    def run():
        s = make_state(player=(7, 6), orc=(1, 6))
        rng = random.Random(42)
        return [[e.text for e in play_turn(s, p, rng).events] for p in plans], s

    a, sa = run()
    b, sb = run()
    assert a == b and sa == sb


def test_level_numbers_are_defined_once():
    assert level.AP_PER_TURN == 4 and level.MAX_STEPS == 3
