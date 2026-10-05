"""대상 확정 (설계서 §2.4). 계획 시작 시점의 상태로 대상 표현마다 한 적을 정한다."""

from __future__ import annotations

from dataclasses import dataclass

from promptgame.domain.narrate import josa, name, pos_text
from promptgame.domain.plan import Plan, TargetRef
from promptgame.domain.state import GameState, Unit, distance


@dataclass(frozen=True)
class TargetError:
    code: str  # ambiguous / not_found
    message: str
    candidates: tuple[str, ...] = ()


def _ambiguous(units: list[Unit]) -> TargetError:
    listed = " · ".join(f"{name(u.kind)} {pos_text(u.pos)}" for u in units)
    kinds = sorted({u.kind for u in units}, key=lambda k: ("goblin", "orc").index(k))
    if len(kinds) > 1:
        hint = " 또는 ".join(f"'{name(k)}'" for k in kinds) + "처럼 대상을 적어 주세요"
    else:
        hint = "'가장 가까운', '불타는'처럼 어느 적인지 적어 주세요"
    return TargetError("ambiguous", f"누구를 말하는지 정할 수 없어요: {listed}. {hint}", tuple(u.uid for u in units))


def _default_choice(state: GameState, cands: list[Unit]) -> Unit | TargetError:
    if len(cands) == 1:
        return cands[0]
    adjacent = [u for u in cands if distance(state.player.pos, u.pos) == 1]
    if len(adjacent) == 1:
        return adjacent[0]
    for u in cands:
        if u.uid == state.last_attacked:
            return u
    best = min(distance(state.player.pos, u.pos) for u in cands)
    nearest = [u for u in cands if distance(state.player.pos, u.pos) == best]
    if len(nearest) == 1:
        return nearest[0]
    return _ambiguous(cands)


def _extreme(cands: list[Unit], key, pick) -> Unit | TargetError:
    best = pick(key(u) for u in cands)
    chosen = [u for u in cands if key(u) == best]
    return chosen[0] if len(chosen) == 1 else _ambiguous(chosen)


def resolve_target(state: GameState, ref: TargetRef) -> Unit | TargetError:
    alive = state.alive_enemies()
    cands = alive if ref.kind == "enemy" else [u for u in alive if u.kind == ref.kind]
    if not cands:
        if ref.kind == "enemy":
            return TargetError("not_found", "남은 적이 없어요")
        return TargetError("not_found", f"{josa(name(ref.kind), '은/는')} 이미 쓰러졌어요")
    p = state.player.pos
    rel = ref.relation
    if rel is None:
        return _default_choice(state, cands)
    if rel == "nearest":
        return _extreme(cands, lambda u: distance(p, u.pos), min)
    if rel == "farthest":
        return _extreme(cands, lambda u: distance(p, u.pos), max)
    if rel == "lowest_hp":
        return _extreme(cands, lambda u: u.hp, min)
    if rel == "last_attacked":
        for u in cands:
            if u.uid == state.last_attacked:
                return u
        return TargetError("not_found", "마지막으로 공격한 적이 없어요")
    if rel in ("burning", "staggered"):
        status = "burning" if rel == "burning" else "stagger"
        filtered = [u for u in cands if u.statuses.get(status, 0) > 0]
        if not filtered:
            return TargetError("not_found", "그런 상태의 적이 없어요")
        return _default_choice(state, filtered)
    side = {
        "north": lambda u: u.pos[1] < p[1],
        "south": lambda u: u.pos[1] > p[1],
        "east": lambda u: u.pos[0] > p[0],
        "west": lambda u: u.pos[0] < p[0],
    }[rel]
    filtered = [u for u in cands if side(u)]
    if not filtered:
        return TargetError("not_found", "그쪽에는 적이 없어요")
    return _default_choice(state, filtered)


def resolve_plan_targets(state: GameState, plan: Plan) -> dict[TargetRef, str] | TargetError:
    """계획 안의 대상 표현을 모두 확정한다. 같은 표현은 같은 적을 가리킨다.

    종류가 enemy이고 관계가 없는 표현("녀석")은 계획 시작 시 한 번 정한 적으로 고정되며,
    이동 뒤 가까운 적이 바뀌어도 바꾸지 않는다.
    """
    resolved: dict[TargetRef, str] = {}
    for ref in plan.target_refs():
        if ref in resolved:
            continue
        result = resolve_target(state, ref)
        if isinstance(result, TargetError):
            return result
        resolved[ref] = result.uid
    return resolved
