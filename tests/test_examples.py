"""설계서 §10 대표 상황 예시 E1~E6 재현 (고정 시드).

시드는 예시에 적힌 주사위 값이 나오도록 고른 값이다.
"""

import random

from helpers import ENEMY, GOBLIN, ORC, attack, dash, make_state, move, plan
from promptgame.domain.plan import Step, TargetRef
from promptgame.domain.resolve import play_turn
from promptgame.domain.validate import validate_plan


def texts(result):
    return [e.text for e in result.events]


def test_e1_dash_then_head_attack():
    s = make_state(player=(7, 5), orc=(2, 6))
    p = plan(dash(toward=ENEMY), attack(ENEMY, aim="head"))
    v = validate_plan(s, p)
    assert v.line() == "계획 4/4 AP: ① 돌진 2칸 → 고블린 옆 (1) ② 머리 조준 베기 → 고블린 (3, 명중 35%)"
    r = play_turn(s, p, random.Random(5643))
    assert texts(r) == [
        "① 돌진 (7,5)→(7,3)",
        "② 머리 조준 베기 → 고블린: 명중 35% · 주사위 28 · 명중! 피해 7 (10→3) · 비틀거림",
        "적 턴: 고블린 공격 → 용병: 명중 35% · 주사위 71 · 빗나감",
        "적 턴: 오크 이동 (2,6)→(2,5)",
    ]
    # 턴 끝: 돌진 상태 해제, 비틀거림은 고블린의 턴이 끝나 해제
    assert s.player.pos == (7, 3) and not s.dashed
    assert s.enemy("goblin").hp == 3 and "stagger" not in s.enemy("goblin").statuses
    assert s.turn == 2 and s.ap == 4


def test_e2_fireball():
    s = make_state(orc=(2, 6))
    p = plan(Step("cast", target=ORC, ability="fireball"))
    v = validate_plan(s, p)
    assert v.line() == "계획 2/4 AP: ① 화염구 → 오크 (2, 마나 3, 명중 90%) · 남은 AP 2 미사용"
    r = play_turn(s, p, random.Random(186))
    t = texts(r)
    assert t[0] == "① 화염구 → 오크: 명중 90% · 주사위 44 · 명중! 피해 4 (18→14) · 불타는 2턴"
    assert t[1].startswith("적 턴: 고블린 이동 (7,2)→")  # 고블린이 먼저 움직인다
    assert t[2:] == ["적 턴: 오크 불타는 피해 2 (14→12)", "적 턴: 오크 이동 (2,6)→(2,5)"]
    assert s.mana == 3
    assert s.enemy("orc").statuses["burning"] == 1  # 남은 1턴


def test_e3_potion_then_retreat():
    s = make_state(player=(4, 6), orc=(5, 6), hp=6)
    p = plan(Step("use_item", item="potion"), move(away_from=ENEMY))
    v = validate_plan(s, p)
    assert v.line() == "계획 2/4 AP: ① 치유 물약 (1) ② 오크에게서 서쪽으로 1칸 (1) · 남은 AP 2 미사용"
    r = play_turn(s, p, random.Random(328))
    t = texts(r)
    assert t[:2] == ["① 치유 물약: 체력 +8 (6→14) · 남은 물약 0", "② 이동 (4,6)→(3,6)"]
    assert t[-2:] == ["적 턴: 오크 이동 (5,6)→(4,6)", "적 턴: 오크 공격 → 용병: 명중 40% · 주사위 83 · 빗나감"]
    assert s.potions == 0 and s.player.hp == 14 and s.player.pos == (3, 6)


def test_e4_dash_into_mud_rejected():
    s = make_state(player=(4, 3), goblin=(7, 3))
    before = s.copy()
    rng = random.Random(1)
    rng_state = rng.getstate()
    r = play_turn(s, plan(dash(toward=GOBLIN), attack(GOBLIN)), rng)
    assert not r.accepted and r.events == []
    assert r.validation.line() == (
        "거부: ① 돌진은 진흙에 들어갈 수 없어요. 걸어가면 진흙 2칸에 4 AP가 들어 이번 턴에는 공격할 수 없어요."
    )
    assert s == before and rng.getstate() == rng_state


def test_e5_ap_over_rejected_without_trimming():
    s = make_state(player=(5, 5), orc=(6, 5), goblin=(5, 4))
    before = s.copy()
    r = play_turn(s, plan(attack(ORC, aim="head", power="strong"), attack(GOBLIN)), random.Random(1))
    assert not r.accepted
    assert r.validation.line() == "거부: AP 6 필요 (① 머리 조준 강타 → 오크 4, ② 베기 → 고블린 2), 한 턴에 4까지예요."
    assert s == before


def test_e5_single_strong_head_attack():
    s = make_state(player=(5, 5), orc=(6, 5), goblin=(5, 4))
    p = plan(attack(ORC, aim="head", power="strong"))
    assert validate_plan(s, p).line() == "계획 4/4 AP: ① 머리 조준 강타 → 오크 (4, 명중 50%)"
    r = play_turn(s, p, random.Random(1))  # 첫 주사위 18
    assert texts(r)[0] == "① 머리 조준 강타 → 오크: 명중 50% · 주사위 18 · 명중! 피해 8 (18→10) · 비틀거림"


STAGGERED_GOBLIN = TargetRef("goblin", "staggered")


def e6_state():
    s = make_state(player=(7, 3), orc=(6, 5))
    g = s.enemy("goblin")
    g.hp = 3
    g.statuses["stagger"] = 1
    return s


def test_e6_hit_cancels_second_attack():
    s = e6_state()
    p = plan(attack(STAGGERED_GOBLIN), attack(STAGGERED_GOBLIN))
    assert validate_plan(s, p).line() == "계획 4/4 AP: ① 베기 → 고블린 (2, 명중 80%) ② 베기 → 고블린 (2, 명중 80%)"
    r = play_turn(s, p, random.Random(55))
    assert texts(r) == [
        "① 베기 → 고블린: 명중 80% · 주사위 12 · 명중! 피해 5 (3→0) · 쓰러짐",
        "② 취소: 고블린이 이미 쓰러졌어요 · 남은 AP 2",
        "적 턴: 오크 이동 (6,5)→(6,4)",
    ]
    assert s.enemy("orc").hp == 18  # 취소된 공격을 오크에게 돌리지 않는다


def test_e6_miss_continues_second_attack():
    s = e6_state()
    p = plan(attack(STAGGERED_GOBLIN), attack(STAGGERED_GOBLIN))
    r = play_turn(s, p, random.Random(19))  # 주사위 87, 6
    t = texts(r)
    assert t[0] == "① 베기 → 고블린: 명중 80% · 주사위 87 · 빗나감"
    assert t[1] == "② 베기 → 고블린: 명중 80% · 주사위 6 · 명중! 피해 5 (3→0) · 쓰러짐"
    assert s.enemy("orc").hp == 18
