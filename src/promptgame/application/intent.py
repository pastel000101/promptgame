"""AI 응답 형식과 형식 검증 (설계서 §2.2). 규칙 검증은 domain이 따로 한다."""

from __future__ import annotations

import json
from dataclasses import dataclass

from promptgame.domain import level
from promptgame.domain.plan import (
    ABILITIES,
    ACTS,
    AIMS,
    ITEMS,
    MOVE_DIRECTIONS,
    POWERS,
    RELATIONS,
    TARGET_KINDS,
    MoveSpec,
    Plan,
    Step,
    TargetRef,
)

CLARIFY_VALUES = ("ambiguous", "unrelated", "too_many_steps")


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_TARGET = {
    "type": "object",
    "properties": {
        "kind": {"enum": list(TARGET_KINDS)},
        "relation": {"enum": list(RELATIONS) + [None]},
    },
    "required": ["kind", "relation"],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "maxItems": level.MAX_STEPS,
            "items": {
                "type": "object",
                "properties": {
                    "act": {"enum": list(ACTS)},
                    "target": _nullable(_TARGET),
                    "move": _nullable({
                        "type": "object",
                        "properties": {
                            "toward": _nullable(_TARGET),
                            "away_from": _nullable(_TARGET),
                            "direction": {"enum": list(MOVE_DIRECTIONS) + [None]},
                            "cells": _nullable({"type": "integer", "minimum": 1}),
                        },
                        "required": ["toward", "away_from", "direction", "cells"],
                    }),
                    "aim": {"enum": list(AIMS)},
                    "power": {"enum": list(POWERS)},
                    "ability": {"enum": list(ABILITIES) + [None]},
                    "item": {"enum": list(ITEMS) + [None]},
                },
                "required": ["act", "target", "move", "aim", "power", "ability", "item"],
            },
        },
        "clarify": {"enum": list(CLARIFY_VALUES) + [None]},
    },
    "required": ["steps", "clarify"],
}


@dataclass(frozen=True)
class Clarify:
    reason: str


class FormatError(ValueError):
    pass


def _enum(value, allowed, field: str, nullable: bool = False):
    if value is None and nullable:
        return None
    if value not in allowed:
        raise FormatError(f"{field}={value!r}")
    return value


def _target(raw, field: str) -> TargetRef | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FormatError(f"{field} is not an object")
    return TargetRef(_enum(raw.get("kind"), TARGET_KINDS, f"{field}.kind"),
                     _enum(raw.get("relation"), RELATIONS, f"{field}.relation", nullable=True))


def _step(raw, i: int) -> Step:
    if not isinstance(raw, dict):
        raise FormatError(f"steps[{i}] is not an object")
    act = _enum(raw.get("act"), ACTS, f"steps[{i}].act")
    target = _target(raw.get("target"), f"steps[{i}].target")
    move = None
    raw_move = raw.get("move")
    if raw_move is not None:
        if not isinstance(raw_move, dict):
            raise FormatError(f"steps[{i}].move is not an object")
        cells = raw_move.get("cells")
        if cells is not None and (not isinstance(cells, int) or isinstance(cells, bool) or cells < 1):
            raise FormatError(f"steps[{i}].move.cells={cells!r}")
        move = MoveSpec(
            toward=_target(raw_move.get("toward"), f"steps[{i}].move.toward"),
            away_from=_target(raw_move.get("away_from"), f"steps[{i}].move.away_from"),
            direction=_enum(raw_move.get("direction"), MOVE_DIRECTIONS, f"steps[{i}].move.direction", nullable=True),
            cells=cells,
        )
    step = Step(
        act=act,
        target=target,
        move=move,
        aim=_enum(raw.get("aim", "none"), AIMS, f"steps[{i}].aim"),
        power=_enum(raw.get("power", "normal"), POWERS, f"steps[{i}].power"),
        ability=_enum(raw.get("ability"), ABILITIES, f"steps[{i}].ability", nullable=True),
        item=_enum(raw.get("item"), ITEMS, f"steps[{i}].item", nullable=True),
    )
    _check_required(step, i)
    return step


def _check_required(step: Step, i: int) -> None:
    where = f"steps[{i}]"
    if step.act in ("move", "dash"):
        if step.move is None:
            raise FormatError(f"{where}: move required")
        chosen = [x for x in (step.move.toward, step.move.away_from, step.move.direction) if x is not None]
        if len(chosen) != 1:
            raise FormatError(f"{where}: exactly one of toward/away_from/direction")
    elif step.act == "attack":
        if step.target is None:
            raise FormatError(f"{where}: target required")
    elif step.act == "skill":
        if step.ability != "whirlwind":
            raise FormatError(f"{where}: skill needs ability=whirlwind")
    elif step.act == "cast":
        if step.ability != "fireball" or step.target is None:
            raise FormatError(f"{where}: cast needs ability=fireball and target")
    elif step.act == "use_item":
        if step.item is None:
            raise FormatError(f"{where}: item required")
        if step.item == "throwing_knife" and step.target is None:
            raise FormatError(f"{where}: throwing_knife needs target")


def parse_response(text: str) -> Plan | Clarify:
    """응답 문자열을 계획 또는 되묻기로 바꾼다. 형식이 틀리면 FormatError."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FormatError(f"not json: {exc}") from exc
    if not isinstance(data, dict) or "steps" not in data or "clarify" not in data:
        raise FormatError("missing steps/clarify")
    clarify = _enum(data["clarify"], CLARIFY_VALUES, "clarify", nullable=True)
    steps = data["steps"]
    if not isinstance(steps, list):
        raise FormatError("steps is not a list")
    if clarify is not None:
        # 되묻기가 있으면 함께 온 단계는 실행하지 않고 버린다(상태를 바꾸지 않는 쪽).
        return Clarify(clarify)
    if not 1 <= len(steps) <= level.MAX_STEPS:
        raise FormatError(f"steps count {len(steps)}")
    return Plan(tuple(_step(raw, i) for i, raw in enumerate(steps)))
