"""행동 계획 구조: 단계, 수식, 대상 지정 (설계서 §2.2)."""

from __future__ import annotations

from dataclasses import dataclass

ACTS = ("move", "dash", "attack", "skill", "cast", "use_item", "guard", "wait")
TARGET_KINDS = ("goblin", "orc", "enemy")
RELATIONS = ("nearest", "farthest", "last_attacked", "lowest_hp", "burning", "staggered", "north", "south", "east", "west")
MOVE_DIRECTIONS = ("N", "E", "S", "W")
AIMS = ("none", "head", "arm", "leg")
POWERS = ("normal", "strong")
ABILITIES = ("whirlwind", "fireball")
ITEMS = ("potion", "throwing_knife")


@dataclass(frozen=True)
class TargetRef:
    kind: str
    relation: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "relation": self.relation}


@dataclass(frozen=True)
class MoveSpec:
    toward: TargetRef | None = None
    away_from: TargetRef | None = None
    direction: str | None = None
    cells: int | None = None

    def to_dict(self) -> dict:
        return {
            "toward": self.toward.to_dict() if self.toward else None,
            "away_from": self.away_from.to_dict() if self.away_from else None,
            "direction": self.direction,
            "cells": self.cells,
        }


@dataclass(frozen=True)
class Step:
    act: str
    target: TargetRef | None = None
    move: MoveSpec | None = None
    aim: str = "none"
    power: str = "normal"
    ability: str | None = None
    item: str | None = None

    def to_dict(self) -> dict:
        return {
            "act": self.act,
            "target": self.target.to_dict() if self.target else None,
            "move": self.move.to_dict() if self.move else None,
            "aim": self.aim,
            "power": self.power,
            "ability": self.ability,
            "item": self.item,
        }


@dataclass(frozen=True)
class Plan:
    steps: tuple[Step, ...]

    def to_dict(self) -> dict:
        return {"steps": [s.to_dict() for s in self.steps]}

    def target_refs(self) -> list[TargetRef]:
        refs = []
        for s in self.steps:
            if s.target:
                refs.append(s.target)
            if s.move:
                refs.extend(r for r in (s.move.toward, s.move.away_from) if r)
        return refs
