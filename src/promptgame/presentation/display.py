"""표시 상태 (설계서 §4.2). 실제 게임 상태의 사본으로, 연출이 이벤트를 재생하며 갱신한다.

연출이 끝나면 sync()로 실제 상태와 같게 맞춘다. 규칙 계산은 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from promptgame.domain.state import GameState


@dataclass
class DisplayUnit:
    uid: str
    kind: str
    gx: float
    gy: float
    hp: int
    max_hp: int
    alive: bool = True
    statuses: dict[str, int] = field(default_factory=dict)
    facing: int = 1
    # 연출용 일시 변형
    dx: float = 0.0  # 화면 픽셀 오프셋
    dy: float = 0.0
    tilt: float = 0.0  # 전체 기울기(도)
    upper: float = 0.0  # 상체 회전(도), 공격 동작
    flash: float = 0.0  # 0~1 흰 번쩍임
    alpha: int = 255
    lying: bool = False  # 쓰러짐
    ghosts: list[tuple[float, float, int]] = field(default_factory=list)  # 돌진 잔상 (gx, gy, alpha)

    @property
    def pos(self) -> tuple[float, float]:
        return self.gx, self.gy

    def reset_transform(self) -> None:
        self.dx = self.dy = self.tilt = self.upper = self.flash = 0.0
        self.ghosts = []


@dataclass
class DisplayState:
    units: dict[str, DisplayUnit]
    guarding: bool = False
    dashed: bool = False
    turn: int = 1

    @classmethod
    def from_game(cls, state: GameState) -> "DisplayState":
        ds = cls({})
        ds.sync(state)
        return ds

    def unit(self, uid: str) -> DisplayUnit:
        return self.units[uid]

    @property
    def player(self) -> DisplayUnit:
        return self.units["player"]

    def sync(self, state: GameState) -> None:
        """실제 상태와 같게 맞춘다. 연출 변형은 지운다."""
        px = state.player.pos[0]
        for unit in [state.player] + list(state.enemies):
            du = self.units.get(unit.uid)
            if du is None:
                facing = 1 if unit.kind == "player" else (-1 if unit.pos[0] >= px else 1)
                du = DisplayUnit(unit.uid, unit.kind, unit.pos[0], unit.pos[1], unit.hp, unit.max_hp, facing=facing)
                self.units[unit.uid] = du
            du.gx, du.gy = float(unit.pos[0]), float(unit.pos[1])
            du.hp, du.max_hp = unit.hp, unit.max_hp
            du.alive = unit.alive
            du.statuses = dict(unit.statuses)
            du.lying = not unit.alive
            du.alpha = 120 if not unit.alive else 255
            du.reset_transform()
        self.guarding = state.guarding
        self.dashed = state.dashed
        self.turn = state.turn

    def face_toward(self, uid: str, gx: float) -> None:
        du = self.units[uid]
        if abs(gx - du.gx) > 0.01:
            du.facing = 1 if gx > du.gx else -1

    def matches(self, state: GameState, strict: bool = True) -> bool:
        """자동 테스트용: 위치·체력·생존이 실제 상태와 같은가. strict면 상태 효과·수식 상태까지 같아야 한다.

        턴 끝의 상태 지속 감소는 규칙이라 연출이 계산하지 않고, 연출이 끝난 뒤 sync()로 맞춘다.
        """
        for unit in [state.player] + list(state.enemies):
            du = self.units.get(unit.uid)
            if du is None:
                return False
            if (round(du.gx), round(du.gy)) != unit.pos or du.hp != unit.hp or du.alive != unit.alive:
                return False
            if strict and du.statuses != unit.statuses:
                return False
        if strict:
            return self.guarding == state.guarding and self.dashed == state.dashed
        return True
