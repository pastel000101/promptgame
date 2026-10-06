"""연출 큐 (설계서 §4.2~§4.4).

domain이 확정한 TurnResult.events를 순서대로 연출 단계(Cue)로 바꾸고 시간을 진행한다.
난수를 뽑거나 피해를 다시 적용하지 않는다. 표시 상태(DisplayState)만 바꾼다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from promptgame.domain import level
from promptgame.domain.resolve import Event
from promptgame.presentation.assets import UNIT_HEIGHT_IN_CELLS
from promptgame.presentation.display import DisplayState, DisplayUnit

# 시간(초). 설계서 §4.4의 값.
MOVE_PER_CELL = 0.18
MUD_PER_CELL = 0.30
DASH_PER_CELL = 0.09
LUNGE = 0.12
SWING = 0.20
STRONG_EXTRA = 0.10
AIM_MARK = 0.15
WHIRL = 0.30
FIREBALL_CAST = 0.20
FIREBALL_FLY = 0.35
KNIFE_FLY = 0.25
POTION = 0.40
GUARD = 0.20
WAIT = 0.30
HIT = 0.40
MISS = 0.30
DEATH = 0.40
BANNER = 0.40
BURN = 0.30
OUTCOME = 0.60
CANCEL = 0.50
GAP = 0.08

_effects_rng = random.Random(0)  # 파티클 모양만 흔든다. 판정과 무관하다.


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 2


def ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: float
    additive: bool = False
    gravity: float = 0.0


@dataclass
class Popup:
    x: float
    y: float
    text: str
    color: tuple[int, int, int]
    life: float
    max_life: float
    big: bool = True


@dataclass
class Fx:
    """프레임마다 그려지는 효과의 현재 상태."""

    particles: list[Particle] = field(default_factory=list)
    popups: list[Popup] = field(default_factory=list)
    slash: tuple[float, float, float, int, float] | None = None  # (x, y, progress, facing, thickness)
    whirl: tuple[float, float, float, float] | None = None  # (x, y, progress, radius)
    projectile: tuple[str, float, float, float] | None = None  # (kind, x, y, progress)
    aim_mark: tuple[float, float, float] | None = None  # (x, y, progress)
    guard_ring: str | None = None  # uid
    banner: tuple[str, float] | None = None  # (text, progress)
    shake: float = 0.0
    active_enemy: str | None = None
    fade: float = 0.0  # 0~1 검은 덮개
    fade_in: bool = False  # 다시 시작: 검은 화면에서 밝아진다

    def tick(self, dt: float) -> None:
        if self.fade_in:
            self.fade = max(0.0, self.fade - dt / 0.3)
            if self.fade <= 0:
                self.fade_in = False
        for p in self.particles:
            p.life -= dt
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
        self.particles = [p for p in self.particles if p.life > 0]
        for q in self.popups:
            q.life -= dt
            q.y -= 28 * dt
        self.popups = [q for q in self.popups if q.life > 0]
        self.shake = max(0.0, self.shake - dt * 12)

    def burst(self, x: float, y: float, n: int, color, speed: float, life: float, size: float,
              additive: bool = False, gravity: float = 0.0, up: bool = False) -> None:
        for _ in range(n):
            a = _effects_rng.random() * math.tau
            s = speed * (0.4 + _effects_rng.random())
            vx, vy = math.cos(a) * s, math.sin(a) * s
            if up:
                vy = -abs(vy)
            self.particles.append(Particle(x, y, vx, vy, life * (0.6 + _effects_rng.random() * 0.6), life, color, size, additive, gravity))

    def popup(self, x: float, y: float, text: str, color, big: bool = True) -> None:
        self.popups.append(Popup(x, y, text, color, 0.9, 0.9, big))


class Cue:
    """한 연출 단계. duration 동안 update(t)가 불리고 끝나면 end()가 불린다."""

    duration = 0.0
    line: str | None = None  # 계획 줄에 보여 줄 문장

    def start(self, ds: DisplayState, fx: Fx, cam) -> None:
        pass

    def update(self, t: float, ds: DisplayState, fx: Fx, cam) -> None:
        pass

    def end(self, ds: DisplayState, fx: Fx, cam) -> None:
        pass


class Delay(Cue):
    def __init__(self, seconds: float):
        self.duration = seconds


class MoveCue(Cue):
    def __init__(self, uid: str, path: list[tuple[int, int]], dash: bool, terrain, line: str):
        self.uid, self.path, self.dash, self.terrain, self.line = uid, [tuple(p) for p in path], dash, terrain, line
        self.segments: list[float] = []
        for p in self.path:
            per = DASH_PER_CELL if dash else (MUD_PER_CELL if terrain(p) == level.MUD else MOVE_PER_CELL)
            self.segments.append(per)
        self.duration = sum(self.segments) or 0.01

    def start(self, ds, fx, cam):
        du = ds.unit(self.uid)
        self.origin = (du.gx, du.gy)
        if self.path:
            ds.face_toward(self.uid, self.path[-1][0])
            if self.dash:
                fx_x, fx_y = cam.foot(du.gx, du.gy)
                fx.burst(fx_x, fx_y, 10, (190, 170, 130), 60, 0.4, 4, gravity=-30, up=True)

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        elapsed = 0.0
        prev = self.origin
        for cell, seg in zip(self.path, self.segments):
            if t <= elapsed + seg:
                k = ease_in_out((t - elapsed) / seg)
                du.gx = prev[0] + (cell[0] - prev[0]) * k
                du.gy = prev[1] + (cell[1] - prev[1]) * k
                du.dy = -abs(math.sin(k * math.pi)) * (3 if self.dash else 5)
                du.tilt = (6 if self.dash else 3) * du.facing * math.sin(k * math.pi)
                break
            elapsed += seg
            prev = cell
        if self.dash and t > 0.05:
            du.ghosts = [(du.gx - (du.gx - self.origin[0]) * 0.12, du.gy - (du.gy - self.origin[1]) * 0.12, 90),
                         (du.gx - (du.gx - self.origin[0]) * 0.24, du.gy - (du.gy - self.origin[1]) * 0.24, 50)]

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        if self.path:
            du.gx, du.gy = float(self.path[-1][0]), float(self.path[-1][1])
        du.reset_transform()
        if self.dash:
            ds.dashed = True


class AttackCue(Cue):
    """내딛기 → 상체 휘두르기 → 궤적. 피격·빗나감 반응은 다음 Cue가 맡는다."""

    def __init__(self, uid: str, target_pos: tuple[int, int], strong: bool, aim: str, line: str, enemy: bool = False):
        self.uid, self.target, self.strong, self.aim, self.line, self.enemy = uid, target_pos, strong, aim, line, enemy
        self.duration = (AIM_MARK if aim != "none" else 0) + LUNGE + SWING + (STRONG_EXTRA if strong else 0)

    def start(self, ds, fx, cam):
        ds.face_toward(self.uid, self.target[0])
        if self.enemy:
            fx.active_enemy = self.uid

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        tx, ty = cam.foot(self.target[0], self.target[1])
        t0 = AIM_MARK if self.aim != "none" else 0
        if t < t0:
            fx.aim_mark = (tx, ty, t / t0)
            return
        fx.aim_mark = None
        t -= t0
        if t < LUNGE:
            k = ease_out(t / LUNGE)
            du.dx = 14 * du.facing * k
            du.upper = -18 * k * du.facing  # 뒤로 젖혀 준비
            return
        t -= LUNGE
        swing = SWING + (STRONG_EXTRA if self.strong else 0)
        k = min(1.0, t / swing)
        du.dx = 14 * du.facing * (1 - k * 0.5)
        du.upper = (-18 + 44 * ease_out(k)) * du.facing  # 앞으로 휘두름
        fx.slash = (tx, ty - cam.cell_width(self.target[1]) * 0.55, k, du.facing, 1.6 if self.strong else 1.0)
        if self.strong and k > 0.3:
            fx.shake = max(fx.shake, 0.5)

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.dx = du.dy = du.tilt = 0.0
        du.upper = 0.0
        fx.slash = None
        fx.aim_mark = None


class WhirlCue(Cue):
    def __init__(self, uid: str, line: str):
        self.uid, self.line = uid, line
        self.duration = WHIRL

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        k = t / WHIRL
        du.upper = math.sin(k * math.pi) * 30 * du.facing
        du.tilt = -math.sin(k * math.pi) * 6 * du.facing
        x, y = cam.foot(du.gx, du.gy)
        fx.whirl = (x, y - cam.cell_width(du.gy) * 0.45, k, cam.cell_width(du.gy) * 1.1)

    def end(self, ds, fx, cam):
        ds.unit(self.uid).reset_transform()
        fx.whirl = None


class ProjectileCue(Cue):
    def __init__(self, kind: str, uid: str, target_pos: tuple[int, int], hit: bool, line: str):
        self.kind, self.uid, self.target, self.hit, self.line = kind, uid, target_pos, hit, line
        self.cast = FIREBALL_CAST if kind == "fireball" else 0.08
        self.fly = FIREBALL_FLY if kind == "fireball" else KNIFE_FLY
        self.duration = self.cast + self.fly

    def start(self, ds, fx, cam):
        ds.face_toward(self.uid, self.target[0])
        du = ds.unit(self.uid)
        hx, hy = self._hand(ds, cam)
        if self.kind == "fireball":
            fx.burst(hx, hy, 12, (255, 170, 60), 30, 0.3, 3, additive=True)

    def _hand(self, ds, cam):
        du = ds.unit(self.uid)
        x, y = cam.foot(du.gx, du.gy)
        h = cam.cell_width(du.gy) * UNIT_HEIGHT_IN_CELLS[du.kind]
        return x + du.facing * h * 0.22, y - h * 0.62

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        hx, hy = self._hand(ds, cam)
        tx, ty = cam.foot(self.target[0], self.target[1])
        ty -= cam.cell_width(self.target[1]) * 1.0
        if t < self.cast:
            du.upper = -10 * du.facing * (t / self.cast)
            fx.projectile = (self.kind, hx, hy, 0.0)
            return
        k = min(1.0, (t - self.cast) / self.fly)
        du.upper = 12 * du.facing * (1 - k)
        # 빗나가면 대상을 지나쳐 날아간다
        end_k = k if self.hit else k * 1.35
        x = hx + (tx - hx) * end_k
        y = hy + (ty - hy) * end_k
        fx.projectile = (self.kind, x, y, k)
        if self.kind == "fireball":
            fx.burst(x, y, 2, (255, 120, 40), 20, 0.25, 6, additive=True)

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.upper = 0.0
        tx, ty = cam.foot(self.target[0], self.target[1])
        ty -= cam.cell_width(self.target[1]) * 1.0
        if self.kind == "fireball":
            if self.hit:
                fx.burst(tx, ty, 40, (255, 150, 50), 180, 0.5, 7, additive=True, gravity=120)
                fx.shake = 0.4
            else:
                mx = tx + (tx - cam.foot(du.gx, du.gy)[0]) * 0.35
                fx.burst(mx, ty, 14, (120, 110, 100), 40, 0.6, 8)
        fx.projectile = None


class HitCue(Cue):
    def __init__(self, uid: str, from_pos, damage: int, hp_after: int, effects: list[str], line: str | None):
        self.uid, self.from_pos, self.damage, self.hp_after, self.effects, self.line = uid, from_pos, damage, hp_after, effects, line
        self.duration = HIT

    def start(self, ds, fx, cam):
        du = ds.unit(self.uid)
        x, y = cam.foot(du.gx, du.gy)
        h = cam.cell_width(du.gy)
        fx.burst(x, y - h * 0.8, 10, (255, 240, 200), 120, 0.3, 3)
        fx.popup(x, y - h * 1.4, f"-{self.damage}", (255, 228, 150))
        for i, eff in enumerate(e for e in self.effects if e != "쓰러짐"):
            fx.popup(x + 46, y - h * 1.25 + i * 20, eff, (240, 200, 110), big=False)

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        k = t / HIT
        du.flash = max(0.0, 1 - k * 4)
        away = 1 if du.gx >= self.from_pos[0] else -1
        du.dx = 8 * away * (1 - ease_out(k))

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.hp = self.hp_after
        du.flash = 0.0
        du.dx = 0.0
        for eff in self.effects:
            if eff == "비틀거림":
                du.statuses["stagger"] = level.STAGGER_TURNS
            elif eff == "팔 부상":
                du.statuses["arm_injury"] = 1
            elif eff.startswith("다리 부상"):
                du.statuses["leg_injury"] = level.LEG_INJURY_TURNS
            elif eff.startswith("불타는"):
                du.statuses["burning"] = level.FIREBALL_BURN_TURNS


class MissCue(Cue):
    def __init__(self, uid: str, line: str | None):
        self.uid, self.line = uid, line
        self.duration = MISS

    def start(self, ds, fx, cam):
        du = ds.unit(self.uid)
        x, y = cam.foot(du.gx, du.gy)
        fx.popup(x, y - cam.cell_width(du.gy) * 1.3, "빗나감", (200, 200, 200), big=False)

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        du.dx = -6 * du.facing * math.sin(min(1.0, t / MISS) * math.pi)

    def end(self, ds, fx, cam):
        ds.unit(self.uid).dx = 0.0


class DeathCue(Cue):
    def __init__(self, uid: str):
        self.uid = uid
        self.duration = DEATH

    def update(self, t, ds, fx, cam):
        du = ds.unit(self.uid)
        k = ease_out(min(1.0, t / DEATH))
        du.tilt = -78 * k * du.facing
        du.alpha = int(255 - 135 * k)

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.alive = False
        du.lying = True
        du.alpha = 120
        du.tilt = 0.0
        du.statuses = {}


class PotionCue(Cue):
    def __init__(self, uid: str, healed: int, hp_after: int, line: str):
        self.uid, self.healed, self.hp_after, self.line = uid, healed, hp_after, line
        self.duration = POTION

    def start(self, ds, fx, cam):
        du = ds.unit(self.uid)
        x, y = cam.foot(du.gx, du.gy)
        h = cam.cell_width(du.gy)
        fx.burst(x, y - h * 0.6, 18, (140, 230, 120), 40, 0.6, 4, gravity=-60, up=True)
        fx.popup(x, y - h * 1.4, f"+{self.healed}", (150, 230, 130))

    def update(self, t, ds, fx, cam):
        ds.unit(self.uid).dy = -4 * math.sin(min(1.0, t / POTION) * math.pi)

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.hp = self.hp_after
        du.dy = 0.0


class GuardCue(Cue):
    def __init__(self, uid: str, line: str):
        self.uid, self.line = uid, line
        self.duration = GUARD

    def end(self, ds, fx, cam):
        ds.guarding = True
        fx.guard_ring = self.uid


class WaitCue(Cue):
    def __init__(self, uid: str, line: str):
        self.uid, self.line = uid, line
        self.duration = WAIT

    def update(self, t, ds, fx, cam):
        ds.unit(self.uid).dy = 4 * math.sin(min(1.0, t / WAIT) * math.pi)

    def end(self, ds, fx, cam):
        ds.unit(self.uid).dy = 0.0


class BannerCue(Cue):
    def __init__(self, text: str, seconds: float = BANNER):
        self.text = text
        self.duration = seconds

    def update(self, t, ds, fx, cam):
        fx.banner = (self.text, min(1.0, t / self.duration))

    def end(self, ds, fx, cam):
        fx.banner = None


class BurnCue(Cue):
    def __init__(self, uid: str, hp_after: int, line: str):
        self.uid, self.hp_after, self.line = uid, hp_after, line
        self.duration = BURN

    def start(self, ds, fx, cam):
        du = ds.unit(self.uid)
        x, y = cam.foot(du.gx, du.gy)
        h = cam.cell_width(du.gy)
        fx.burst(x, y - h * 0.7, 16, (255, 140, 50), 40, 0.5, 5, additive=True, gravity=-80, up=True)
        fx.popup(x, y - h * 1.4, f"-{level.BURN_DAMAGE}", (255, 170, 90))

    def end(self, ds, fx, cam):
        du = ds.unit(self.uid)
        du.hp = self.hp_after
        if du.hp <= 0:
            du.alive = False
            du.lying = True
            du.alpha = 120
            du.statuses = {}


class TextCue(Cue):
    """취소·승패처럼 글자만 보여 주는 단계."""

    def __init__(self, line: str, seconds: float):
        self.line = line
        self.duration = seconds


class OutcomeCue(Cue):
    def __init__(self, outcome: str, line: str):
        self.outcome, self.line = outcome, line
        self.duration = OUTCOME

    def update(self, t, ds, fx, cam):
        fx.fade = 0.45 * min(1.0, t / OUTCOME)


class TurnEndCue(Cue):
    """턴이 끝나며 풀리는 플레이어 수식 상태 표시를 지운다. 상태 지속 감소는 실제 상태와 동기화할 때 반영된다."""

    duration = 0.01

    def end(self, ds, fx, cam):
        ds.dashed = False
        ds.guarding = False
        fx.guard_ring = None


class EnemyActive(Cue):
    def __init__(self, uid: str | None):
        self.uid = uid
        self.duration = 0.01

    def end(self, ds, fx, cam):
        fx.active_enemy = self.uid


def _line_for(event: Event) -> str:
    return event.text


def build_cues(events: list[Event], ds: DisplayState, terrain) -> list[Cue]:
    """이벤트 목록을 연출 단계 목록으로 바꾼다. 순서는 이벤트 순서 그대로다."""
    cues: list[Cue] = []
    enemy_phase = False
    for ev in events:
        d = ev.data
        kind = d.get("type")
        line = _line_for(ev)
        if kind in ("enemy_move", "enemy_attack", "burn") and not enemy_phase:
            enemy_phase = True
            cues.append(BannerCue("적 턴"))
        if kind == "move":
            cues.append(MoveCue("player", d.get("path", []), d.get("act") == "dash", terrain, line))
        elif kind == "player_attack":
            act = d.get("act", "attack")
            target = d["target"]
            tpos = tuple(d.get("target_pos", (0, 0)))
            if act == "skill":
                if not any(isinstance(c, WhirlCue) for c in cues[-3:]):
                    cues.append(WhirlCue("player", line))
            elif act == "cast":
                cues.append(ProjectileCue("fireball", "player", tpos, d["hit"], line))
            elif act == "use_item":
                cues.append(ProjectileCue("knife", "player", tpos, d["hit"], line))
            else:
                cues.append(AttackCue("player", tpos, d.get("power") == "strong", d.get("aim", "none"), line))
            cues.extend(_reaction(target, tuple(d.get("attacker_pos", (0, 0))), d, line))
        elif kind == "potion":
            cues.append(PotionCue("player", d["healed"], d["hp_after"], line))
        elif kind == "guard":
            cues.append(GuardCue("player", line))
        elif kind == "wait":
            cues.append(WaitCue("player", line))
        elif kind == "cancel":
            cues.append(TextCue(line, CANCEL))
        elif kind == "enemy_move":
            cues.append(EnemyActive(d["enemy"]))
            cues.append(MoveCue(d["enemy"], d.get("path", []), False, terrain, line))
        elif kind == "enemy_attack":
            cues.append(EnemyActive(d["enemy"]))
            cues.append(AttackCue(d["enemy"], tuple(d.get("target_pos", (0, 0))), False, "none", line, enemy=True))
            cues.extend(_reaction("player", tuple(d.get("attacker_pos", (0, 0))), d, line))
        elif kind == "burn":
            cues.append(EnemyActive(d["enemy"]))
            cues.append(BurnCue(d["enemy"], d["hp_after"], line))
        elif kind == "outcome":
            cues.append(EnemyActive(None))
            if d["outcome"] == "lose":
                cues.append(DeathCue("player"))
            cues.append(OutcomeCue(d["outcome"], line))
        cues.append(Delay(GAP))
    cues.append(EnemyActive(None))
    if not any(isinstance(c, OutcomeCue) for c in cues):
        cues.append(TurnEndCue())
    return cues


def _reaction(target: str, from_pos, d: dict, line: str) -> list[Cue]:
    if not d.get("hit"):
        return [MissCue(target, line)]
    effects = d.get("effects", [])
    out: list[Cue] = [HitCue(target, from_pos, d.get("damage", 0), d.get("hp_after", 0), effects, line)]
    if "쓰러짐" in effects or d.get("hp_after", 1) <= 0:
        out.append(DeathCue(target))
    return out


class Animator:
    """연출 큐를 프레임마다 진행한다."""

    def __init__(self, display: DisplayState, cam):
        self.display = display
        self.cam = cam
        self.fx = Fx()
        self.cues: list[Cue] = []
        self.index = 0
        self.t = 0.0
        self.current_line: str | None = None
        self.played_lines: list[str] = []  # 이미 보여 준 결과 줄 (아직 재생하지 않은 결과는 띄우지 않는다)
        self._started = False

    @property
    def running(self) -> bool:
        return self.index < len(self.cues)

    def start(self, events: list[Event], terrain) -> None:
        self.cues = build_cues(events, self.display, terrain)
        self.index = 0
        self.t = 0.0
        self._started = False
        self.played_lines = []

    def clear(self) -> None:
        self.cues = []
        self.index = 0
        self.fx = Fx()
        self.current_line = None
        self.played_lines = []

    def restart_fade(self) -> None:
        """새 판: 검게 덮었다가 0.3초에 걸쳐 밝아진다."""
        self.fx.fade = 1.0
        self.fx.fade_in = True

    def update(self, dt: float) -> None:
        self.fx.tick(dt)
        if not self.running:
            return
        cue = self.cues[self.index]
        if not self._started:
            cue.start(self.display, self.fx, self.cam)
            if cue.line:
                self.current_line = cue.line
                if not self.played_lines or self.played_lines[-1] != cue.line:
                    self.played_lines.append(cue.line)
            self._started = True
        self.t += dt
        if self.t >= cue.duration:
            cue.update(cue.duration, self.display, self.fx, self.cam)
            cue.end(self.display, self.fx, self.cam)
            self.index += 1
            self.t = 0.0
            self._started = False
            return
        cue.update(self.t, self.display, self.fx, self.cam)

    def run_to_end(self, step: float = 1 / 30) -> None:
        guard = 0
        while self.running and guard < 100000:
            self.update(step)
            guard += 1

    def total_duration(self) -> float:
        return sum(c.duration for c in self.cues)
