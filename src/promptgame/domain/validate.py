"""계획 검증·비용·명중률 (설계서 §1.3~§1.5, §2.5).

검증은 상태 사본 위에서 단계를 순서대로 모의 실행한다. 실제 상태와 난수 생성기는 건드리지 않고,
명중·피해처럼 주사위로 정해지는 결과는 미리 확정하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from promptgame.domain import level
from promptgame.domain.narrate import DIRECTION_NAMES, TERRAIN_NAMES, attack_label, josa, name, num
from promptgame.domain.plan import Plan, Step, TargetRef
from promptgame.domain.state import (
    DIRECTION_ORDER,
    GameState,
    Pos,
    Unit,
    cells_next_to,
    distance,
    find_path,
    path_cost,
    sight_blocker,
)
from promptgame.domain.state import step as step_pos
from promptgame.domain.targeting import TargetError, resolve_plan_targets


@dataclass
class StepCheck:
    index: int
    step: Step
    ap: int
    label: str
    mana: int = 0
    target: str | None = None
    path: list[Pos] = field(default_factory=list)
    dash: bool = False
    chances: dict[str, int] = field(default_factory=dict)

    def cost_text(self) -> str:
        parts = [str(self.ap)]
        if self.mana:
            parts.append(f"마나 {self.mana}")
        if len(self.chances) == 1:
            parts.append(f"명중 {next(iter(self.chances.values()))}%")
        elif self.chances:
            parts.append("명중 " + " · ".join(f"{name(uid)} {c}%" for uid, c in self.chances.items()))
        return "(" + ", ".join(parts) + ")"


@dataclass
class Rejection:
    index: int | None
    code: str
    message: str
    alternative: str | None = None
    candidates: tuple[str, ...] = ()

    def line(self) -> str:
        if self.code == "ambiguous":
            return f"다시 입력: {self.message}"
        head = f"거부: {num(self.index)} {self.message}" if self.index is not None else f"거부: {self.message}"
        return head + "." + (f" {self.alternative}." if self.alternative else "")


@dataclass
class Validation:
    accepted: bool
    checks: list[StepCheck]
    total_ap: int
    rejection: Rejection | None = None
    targets: dict[TargetRef, str] = field(default_factory=dict)

    def line(self) -> str:
        if not self.accepted:
            return self.rejection.line()
        body = " ".join(f"{num(c.index)} {c.label} {c.cost_text()}" for c in self.checks)
        text = f"계획 {self.total_ap}/{level.AP_PER_TURN} AP: {body}"
        unused = level.AP_PER_TURN - self.total_ap
        if unused > 0 and not any(c.step.act == "wait" for c in self.checks):
            text += f" · 남은 AP {unused} 미사용"
        return text

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "total_ap": self.total_ap,
            "steps": [
                {"index": c.index, "label": c.label, "ap": c.ap, "mana": c.mana, "target": c.target,
                 "path": [list(p) for p in c.path], "chances": c.chances}
                for c in self.checks
            ],
            "rejection": None
            if self.rejection is None
            else {"index": self.rejection.index, "code": self.rejection.code, "message": self.rejection.message,
                  "alternative": self.rejection.alternative, "candidates": list(self.rejection.candidates)},
            "line": self.line(),
        }


def clamp_hit(chance: int) -> int:
    return max(level.HIT_MIN, min(level.HIT_MAX, chance))


def player_hit_chance(state: GameState, target: Unit, action_mod: int) -> int:
    chance = state.player.accuracy + action_mod - target.evasion
    if state.dashed:
        chance += level.DASH_ATTACK_MOD
    if target.statuses.get("stagger", 0) > 0:
        chance += level.STAGGERED_TARGET_MOD
    if state.terrain(target.pos) == level.BUSH:
        chance += level.BUSH_TARGET_MOD
    return clamp_hit(chance)


def enemy_hit_chance(state: GameState, enemy: Unit) -> int:
    evasion = state.player.evasion
    if state.dashed:
        evasion += level.DASH_EVASION_MOD
    if state.guarding:
        evasion += level.GUARD_EVASION_MOD
    chance = enemy.accuracy - evasion
    if enemy.statuses.get("stagger", 0) > 0:
        chance += level.STAGGERED_ATTACKER_MOD
    return clamp_hit(chance)


def modifier_ap(step: Step) -> int:
    return (level.AIM_AP if step.aim != "none" else 0) + (level.STRONG_AP if step.power == "strong" else 0)


def base_ap(step: Step) -> int:
    """경로와 무관한 동작의 AP. 이동·돌진은 0으로 본다(대안 안내용)."""
    if step.act == "attack":
        return level.ATTACK_AP + modifier_ap(step)
    if step.act == "skill":
        return level.WHIRLWIND_AP
    if step.act == "cast":
        return level.FIREBALL_AP
    if step.act == "use_item":
        return level.POTION_AP if step.item == "potion" else level.KNIFE_AP + modifier_ap(step)
    if step.act == "guard":
        return level.GUARD_AP
    return 0


_NEXT_ACTION_TEXT = {
    "attack": "공격할",
    "skill": "돌려베기를 쓸",
    "cast": "화염구를 쓸",
    "use_item": "아이템을 쓸",
    "guard": "방어 자세를 잡을",
}


def _reject(index: int, code: str, message: str, alternative: str | None = None) -> Rejection:
    return Rejection(index, code, message, alternative)


def _down(index: int, target: Unit) -> Rejection:
    return _reject(index, "target_down", f"{josa(name(target.kind), '이/가')} 이미 쓰러졌어요")


def _target_unit(state: GameState, targets: dict[TargetRef, str], ref: TargetRef | None) -> Unit | None:
    if ref is None:
        return None
    return state.enemy(targets[ref])


def _walk_alternative(state: GameState, walk: list[Pos], used_ap: int, rest_steps: list[Step]) -> str:
    cost = path_cost(state, walk)
    muds = sum(1 for p in walk if state.terrain(p) == level.MUD)
    mud_text = f"진흙 {muds}칸에 " if muds else ""
    if used_ap + cost > level.AP_PER_TURN:
        return f"걸어가면 {mud_text}{cost} AP가 들어 이번 턴에는 닿을 수 없어요"
    rest = sum(base_ap(s) for s in rest_steps)
    if rest_steps and used_ap + cost + rest > level.AP_PER_TURN:
        what = _NEXT_ACTION_TEXT.get(rest_steps[0].act, "다음 행동을 할")
        return f"걸어가면 {mud_text}{cost} AP가 들어 이번 턴에는 {what} 수 없어요"
    return f"걸어가면 {mud_text}{cost} AP예요"


def _first_non_dash_terrain(state: GameState, path: list[Pos]) -> str | None:
    for p in path:
        t = state.terrain(p)
        if t not in level.DASH_ALLOWED:
            return t
    return None


def _check_move(state: GameState, st: Step, index: int, targets, used_ap: int, rest: list[Step]) -> StepCheck | Rejection:
    spec = st.move
    dash = st.act == "dash"
    verb = "돌진" if dash else "이동"
    if st.aim != "none" or st.power == "strong":
        return _reject(index, "modifier", f"{verb}에는 조준·강타를 붙일 수 없어요")
    if spec is None or sum(x is not None for x in (spec.toward, spec.away_from, spec.direction)) != 1:
        return _reject(index, "move_spec", "어디로 움직일지 하나만 정해 주세요")
    if spec.cells is not None and spec.cells < 1:
        return _reject(index, "move_spec", "움직일 칸 수는 1 이상이어야 해요")
    player = state.player
    allowed = level.DASH_ALLOWED if dash else None

    if spec.toward is not None:
        target = _target_unit(state, targets, spec.toward)
        if not target.alive:
            return _down(index, target)
        goals = cells_next_to(state, target.pos)
        if dash:
            path = find_path(state, player, goals, allowed=allowed, unit_cost=True)
            if path is not None and spec.cells is not None:
                path = path[: spec.cells]
            if path is None or len(path) > level.DASH_MAX_CELLS:
                walk = find_path(state, player, goals)
                if walk is not None and spec.cells is not None:
                    walk = walk[: spec.cells]
                bad = _first_non_dash_terrain(state, walk) if walk is not None else None
                if bad is not None and (path is None or len(walk) <= level.DASH_MAX_CELLS):
                    return _reject(index, "terrain", f"돌진은 {TERRAIN_NAMES[bad]}에 들어갈 수 없어요",
                                   _walk_alternative(state, walk, used_ap, rest))
                if path is not None:
                    return _reject(index, "dash_range",
                                   f"돌진은 한 번에 {level.DASH_MAX_CELLS}칸까지예요 ({len(path)}칸 필요)")
                return _reject(index, "no_path", f"{name(target.kind)} 옆으로 갈 길이 없어요")
        else:
            path = find_path(state, player, goals)
            if path is None:
                return _reject(index, "no_path", f"{name(target.kind)} 옆으로 갈 길이 없어요")
            if spec.cells is not None:
                path = path[: spec.cells]
        end = path[-1] if path else player.pos
        where = "옆" if distance(end, target.pos) == 1 else "쪽"
        label = f"{verb} {len(path)}칸 → {name(target.kind)} {where}"
        return _move_check(state, st, index, path, dash, label)

    if spec.away_from is not None:
        enemy = _target_unit(state, targets, spec.away_from)
        if not enemy.alive:
            return _down(index, enemy)
        cells = spec.cells or 1
        path = _retreat_path(state, enemy, cells, allowed)
        if len(path) < cells:
            return _reject(index, "no_retreat", f"{name(enemy.kind)}에게서 {cells}칸 물러날 곳이 없어요")
        dirs = {_direction_of(a, b) for a, b in zip([player.pos] + path, path)}
        dir_text = f"{DIRECTION_NAMES[dirs.pop()]}으로 " if len(dirs) == 1 else ""
        label = f"{'돌진: ' if dash else ''}{name(enemy.kind)}에게서 {dir_text}{cells}칸"
        return _move_check(state, st, index, path, dash, label)

    cells = spec.cells or 1
    path: list[Pos] = []
    cur = player.pos
    for n in range(1, cells + 1):
        cur = step_pos(cur, spec.direction)
        t = state.terrain(cur)
        occupant = state.unit_at(cur)
        where = f"{DIRECTION_NAMES[spec.direction]} {n}칸째"
        if level.MOVE_COST[t] is None:
            return _reject(index, "blocked", f"{where}는 벽이라 갈 수 없어요")
        if occupant is not None:
            return _reject(index, "blocked", f"{where}에 {josa(name(occupant.kind), '이/가')} 있어 갈 수 없어요")
        if dash and t not in level.DASH_ALLOWED:
            return _reject(index, "terrain", f"돌진은 {TERRAIN_NAMES[t]}에 들어갈 수 없어요")
        path.append(cur)
    label = f"{verb} {DIRECTION_NAMES[spec.direction]}으로 {cells}칸"
    return _move_check(state, st, index, path, dash, label)


def _direction_of(a: Pos, b: Pos) -> str:
    for d in DIRECTION_ORDER:
        if step_pos(a, d) == b:
            return d
    raise ValueError((a, b))


def _retreat_path(state: GameState, enemy: Unit, cells: int, allowed: set[str] | None) -> list[Pos]:
    """적과의 맨해튼 거리를 가장 크게 늘리는 칸으로 한 칸씩 물러난다 (설계서 §2.4).

    동률이면 적과 플레이어의 차이가 큰 축의 반대 방향(같으면 가로축), 그다음 북→동→남→서.
    """
    path: list[Pos] = []
    cur = state.player.pos
    for _ in range(cells):
        dx = cur[0] - enemy.pos[0]
        dy = cur[1] - enemy.pos[1]
        if abs(dx) >= abs(dy):
            preferred = "E" if dx > 0 else "W"
        else:
            preferred = "S" if dy > 0 else "N"
        best = None
        for order, d in enumerate(DIRECTION_ORDER):
            q = step_pos(cur, d)
            t = state.terrain(q)
            if level.MOVE_COST[t] is None or (allowed is not None and t not in allowed):
                continue
            occupant = state.unit_at(q)
            if occupant is not None and occupant is not state.player:
                continue
            key = (distance(q, enemy.pos), d == preferred, -order)
            if best is None or key > best[0]:
                best = (key, q)
        if best is None or best[0][0] <= distance(cur, enemy.pos):
            break
        cur = best[1]
        path.append(cur)
    return path


def _move_check(state: GameState, st: Step, index: int, path: list[Pos], dash: bool, label: str) -> StepCheck | Rejection:
    if dash:
        if len(path) > level.DASH_MAX_CELLS:
            return _reject(index, "dash_range", f"돌진은 한 번에 {level.DASH_MAX_CELLS}칸까지예요 ({len(path)}칸 필요)")
        ap = math.ceil(len(path) / level.DASH_CELLS_PER_AP)
    else:
        ap = path_cost(state, path)
    return StepCheck(index, st, ap, label, path=list(path), dash=dash and bool(path))


def _check_reach(state: GameState, index: int, target: Unit, max_range: int | None, what: str) -> Rejection | None:
    d = distance(state.player.pos, target.pos)
    if max_range is None:
        if d != 1:
            return _reject(index, "not_adjacent", f"{josa(name(target.kind), '이/가')} 옆에 없어요 (거리 {d})")
        return None
    if d > max_range:
        return _reject(index, "out_of_range", f"{what} 사거리 {max_range}를 넘어요 ({name(target.kind)}까지 거리 {d})")
    blocker = sight_blocker(state, state.player.pos, target.pos)
    if blocker is not None:
        return _reject(index, "no_sight", f"{TERRAIN_NAMES[blocker]}에 가려 {josa(name(target.kind), '이/가')} 보이지 않아요")
    return None


def check_step(
    state: GameState,
    st: Step,
    targets: dict[TargetRef, str],
    index: int,
    used_ap: int = 0,
    rest: list[Step] | None = None,
) -> StepCheck | Rejection:
    """한 단계를 주어진 상태에서 실행할 수 있는지 검사하고 비용·명중률을 계산한다. 상태를 바꾸지 않는다."""
    rest = rest or []
    act = st.act
    if act in ("move", "dash"):
        return _check_move(state, st, index, targets, used_ap, rest)

    if act == "attack":
        target = _target_unit(state, targets, st.target)
        if target is None:
            return _reject(index, "no_target", "공격할 대상을 정해 주세요")
        if not target.alive:
            return _down(index, target)
        err = _check_reach(state, index, target, None, "")
        if err:
            return err
        mod = (level.AIM_HIT_MOD if st.aim != "none" else 0) + (level.STRONG_HIT_MOD if st.power == "strong" else 0)
        chance = player_hit_chance(state, target, mod)
        label = f"{attack_label(st.aim, st.power)} → {name(target.kind)}"
        return StepCheck(index, st, level.ATTACK_AP + modifier_ap(st), label, target=target.uid, chances={target.uid: chance})

    if act == "skill":
        if st.ability != "whirlwind":
            return _reject(index, "no_ability", "스킬은 돌려베기만 쓸 수 있어요")
        if st.aim != "none" or st.power == "strong":
            return _reject(index, "modifier", "돌려베기에는 조준·강타를 붙일 수 없어요")
        if state.whirlwind_cooldown > 0:
            return _reject(index, "cooldown", f"돌려베기는 재사용 대기 중이에요 ({state.whirlwind_cooldown}턴 남음)")
        adjacent = state.adjacent_enemies()
        if not adjacent:
            return _reject(index, "not_adjacent", "옆에 적이 없어 돌려베기를 쓸 수 없어요")
        chances = {e.uid: player_hit_chance(state, e, level.WHIRLWIND_HIT_MOD) for e in adjacent}
        label = "돌려베기 → " + "·".join(name(e.kind) for e in adjacent)
        return StepCheck(index, st, level.WHIRLWIND_AP, label, chances=chances)

    if act == "cast":
        if st.ability != "fireball":
            return _reject(index, "no_ability", "마법은 화염구만 쓸 수 있어요")
        if st.aim != "none" or st.power == "strong":
            return _reject(index, "modifier", "화염구에는 조준·강타를 붙일 수 없어요")
        if state.mana < level.FIREBALL_MANA:
            return _reject(index, "no_mana", f"마나가 부족해요 ({state.mana}/{level.FIREBALL_MANA})")
        target = _target_unit(state, targets, st.target)
        if target is None:
            return _reject(index, "no_target", "화염구를 던질 대상을 정해 주세요")
        if not target.alive:
            return _down(index, target)
        err = _check_reach(state, index, target, level.FIREBALL_RANGE, "화염구")
        if err:
            return err
        chance = player_hit_chance(state, target, level.FIREBALL_HIT_MOD)
        return StepCheck(index, st, level.FIREBALL_AP, f"화염구 → {name(target.kind)}", mana=level.FIREBALL_MANA,
                         target=target.uid, chances={target.uid: chance})

    if act == "use_item":
        if st.item == "potion":
            if st.aim != "none" or st.power == "strong":
                return _reject(index, "modifier", "치유 물약에는 조준·강타를 붙일 수 없어요")
            if state.potions < 1:
                return _reject(index, "no_item", "치유 물약이 없어요")
            return StepCheck(index, st, level.POTION_AP, "치유 물약")
        if st.item == "throwing_knife":
            if st.power == "strong":
                return _reject(index, "modifier", "투척 단검에는 강타를 붙일 수 없어요")
            if state.knives < 1:
                return _reject(index, "no_item", "투척 단검이 없어요")
            target = _target_unit(state, targets, st.target)
            if target is None:
                return _reject(index, "no_target", "단검을 던질 대상을 정해 주세요")
            if not target.alive:
                return _down(index, target)
            err = _check_reach(state, index, target, level.KNIFE_RANGE, "투척 단검")
            if err:
                return err
            mod = level.AIM_HIT_MOD if st.aim != "none" else 0
            chance = player_hit_chance(state, target, mod)
            label = f"{attack_label(st.aim, 'normal', '단검 투척')} → {name(target.kind)}"
            return StepCheck(index, st, level.KNIFE_AP + modifier_ap(st), label, target=target.uid, chances={target.uid: chance})
        return _reject(index, "no_item", "가방에 없는 아이템이에요")

    if act in ("guard", "wait"):
        if st.aim != "none" or st.power == "strong":
            return _reject(index, "modifier", "조준·강타는 공격에만 붙일 수 있어요")
        if act == "guard":
            return StepCheck(index, st, level.GUARD_AP, "방어 자세")
        if rest:
            return _reject(index, "wait_not_last", "대기 뒤에는 다른 행동을 할 수 없어요")
        return StepCheck(index, st, level.WAIT_AP, "대기")

    return _reject(index, "unknown_act", "알 수 없는 동작이에요")


def apply_without_rolls(state: GameState, check: StepCheck) -> None:
    """주사위와 무관한 변화(위치, 돌진·방어 상태, AP·마나·아이템, 재사용 대기)를 적용한다."""
    st = check.step
    state.ap -= check.ap
    if check.path:
        state.player.pos = check.path[-1]
    if check.dash:
        state.dashed = True
    if st.act == "cast":
        state.mana -= level.FIREBALL_MANA
    elif st.act == "skill":
        # 사용한 턴이 끝날 때 한 번 줄어들므로 1을 더해 둔다.
        state.whirlwind_cooldown = level.WHIRLWIND_COOLDOWN + 1
    elif st.act == "use_item":
        if st.item == "potion":
            state.potions -= 1
        else:
            state.knives -= 1
    elif st.act == "guard":
        state.guarding = True


def validate_plan(state: GameState, plan: Plan) -> Validation:
    """계획 전체를 사본 위에서 모의 실행한다. 한 단계라도 안 되면 계획 전체를 거부한다."""
    targets = resolve_plan_targets(state, plan)
    if isinstance(targets, TargetError):
        code = "ambiguous" if targets.code == "ambiguous" else "target"
        return Validation(False, [], 0, Rejection(None, code, targets.message, candidates=targets.candidates))
    sim = state.copy()
    checks: list[StepCheck] = []
    used = 0
    steps = list(plan.steps)
    for i, st in enumerate(steps):
        result = check_step(sim, st, targets, i, used, steps[i + 1:])
        if isinstance(result, Rejection):
            return Validation(False, checks, used, result, targets)
        checks.append(result)
        used += result.ap
        apply_without_rolls(sim, result)
    if used > level.AP_PER_TURN:
        detail = ", ".join(f"{num(c.index)} {c.label} {c.ap}" for c in checks)
        rejection = Rejection(None, "ap", f"AP {used} 필요 ({detail}), 한 턴에 {level.AP_PER_TURN}까지예요",
                              _partial_move_hint(state, checks))
        return Validation(False, checks, used, rejection, targets)
    return Validation(True, checks, used, None, targets)


def _partial_move_hint(state: GameState, checks: list[StepCheck]) -> str | None:
    """걸어서 다가가는 단계가 AP를 넘길 때, 이번 턴에 갈 수 있는 칸 수를 안내한다."""
    before = 0
    for c in checks:
        move = c.step.move
        if c.step.act == "move" and move is not None and move.toward is not None and c.ap > level.AP_PER_TURN - before:
            budget = level.AP_PER_TURN - before
            spent = cells = 0
            for p in c.path:
                spent += level.MOVE_COST[state.terrain(p)]
                if spent > budget:
                    break
                cells += 1
            if cells > 0:
                return f"'{cells}칸 다가가'처럼 칸 수를 적으면 이번 턴에 {cells}칸까지 갈 수 있어요"
            return None
        before += c.ap
    return None
