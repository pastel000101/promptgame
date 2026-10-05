"""게임 상태, 좌표, 시야, 경로 (설계서 §1.1, §1.2, §2.4)."""

from __future__ import annotations

import copy
import heapq
from dataclasses import dataclass, field

from promptgame.domain import level

Pos = tuple[int, int]

# 동률일 때의 탐색 순서: 북 → 동 → 남 → 서
DIRECTIONS: dict[str, Pos] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
DIRECTION_ORDER = ("N", "E", "S", "W")


@dataclass
class Unit:
    uid: str
    kind: str  # player / goblin / orc
    pos: Pos
    hp: int
    max_hp: int
    accuracy: int
    evasion: int
    armor: int
    weapon_damage: int
    move_points: int = 0
    # 적 상태: stagger·burning·leg_injury는 남은 턴 수, arm_injury는 1이면 부상
    statuses: dict[str, int] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class GameState:
    grid: tuple[str, ...]
    player: Unit
    enemies: list[Unit]
    mana: int
    ap: int
    potions: int
    knives: int
    whirlwind_cooldown: int = 0
    dashed: bool = False  # 돌진 직후: 이번 턴 공격 −10, 다음 적 턴까지 회피 −10
    guarding: bool = False  # 방어 자세: 다음 적 턴까지 회피 +20
    turn: int = 1
    last_attacked: str | None = None
    outcome: str | None = None  # None / "win" / "lose"

    def copy(self) -> GameState:
        return copy.deepcopy(self)

    # 지형
    def terrain(self, pos: Pos) -> str:
        x, y = pos
        if not (0 <= x < level.WIDTH and 0 <= y < level.HEIGHT):
            return level.WALL
        return self.grid[y][x]

    def move_cost(self, pos: Pos) -> int | None:
        return level.MOVE_COST[self.terrain(pos)]

    # 유닛
    def alive_enemies(self) -> list[Unit]:
        return [e for e in self.enemies if e.alive]

    def enemy(self, uid: str) -> Unit:
        for e in self.enemies:
            if e.uid == uid:
                return e
        raise KeyError(uid)

    def unit_at(self, pos: Pos) -> Unit | None:
        if self.player.alive and self.player.pos == pos:
            return self.player
        for e in self.alive_enemies():
            if e.pos == pos:
                return e
        return None

    def adjacent_enemies(self, pos: Pos | None = None) -> list[Unit]:
        p = self.player.pos if pos is None else pos
        return [e for e in self.alive_enemies() if distance(p, e.pos) == 1]


def new_game() -> GameState:
    s = level.PLAYER_STATS
    player = Unit("player", "player", level.PLAYER_START, s["hp"], s["hp"], s["accuracy"], s["evasion"], s["armor"], s["weapon_damage"])
    enemies = []
    for kind, pos in level.ENEMY_STARTS:
        e = level.ENEMY_STATS[kind]
        enemies.append(Unit(kind, kind, pos, e["hp"], e["hp"], e["accuracy"], e["evasion"], e["armor"], e["weapon_damage"], e["move_points"]))
    return GameState(
        grid=level.MAP_ROWS,
        player=player,
        enemies=enemies,
        mana=s["mana"],
        ap=level.AP_PER_TURN,
        potions=level.PLAYER_POTIONS,
        knives=level.PLAYER_KNIVES,
    )


def distance(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step(pos: Pos, direction: str) -> Pos:
    dx, dy = DIRECTIONS[direction]
    return (pos[0] + dx, pos[1] + dy)


def line_cells(a: Pos, b: Pos) -> list[Pos]:
    """브레젠햄 직선이 지나는 칸 (양 끝 포함)."""
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    cells = []
    while True:
        cells.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return cells
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def has_sight(state: GameState, a: Pos, b: Pos) -> bool:
    """시작·대상 칸을 뺀 직선 위 칸에 벽·덤불이 없으면 보인다. 인접이면 검사하지 않는다."""
    if distance(a, b) <= 1:
        return True
    return all(state.terrain(c) not in level.BLOCKS_SIGHT for c in line_cells(a, b)[1:-1])


def sight_blocker(state: GameState, a: Pos, b: Pos) -> str | None:
    if distance(a, b) <= 1:
        return None
    for c in line_cells(a, b)[1:-1]:
        t = state.terrain(c)
        if t in level.BLOCKS_SIGHT:
            return t
    return None


def _passable(state: GameState, pos: Pos, mover: Unit, allowed: set[str] | None) -> bool:
    t = state.terrain(pos)
    if level.MOVE_COST[t] is None:
        return False
    if allowed is not None and t not in allowed:
        return False
    occupant = state.unit_at(pos)
    return occupant is None or occupant is mover


def find_path(
    state: GameState,
    mover: Unit,
    goals: set[Pos],
    allowed: set[str] | None = None,
    unit_cost: bool = False,
) -> list[Pos] | None:
    """mover 위치에서 goals 중 하나까지 최소 비용 경로(시작 칸 제외).

    비용이 같은 경로는 북→동→남→서 순서로 먼저 나아가는 쪽을 고른다.
    unit_cost가 참이면 칸 수만 센다(돌진). allowed가 있으면 그 지형만 지난다.
    다른 캐릭터가 있는 칸은 지나거나 도착할 수 없다.
    """
    goals = {g for g in goals if _passable(state, g, mover, allowed)}
    if not goals:
        return None
    if mover.pos in goals:
        return []

    def cost_into(p: Pos) -> int:
        return 1 if unit_cost else level.MOVE_COST[state.terrain(p)]

    # 목표에서 거꾸로 각 칸의 남은 비용을 구한다.
    remaining: dict[Pos, int] = {}
    heap = [(0, g) for g in goals]
    heapq.heapify(heap)
    while heap:
        d, p = heapq.heappop(heap)
        if p in remaining:
            continue
        remaining[p] = d
        for name in DIRECTION_ORDER:
            q = step(p, name)
            if q in remaining or not _passable(state, q, mover, allowed):
                continue
            heapq.heappush(heap, (d + cost_into(p), q))
    if mover.pos not in remaining:
        return None
    path: list[Pos] = []
    cur = mover.pos
    while remaining[cur] > 0:
        for name in DIRECTION_ORDER:
            q = step(cur, name)
            if q in remaining and remaining[q] + cost_into(q) == remaining[cur]:
                path.append(q)
                cur = q
                break
    return path


def path_cost(state: GameState, path: list[Pos]) -> int:
    return sum(level.MOVE_COST[state.terrain(p)] for p in path)


def cells_next_to(state: GameState, target: Pos) -> set[Pos]:
    return {step(target, d) for d in DIRECTION_ORDER}
