"""계획 실행·판정·적 턴 (설계서 §1.5~§1.7, §2.6, §2.7)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from promptgame.domain import level
from promptgame.domain.narrate import AIM_NAMES, damage_text, josa, name, num, num_range, pos_text, roll_text
from promptgame.domain.plan import Plan
from promptgame.domain.state import GameState, Unit, cells_next_to, distance, find_path
from promptgame.domain.validate import (
    Rejection,
    StepCheck,
    Validation,
    apply_without_rolls,
    check_step,
    enemy_hit_chance,
    validate_plan,
)


@dataclass
class Event:
    """한 줄의 결과 설명과 재현·기록용 세부 값."""

    text: str
    data: dict = field(default_factory=dict)


@dataclass
class TurnResult:
    validation: Validation
    events: list[Event] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.validation.accepted


def roll(rng: random.Random) -> int:
    return rng.randint(1, level.DICE_SIDES)


def _damage(base: int, multiplier: float, bonus: int, armor: int) -> int:
    return max(1, math.floor(base * multiplier) + bonus - armor)


def _check_win(state: GameState) -> bool:
    if not state.alive_enemies():
        state.outcome = "win"
        return True
    return False


def _hit_enemy(state: GameState, target: Unit, chance: int, base: int, multiplier: float, bonus: int,
               aim: str, burn: bool, rng: random.Random, prefix: str) -> Event:
    dice = roll(rng)
    hit = dice <= chance
    data = {"type": "player_attack", "target": target.uid, "chance": chance, "dice": dice, "hit": hit}
    text = f"{prefix} → {name(target.kind)}: {roll_text(chance, dice, hit)}"
    state.last_attacked = target.uid
    if not hit:
        return Event(text, data)
    before = target.hp
    dmg = _damage(base, multiplier, bonus, target.armor)
    target.hp = max(0, target.hp - dmg)
    text += f" {damage_text(dmg, before, target.hp)}"
    data.update(damage=dmg, hp_before=before, hp_after=target.hp)
    effects = []
    if not target.alive:
        effects.append("쓰러짐")
    else:
        if aim == "head":
            target.statuses["stagger"] = level.STAGGER_TURNS
            effects.append("비틀거림")
        elif aim == "arm":
            target.statuses["arm_injury"] = 1
            effects.append("팔 부상")
        elif aim == "leg":
            target.statuses["leg_injury"] = level.LEG_INJURY_TURNS
            effects.append(f"다리 부상 {level.LEG_INJURY_TURNS}턴")
        if burn:
            target.statuses["burning"] = level.FIREBALL_BURN_TURNS
            effects.append(f"불타는 {level.FIREBALL_BURN_TURNS}턴")
    if effects:
        text += " · " + " · ".join(effects)
        data["effects"] = effects
    return Event(text, data)


def _apply_step(state: GameState, check: StepCheck, rng: random.Random) -> list[Event]:
    st = check.step
    head = num(check.index)
    start = state.player.pos
    apply_without_rolls(state, check)
    if st.act in ("move", "dash"):
        verb = "돌진" if st.act == "dash" else "이동"
        if not check.path:
            return [Event(f"{head} {verb}: 이미 그 자리예요", {"type": "move", "from": list(start), "to": list(start)})]
        return [Event(f"{head} {verb} {pos_text(start)}→{pos_text(state.player.pos)}",
                      {"type": "move", "from": list(start), "to": list(state.player.pos), "ap": check.ap})]
    if st.act == "attack":
        target = state.enemy(check.target)
        mult = level.HEAD_DAMAGE_MULTIPLIER if st.aim == "head" else 1
        bonus = level.STRONG_DAMAGE_BONUS if st.power == "strong" else 0
        return [_hit_enemy(state, target, check.chances[target.uid], state.player.weapon_damage, mult, bonus,
                           st.aim, False, rng, f"{head} {check.label.split(' → ')[0]}")]
    if st.act == "skill":
        events = []
        for uid, chance in check.chances.items():
            target = state.enemy(uid)
            events.append(_hit_enemy(state, target, chance, state.player.weapon_damage, 1, 0, "none", False, rng, f"{head} 돌려베기"))
        return events
    if st.act == "cast":
        target = state.enemy(check.target)
        ev = _hit_enemy(state, target, check.chances[target.uid], level.FIREBALL_DAMAGE, 1, 0, "none", True, rng, f"{head} 화염구")
        return [ev]
    if st.act == "use_item" and st.item == "potion":
        before = state.player.hp
        state.player.hp = min(state.player.max_hp, before + level.POTION_HEAL)
        healed = state.player.hp - before
        return [Event(f"{head} 치유 물약: 체력 +{healed} ({before}→{state.player.hp}) · 남은 물약 {state.potions}",
                      {"type": "potion", "hp_before": before, "hp_after": state.player.hp})]
    if st.act == "use_item":
        target = state.enemy(check.target)
        mult = level.HEAD_DAMAGE_MULTIPLIER if st.aim == "head" else 1
        prefix = f"{head} {AIM_NAMES[st.aim] + ' 조준 ' if st.aim != 'none' else ''}단검 투척"
        ev = _hit_enemy(state, target, check.chances[target.uid], level.KNIFE_DAMAGE, mult, 0, st.aim, False, rng, prefix)
        ev.text += f" · 남은 단검 {state.knives}"
        return [ev]
    if st.act == "guard":
        return [Event(f"{head} 방어 자세: 다음 적 턴까지 회피 +{level.GUARD_EVASION_MOD}", {"type": "guard"})]
    return [Event(f"{head} 대기: 남은 AP {state.ap}를 버리고 턴을 끝내요", {"type": "wait"})]


def execute_plan(state: GameState, plan: Plan, validation: Validation, rng: random.Random) -> list[Event]:
    """수락된 계획을 실제 상태에서 실행한다. 단계마다 전제를 다시 검사하고, 깨지면 그 단계부터 취소한다."""
    events: list[Event] = []
    steps = list(plan.steps)
    for i, st in enumerate(steps):
        check = check_step(state, st, validation.targets, i)
        reason = None
        if isinstance(check, Rejection):
            reason = check.message
        elif check.ap > state.ap:
            reason = f"AP가 부족해요 ({check.ap} 필요, 남은 AP {state.ap})"
        if reason is not None:
            events.append(Event(f"{num_range(i, len(steps) - 1)} 취소: {reason} · 남은 AP {state.ap}",
                                {"type": "cancel", "from_step": i, "reason": reason, "ap_left": state.ap}))
            break
        events.extend(_apply_step(state, check, rng))
        if _check_win(state):
            break
    return events


def _move_enemy(state: GameState, enemy: Unit) -> Event | None:
    if enemy.statuses.get("stagger", 0) > 0 or enemy.statuses.get("leg_injury", 0) > 0:
        return None
    if distance(enemy.pos, state.player.pos) == 1:
        return None
    path = find_path(state, enemy, cells_next_to(state, state.player.pos))
    if not path:
        return None
    points = enemy.move_points
    start = enemy.pos
    for p in path:
        cost = level.MOVE_COST[state.terrain(p)]
        if cost > points:
            break
        points -= cost
        enemy.pos = p
    if enemy.pos == start:
        return None
    return Event(f"적 턴: {name(enemy.kind)} 이동 {pos_text(start)}→{pos_text(enemy.pos)}",
                 {"type": "enemy_move", "enemy": enemy.uid, "from": list(start), "to": list(enemy.pos)})


def _enemy_attack(state: GameState, enemy: Unit, rng: random.Random) -> Event:
    chance = enemy_hit_chance(state, enemy)
    dice = roll(rng)
    hit = dice <= chance
    text = f"적 턴: {name(enemy.kind)} 공격 → 용병: {roll_text(chance, dice, hit)}"
    data = {"type": "enemy_attack", "enemy": enemy.uid, "chance": chance, "dice": dice, "hit": hit}
    if hit:
        weapon = enemy.weapon_damage
        if enemy.statuses.get("arm_injury"):
            weapon = max(1, weapon - level.ARM_DAMAGE_PENALTY)
        dmg = max(1, weapon - state.player.armor)
        before = state.player.hp
        state.player.hp = max(0, before - dmg)
        text += f" {damage_text(dmg, before, state.player.hp)}"
        data.update(damage=dmg, hp_before=before, hp_after=state.player.hp)
    return Event(text, data)


def enemy_turn(state: GameState, rng: random.Random) -> list[Event]:
    """고블린, 오크 순서로 불타는 피해 → 이동 → 인접하면 공격 (설계서 §1.7)."""
    events: list[Event] = []
    for kind in level.ENEMY_ORDER:
        for enemy in [e for e in state.enemies if e.kind == kind]:
            if not enemy.alive:
                continue
            if enemy.statuses.get("burning", 0) > 0:
                before = enemy.hp
                enemy.hp = max(0, before - level.BURN_DAMAGE)
                text = f"적 턴: {name(enemy.kind)} 불타는 피해 {level.BURN_DAMAGE} ({before}→{enemy.hp})"
                if not enemy.alive:
                    text += " · 쓰러짐"
                events.append(Event(text, {"type": "burn", "enemy": enemy.uid, "hp_before": before, "hp_after": enemy.hp}))
                if not enemy.alive:
                    if _check_win(state):
                        return events
                    continue
            moved = _move_enemy(state, enemy)
            if moved:
                events.append(moved)
            if distance(enemy.pos, state.player.pos) == 1:
                events.append(_enemy_attack(state, enemy, rng))
                if not state.player.alive:
                    state.outcome = "lose"
                    return events
    return events


def end_turn(state: GameState) -> None:
    for enemy in state.enemies:
        for key in ("stagger", "burning", "leg_injury"):
            if key in enemy.statuses:
                enemy.statuses[key] -= 1
                if enemy.statuses[key] <= 0:
                    del enemy.statuses[key]
    state.dashed = False
    state.guarding = False
    state.whirlwind_cooldown = max(0, state.whirlwind_cooldown - 1)
    state.turn += 1
    state.ap = level.AP_PER_TURN


def play_turn(state: GameState, plan: Plan, rng: random.Random) -> TurnResult:
    """계획 검증 → 실행 → 적 턴 → 턴 끝. 거부되면 상태·AP·턴·난수를 바꾸지 않는다."""
    return run_validated(state, plan, validate_plan(state, plan), rng)


def run_validated(state: GameState, plan: Plan, validation: Validation, rng: random.Random) -> TurnResult:
    """이미 검증한 계획을 실행 → 적 턴 → 턴 끝까지 처리한다. 검증 뒤 상태가 바뀌지 않았을 때만 부른다."""
    result = TurnResult(validation)
    if not validation.accepted or state.outcome is not None:
        return result
    result.events.extend(execute_plan(state, plan, validation, rng))
    if state.outcome is None:
        result.events.extend(enemy_turn(state, rng))
    if state.outcome is None:
        end_turn(state)
    elif state.outcome == "win":
        result.events.append(Event(f"승리! 적을 모두 쓰러뜨렸어요 ({state.turn}턴)", {"type": "outcome", "outcome": "win"}))
    else:
        result.events.append(Event(f"패배… {josa('용병', '이/가')} 쓰러졌어요 ({state.turn}턴)", {"type": "outcome", "outcome": "lose"}))
    return result
