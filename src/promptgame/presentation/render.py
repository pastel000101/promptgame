"""그리기 (설계서 §4.1). 상태·표시 상태·효과를 읽기만 하고 규칙 계산이나 LLM 호출을 하지 않는다.

창 1280×800: 위 1280×720은 장면(배경 그림·캐릭터·효과·HUD), 아래 80px은 계획 줄과 입력창.
상시 격자선·칸별 바닥 무늬는 그리지 않는다. 개발용 격자는 debug가 참일 때만 그린다.
"""

from __future__ import annotations

import math

import pygame

from promptgame.domain import level
from promptgame.domain.narrate import name
from promptgame.presentation import assets as assets_mod
from promptgame.presentation.display import DisplayState, DisplayUnit

BACKDROP_SIZE = (1280, 720)
SCENE_CROP_TOP = 40  # 배경 위쪽 하늘을 잘라 낸다
SCENE_SIZE = (1280, BACKDROP_SIZE[1] - SCENE_CROP_TOP)
WINDOW_SIZE = (1280, 800)
STRIP_TOP = SCENE_SIZE[1]

TEXT = (236, 230, 214)
DIM = (178, 170, 150)
GOLD = (222, 186, 110)
RED = (214, 72, 60)
GREEN = (118, 190, 92)
BLUE = (84, 150, 220)
PANEL = (16, 20, 30, 190)
PANEL_LINE = (150, 122, 70)
STATUS_LONG = {"stagger": "비틀거림", "burning": "불타는", "arm_injury": "팔 부상", "leg_injury": "다리 부상"}
STATUS_COLOR = {"stagger": (240, 200, 110), "burning": (255, 150, 60), "arm_injury": (230, 110, 100), "leg_injury": (230, 110, 100)}


# ---------------------------------------------------------------- 작은 도우미

def _panel(surface, rect: pygame.Rect, alpha: int = 190) -> None:
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    s.fill((16, 20, 30, alpha))
    surface.blit(s, rect.topleft)
    pygame.draw.rect(surface, PANEL_LINE, rect, 1, border_radius=4)


def _text(surface, font, s, pos, color=TEXT, anchor="topleft", shadow=True):
    img = font.render(s, True, color)
    r = img.get_rect(**{anchor: pos})
    if shadow:
        sh = font.render(s, True, (10, 10, 14))
        surface.blit(sh, r.move(1, 1))
    surface.blit(img, r)
    return r


def wrap(font, text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if font.size(cur + ch)[0] > width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def _glow(surface, center, radius, color, steps=8):
    radius = max(2, int(radius))
    g = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for i in range(steps, 0, -1):
        k = i / steps
        col = tuple(int(c * (1 - k) ** 1.6) for c in color)
        pygame.draw.circle(g, col, (radius, radius), int(radius * k))
    surface.blit(g, (int(center[0]) - radius, int(center[1]) - radius), special_flags=pygame.BLEND_RGB_ADD)


def _hp_bar(surface, fonts, cx, top, hp, max_hp, color, width=60):
    bx = cx - width // 2
    pygame.draw.rect(surface, (10, 10, 12), (bx - 1, top - 1, width + 2, 8), border_radius=3)
    pygame.draw.rect(surface, (70, 28, 24), (bx, top, width, 6), border_radius=3)
    if max_hp:
        pygame.draw.rect(surface, color, (bx, top, int(width * max(0, hp) / max_hp), 6), border_radius=3)
    _text(surface, fonts.small, str(max(0, hp)), (bx - 5, top + 3), TEXT, "midright")


# ---------------------------------------------------------------- 장면

class Renderer:
    def __init__(self, assets: assets_mod.Assets, cam, debug: bool = False):
        self.assets = assets
        self.cam = cam
        self.debug = debug
        self.fonts = assets.fonts
        self.scene = pygame.Surface(SCENE_SIZE)

    # ---- 캐릭터
    def _unit_sprite(self, du: DisplayUnit) -> tuple[pygame.Surface, int]:
        height = int(self.cam.cell_width(du.gy) * assets_mod.UNIT_HEIGHT_IN_CELLS[du.kind])
        return self.assets.unit_scaled(du.kind, height, du.facing), height

    def draw_unit(self, surface, du: DisplayUnit, ds: DisplayState) -> pygame.Rect:
        img, height = self._unit_sprite(du)
        fx_x, fy = self.cam.foot(du.gx, du.gy)
        cw = self.cam.cell_width(du.gy)
        fx_x += du.dx
        fy += du.dy
        # 그림자
        sh = pygame.Surface((int(cw * 0.9), int(cw * 0.32)), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0, 0, 0, 95), sh.get_rect())
        surface.blit(sh, sh.get_rect(center=(fx_x, fy - 2)))
        foot_x = assets_mod.UNIT_FOOT_X[du.kind] if du.facing == assets_mod.UNIT_FACING[du.kind] else 1 - assets_mod.UNIT_FOOT_X[du.kind]
        # 잔상
        for gx, gy, alpha in du.ghosts:
            gfx, gfy = self.cam.foot(gx, gy)
            ghost = img.copy()
            ghost.set_alpha(alpha)
            surface.blit(ghost, ghost.get_rect(midbottom=(gfx, gfy)))
        if du.lying:
            lying = pygame.transform.rotozoom(img, 78 * du.facing, 0.92)
            lying.set_alpha(du.alpha)
            rect = lying.get_rect(center=(fx_x, fy - cw * 0.25))
            surface.blit(lying, rect)
            return rect
        rect = img.get_rect()
        rect.bottomleft = (fx_x - img.get_width() * foot_x, fy)
        if du.tilt:
            rotated = pygame.transform.rotozoom(img, du.tilt, 1.0)
            if du.alpha < 255:
                rotated.set_alpha(du.alpha)
            r = rotated.get_rect(midbottom=(fx_x, fy))
            surface.blit(rotated, r)
            rect = r
        elif du.upper:
            waist = int(img.get_height() * assets_mod.UNIT_WAIST[du.kind])
            lower = img.subsurface((0, waist, img.get_width(), img.get_height() - waist))
            upper = img.subsurface((0, 0, img.get_width(), waist))
            surface.blit(lower, (rect.left, rect.top + waist))
            pivot = (rect.left + img.get_width() * foot_x, rect.top + waist)
            rotated = pygame.transform.rotozoom(upper, du.upper, 1.0)
            # 회전 전 허리 기준점이 회전 후 어디로 가는지 계산해 고정한다
            ox = (rect.left + img.get_width() / 2) - pivot[0]
            oy = (rect.top + waist / 2) - pivot[1]
            a = math.radians(du.upper)
            rx = ox * math.cos(a) + oy * math.sin(a)
            ry = -ox * math.sin(a) + oy * math.cos(a)
            r = rotated.get_rect(center=(pivot[0] + rx, pivot[1] + ry))
            surface.blit(rotated, r)
        else:
            if du.alpha < 255:
                img = img.copy()
                img.set_alpha(du.alpha)
            surface.blit(img, rect)
        if du.flash > 0:
            white = img.copy()
            white.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_ADD)
            white.set_alpha(int(220 * du.flash))
            surface.blit(white, rect)
        return rect

    def draw_hidden_outlines(self, surface, ds: DisplayState, rects: dict) -> None:
        """더 가까운 캐릭터에 절반 넘게 가려진 캐릭터는 윤곽선으로 보여 준다 (설계서 §4.3)."""
        for uid, (gy, rect) in rects.items():
            du = ds.units[uid]
            if du.lying or rect.width == 0:
                continue
            occluders = []
            for other, (ogy, orect) in rects.items():
                if other == uid or ogy <= gy or ds.units[other].lying:
                    continue
                inter = rect.clip(orect)
                if inter.width * inter.height >= rect.width * rect.height * 0.3:
                    occluders.append(other)
            if not occluders or du.tilt:
                continue
            img, _ = self._unit_sprite(du)
            mask = pygame.mask.from_surface(img, 100)
            color = (120, 190, 255) if du.kind == "player" else (255, 120, 90)
            outline = mask.outline(4)
            if len(outline) <= 2:
                continue
            pts = [(rect.x + x, rect.y + y) for x, y in outline]
            layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(layer, (*color, 60), pts)
            pygame.draw.lines(layer, (*color, 220), True, pts, 2)
            # 가린 캐릭터의 실제 픽셀이 있는 곳에만 윤곽이 보이게 자른다
            clip = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            for other in occluders:
                oimg, _ = self._unit_sprite(ds.units[other])
                omask = pygame.mask.from_surface(oimg, 100).to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
                clip.blit(omask, rects[other][1])
            layer.blit(clip, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(layer, (0, 0))

    def draw_unit_overlay(self, surface, du: DisplayUnit, ds: DisplayState, fx) -> None:
        """체력 막대·상태 배지·방어 고리. 모든 캐릭터를 그린 뒤에 그린다."""
        if du.lying:
            return
        fx_x, fy = self.cam.foot(du.gx, du.gy)
        cw = self.cam.cell_width(du.gy)
        height = int(cw * assets_mod.UNIT_HEIGHT_IN_CELLS[du.kind])
        top = fy - height - 16
        color = GREEN if du.kind == "player" else RED
        _hp_bar(surface, self.fonts, int(fx_x), int(top), du.hp, du.max_hp, color)
        badges = []
        for key in du.statuses:
            badges.append((STATUS_LONG[key], STATUS_COLOR[key]))
        if du.kind == "player":
            if ds.guarding:
                badges.append(("방어", (140, 190, 240)))
            if ds.dashed:
                badges.append(("돌진 직후", (170, 170, 170)))
        bx = int(fx_x) + 34
        for label, col in badges:
            t = self.fonts.small.render(label, True, (18, 16, 12))
            badge = pygame.Surface((t.get_width() + 10, 18), pygame.SRCALPHA)
            pygame.draw.rect(badge, (*col, 230), badge.get_rect(), border_radius=5)
            badge.blit(t, (5, 0))
            surface.blit(badge, (bx, int(top) - 5))
            bx += badge.get_width() + 3
        if "burning" in du.statuses:
            for i in range(3):
                _glow(surface, (fx_x - 14 + i * 14, fy - cw * (0.5 + 0.1 * i)), 14, (200, 90, 20))
        if ds.guarding and du.kind == "player":
            ring = pygame.Surface((int(cw * 1.3), int(cw * 0.5)), pygame.SRCALPHA)
            pygame.draw.ellipse(ring, (140, 190, 240, 120), ring.get_rect(), 4)
            surface.blit(ring, ring.get_rect(center=(fx_x, fy - 4)))
        if fx is not None and fx.active_enemy == du.uid:
            ring = pygame.Surface((int(cw * 1.1), int(cw * 0.42)), pygame.SRCALPHA)
            pygame.draw.ellipse(ring, (230, 90, 70, 200), ring.get_rect(), 3)
            surface.blit(ring, ring.get_rect(center=(fx_x, fy - 2)))

    # ---- 지형 장식
    def draw_terrain_decals(self, surface, grid) -> list[tuple[float, callable]]:
        """진흙은 바닥 장식으로 바로 그리고, 덤불·돌담은 깊이 정렬 목록으로 돌려준다."""
        layered = []
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                if ch == level.MUD:
                    cx, cy = self.cam.cell_center(x, y)
                    cw = self.cam.cell_width(y)
                    mud = self.assets.fx_scaled("mud", (int(cw * 1.25), int(cw * 0.6)))
                    if mud is not None:
                        surface.blit(mud, mud.get_rect(center=(cx, cy)))
                    else:
                        s = pygame.Surface((int(cw * 1.2), int(cw * 0.55)), pygame.SRCALPHA)
                        pygame.draw.ellipse(s, (80, 55, 30, 170), s.get_rect())
                        surface.blit(s, s.get_rect(center=(cx, cy)))
                elif ch == level.BUSH:
                    layered.append((y + 0.95, lambda s, x=x, y=y: self._draw_bush(s, x, y)))
                elif ch == level.WALL and 0 < x < level.WIDTH - 1 and 0 < y < level.HEIGHT - 1:
                    layered.append((y + 0.98, lambda s, x=x, y=y: self._draw_wall_stub(s, x, y)))
        return layered

    def _draw_bush(self, surface, x, y):
        cx, cy = self.cam.cell_center(x, y)
        cw = self.cam.cell_width(y)
        bush = self.assets.fx_scaled("bush", (int(cw * 1.15), int(cw * 0.95)))
        if bush is None:
            s = pygame.Surface((int(cw), int(cw * 0.8)), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (60, 110, 55, 220), s.get_rect())
            surface.blit(s, s.get_rect(midbottom=(cx, cy + cw * 0.3)))
            return
        surface.blit(bush, bush.get_rect(midbottom=(cx, cy + cw * 0.32)))

    def _draw_wall_stub(self, surface, x, y):
        cx, cy = self.cam.cell_center(x, y)
        cw = self.cam.cell_width(y)
        wall = self.assets.fx_scaled("wall-stub", (int(cw * 1.05), int(cw * 0.62)))
        if wall is None:
            pygame.draw.rect(surface, (95, 92, 84), (cx - cw * 0.5, cy - cw * 0.5, cw, cw * 0.6))
            return
        surface.blit(wall, wall.get_rect(midbottom=(cx, cy + cw * 0.28)))

    # ---- 계획 표시
    def draw_plan_preview(self, surface, validation, ds: DisplayState, state) -> None:
        if validation is None or not validation.accepted:
            return
        start = (float(state.player.pos[0]), float(state.player.pos[1]))
        for check in validation.checks:
            if check.path:
                pts = [self.cam.foot(*start)] + [self.cam.foot(*p) for p in check.path]
                for a, b in zip(pts, pts[1:]):
                    self._dotted(surface, a, b)
                end = pts[-1]
                cw = self.cam.cell_width(check.path[-1][1])
                ring = pygame.Surface((int(cw * 0.7), int(cw * 0.28)), pygame.SRCALPHA)
                pygame.draw.ellipse(ring, (250, 215, 120, 220), ring.get_rect(), 3)
                surface.blit(ring, ring.get_rect(center=(end[0], end[1] - 2)))
                start = (float(check.path[-1][0]), float(check.path[-1][1]))
            if check.target:
                du = ds.units.get(check.target)
                if du is not None:
                    self._target_mark(surface, du)
            if check.chances and not check.target:
                for uid in check.chances:
                    du = ds.units.get(uid)
                    if du is not None:
                        self._target_mark(surface, du)

    def _dotted(self, surface, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        dist = math.hypot(dx, dy)
        n = max(1, int(dist / 14))
        for i in range(n + 1):
            k = i / n
            p = (a[0] + dx * k, a[1] + dy * k)
            pygame.draw.circle(surface, (20, 16, 10), (int(p[0]), int(p[1])), 4)
            pygame.draw.circle(surface, (250, 215, 120), (int(p[0]), int(p[1])), 3)

    def _target_mark(self, surface, du: DisplayUnit):
        fx_x, fy = self.cam.foot(du.gx, du.gy)
        cw = self.cam.cell_width(du.gy)
        arc = pygame.Surface((int(cw * 1.0), int(cw * 0.4)), pygame.SRCALPHA)
        rect = arc.get_rect()
        pygame.draw.arc(arc, (240, 120, 80, 230), rect, math.radians(200), math.radians(340), 3)
        pygame.draw.arc(arc, (240, 120, 80, 230), rect, math.radians(20), math.radians(160), 3)
        surface.blit(arc, arc.get_rect(center=(fx_x, fy - 2)))
        # 머리 위 작은 화살표
        top = fy - cw * 1.9
        pygame.draw.polygon(surface, (240, 120, 80), [(fx_x - 7, top - 12), (fx_x + 7, top - 12), (fx_x, top)])

    # ---- 효과
    def draw_fx(self, surface, fx) -> None:
        if fx.aim_mark:
            x, y, k = fx.aim_mark
            r = 10 + 8 * (1 - k)
            cw = 60
            cy = y - cw * 1.2
            pygame.draw.circle(surface, (255, 230, 160), (int(x), int(cy)), int(r), 2)
            pygame.draw.line(surface, (255, 230, 160), (x - r - 6, cy), (x - r + 2, cy), 2)
            pygame.draw.line(surface, (255, 230, 160), (x + r - 2, cy), (x + r + 6, cy), 2)
        if fx.slash:
            self._slash(surface, *fx.slash)
        if fx.whirl:
            x, y, k, radius = fx.whirl
            ang = k * 360
            for i in range(6):
                a0 = math.radians(ang - i * 18)
                pts = [(x + math.cos(a0) * radius, y + math.sin(a0) * radius * 0.45)]
                a1 = math.radians(ang - i * 18 - 18)
                pts.append((x + math.cos(a1) * radius, y + math.sin(a1) * radius * 0.45))
                alpha = max(0, 230 - i * 38)
                s = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
                pygame.draw.line(s, (255, 236, 190, alpha), pts[0], pts[1], 6)
                surface.blit(s, (0, 0))
        for p in fx.particles:
            k = max(0.0, min(1.0, p.life / p.max_life))
            if p.additive:
                _glow(surface, (p.x, p.y), p.size * (0.6 + k), p.color)
            else:
                col = tuple(int(c * (0.4 + 0.6 * k)) for c in p.color)
                pygame.draw.circle(surface, col, (int(p.x), int(p.y)), max(1, int(p.size * k)))
        if fx.projectile:
            kind, x, y, k = fx.projectile
            if kind == "fireball":
                _glow(surface, (x, y), 42, (255, 120, 30))
                _glow(surface, (x, y), 20, (255, 220, 120))
                pygame.draw.circle(surface, (255, 245, 210), (int(x), int(y)), 7)
            else:
                ang = k * 1080
                knife = pygame.Surface((34, 8), pygame.SRCALPHA)
                pygame.draw.polygon(knife, (220, 220, 230), [(0, 4), (22, 0), (34, 4), (22, 8)])
                pygame.draw.rect(knife, (90, 60, 40), (0, 2, 10, 4))
                rot = pygame.transform.rotozoom(knife, ang, 1.0)
                surface.blit(rot, rot.get_rect(center=(x, y)))
        for q in fx.popups:
            k = q.life / q.max_life
            font = self.fonts.number if q.big else self.fonts.label
            img = font.render(q.text, True, q.color)
            sh = font.render(q.text, True, (10, 8, 6))
            img.set_alpha(int(255 * min(1.0, k * 2)))
            sh.set_alpha(int(255 * min(1.0, k * 2)))
            r = img.get_rect(center=(q.x, q.y))
            surface.blit(sh, r.move(2, 2))
            surface.blit(img, r)

    def _slash(self, surface, x, y, k, facing, thick):
        radius = 46 * thick
        start = -110 * facing
        sweep = 180 * facing * ease(k)
        s = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pts_out, pts_in = [], []
        n = 16
        for i in range(n + 1):
            a = math.radians(start + sweep * i / n)
            pts_out.append((x + math.cos(a) * radius, y + math.sin(a) * radius))
            w = (1 - abs(i / n - 0.5) * 1.6) * 14 * thick
            pts_in.append((x + math.cos(a) * (radius - w), y + math.sin(a) * (radius - w)))
        if len(pts_out) > 2:
            alpha = int(230 * (1 - k * 0.6))
            pygame.draw.polygon(s, (255, 236, 190, alpha), pts_out + pts_in[::-1])
            pygame.draw.polygon(s, (255, 255, 255, alpha), [((px + x) / 2, (py + y) / 2) for px, py in pts_out] + [((px + x) / 2, (py + y) / 2) for px, py in pts_in[::-1]])
        surface.blit(s, (0, 0))
        _glow(surface, (x, y), 40 * thick, (120, 100, 60))

    # ---- HUD
    def draw_hud(self, surface, session, ds: DisplayState, fx) -> None:
        f = self.fonts
        state = session.state
        p = state.player
        # 왼쪽 위: 서린
        rect = pygame.Rect(16, 14, 340, 108)
        _panel(surface, rect)
        por = self.assets.portraits.get("player")
        if por is not None:
            surface.blit(pygame.transform.smoothscale(por, (66, 66)), (rect.x + 10, rect.y + 10))
        else:
            pygame.draw.rect(surface, BLUE, (rect.x + 10, rect.y + 10, 66, 66), border_radius=6)
        pygame.draw.rect(surface, PANEL_LINE, (rect.x + 10, rect.y + 10, 66, 66), 1, border_radius=6)
        _text(surface, f.label, "서린", (rect.x + 88, rect.y + 8), GOLD)
        _text(surface, f.small, "용병", (rect.x + 138, rect.y + 13), DIM)
        hp = ds.player.hp
        bar = pygame.Rect(rect.x + 88, rect.y + 36, 160, 10)
        pygame.draw.rect(surface, (70, 28, 24), bar, border_radius=3)
        pygame.draw.rect(surface, GREEN, (bar.x, bar.y, int(bar.width * max(0, hp) / p.max_hp), bar.height), border_radius=3)
        _text(surface, f.small, f"{max(0, hp)} / {p.max_hp}", (bar.right + 8, bar.y - 3), TEXT)
        _text(surface, f.small, f"마나 {state.mana}", (rect.x + 88, rect.y + 54), TEXT)
        mb = pygame.Rect(rect.x + 140, rect.y + 60, 50, 6)
        pygame.draw.rect(surface, (30, 40, 60), mb, border_radius=3)
        pygame.draw.rect(surface, BLUE, (mb.x, mb.y, int(mb.width * state.mana / level.PLAYER_STATS["mana"]), mb.height), border_radius=3)
        _text(surface, f.small, f"행동 {state.ap} / {level.AP_PER_TURN}", (rect.x + 200, rect.y + 54), TEXT)
        for i in range(level.AP_PER_TURN):
            col = GOLD if i < state.ap else (70, 64, 50)
            cx, cy = rect.x + 284 + i * 12, rect.y + 62
            pygame.draw.polygon(surface, col, [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)])
        # 가운데 위: 턴
        trect = pygame.Rect(SCENE_SIZE[0] // 2 - 110, 14, 220, 34)
        _panel(surface, trect)
        _text(surface, f.label, f"턴 {state.turn}", (trect.x + 16, trect.centery), GOLD, "midleft")
        _text(surface, f.small, f"시드 {session.seed}", (trect.right - 14, trect.centery), DIM, "midright")
        # 오른쪽 위: 적
        x = SCENE_SIZE[0] - 16
        for uid in ("orc", "goblin"):
            unit = state.enemy(uid)
            du = ds.units[uid]
            r = pygame.Rect(x - 236, 14, 236, 58)
            _panel(surface, r)
            por = self.assets.portraits.get(uid)
            if por is not None:
                surface.blit(pygame.transform.smoothscale(por, (44, 44)), (r.x + 7, r.y + 7))
            pygame.draw.rect(surface, PANEL_LINE, (r.x + 7, r.y + 7, 44, 44), 1, border_radius=5)
            label = "리크" if uid == "goblin" else "브루"
            _text(surface, f.label, label, (r.x + 60, r.y + 4), GOLD)
            _text(surface, f.small, name(uid), (r.x + 108, r.y + 9), DIM)
            bar = pygame.Rect(r.x + 60, r.y + 32, 104, 8)
            pygame.draw.rect(surface, (70, 28, 24), bar, border_radius=3)
            pygame.draw.rect(surface, RED, (bar.x, bar.y, int(bar.width * max(0, du.hp) / unit.max_hp), bar.height), border_radius=3)
            _text(surface, f.small, "전투불능" if not du.alive else f"{max(0, du.hp)}/{unit.max_hp}", (bar.right + 6, bar.y - 4), DIM)
            x -= 246
        # 왼쪽 위 패널 아래: 자원 한 줄
        cooldown = "사용 가능" if state.whirlwind_cooldown == 0 else f"대기 {state.whirlwind_cooldown}턴"
        _text(surface, f.small, f"물약 {state.potions} · 단검 {state.knives} · 돌려베기 {cooldown} · 화염구 마나 {level.FIREBALL_MANA}",
              (rect.x + 10, rect.y + 84), DIM, shadow=False)
        # 배너
        if fx is not None and fx.banner:
            text, k = fx.banner
            alpha = int(255 * min(1.0, k * 3) * (1 if k < 0.8 else (1 - k) * 5))
            img = f.title.render(text, True, (255, 210, 190))
            img.set_alpha(max(0, alpha))
            bx = SCENE_SIZE[0] // 2 - 200 * (1 - min(1.0, k * 3))
            surface.blit(img, img.get_rect(center=(bx, 120)))

    def draw_outcome(self, surface, session) -> None:
        state = session.state
        if state.outcome is None:
            return
        box = pygame.Rect(SCENE_SIZE[0] // 2 - 300, 230, 600, 190)
        _panel(surface, box, 225)
        title = "승리" if state.outcome == "win" else "패배"
        body = ("관문 앞이 조용해진다. 지금 이 통로를 막는 상대는 없다." if state.outcome == "win"
                else "검을 쥔 손에 힘이 풀린다. 서린은 더 싸울 수 없다.")
        _text(surface, self.fonts.big, title, (box.centerx, box.y + 52), GOLD, "center")
        _text(surface, self.fonts.body, f"{state.turn}턴 · {body}", (box.centerx, box.y + 112), TEXT, "center")
        _text(surface, self.fonts.small, "'다시 시작'을 입력하면 새 판을 시작해요", (box.centerx, box.y + 152), DIM, "center")

    def draw_debug(self, surface, state) -> None:
        for y in range(level.HEIGHT):
            for x in range(level.WIDTH):
                poly = self.cam.cell_polygon(x, y)
                pygame.draw.polygon(surface, (255, 255, 255), poly, 1)
                cx, cy = self.cam.cell_center(x, y)
                _text(surface, self.fonts.small, f"{x},{y}{state.terrain((x, y))}", (cx, cy), (255, 255, 120), "center", shadow=False)

    # ---- 전체
    def draw(self, window, session, ds: DisplayState, animator, text_input, pending_validation=None) -> None:
        s = self.scene
        s.blit(self.assets.backdrop, (0, -SCENE_CROP_TOP))
        layered = self.draw_terrain_decals(s, session.state.grid)
        fx = animator.fx if animator is not None else None
        if session.phase == "planned":
            self.draw_plan_preview(s, pending_validation, ds, session.state)
        # 깊이 정렬: 발 위치 행이 큰(가까운) 것을 나중에
        rects: dict[str, tuple[float, pygame.Rect]] = {}

        def unit_drawer(du):
            def fn(surf):
                rects[du.uid] = (du.gy, self.draw_unit(surf, du, ds))
            return fn

        drawables = [(du.gy + 0.72, unit_drawer(du)) for du in ds.units.values()]
        drawables.extend(layered)
        for _, fn in sorted(drawables, key=lambda item: item[0]):
            fn(s)
        self.draw_hidden_outlines(s, ds, rects)
        for du in ds.units.values():
            self.draw_unit_overlay(s, du, ds, fx)
        if fx is not None:
            self.draw_fx(s, fx)
        if self.debug:
            self.draw_debug(s, session.state)
        self.draw_hud(s, session, ds, fx)
        if fx is not None and fx.fade > 0:
            dark = pygame.Surface(SCENE_SIZE, pygame.SRCALPHA)
            dark.fill((0, 0, 0, int(255 * fx.fade)))
            s.blit(dark, (0, 0))
        if session.state.outcome is not None and (animator is None or not animator.running):
            self.draw_outcome(s, session)
        shake = fx.shake if fx is not None else 0.0
        offset = (int(math.sin(shake * 40) * 4 * shake), int(math.cos(shake * 33) * 3 * shake)) if shake > 0 else (0, 0)
        window.fill((8, 9, 12))
        window.blit(s, offset)
        self.draw_strip(window, session, animator, text_input)

    def draw_strip(self, window, session, animator, text_input) -> None:
        f = self.fonts
        strip = pygame.Rect(0, STRIP_TOP, WINDOW_SIZE[0], WINDOW_SIZE[1] - STRIP_TOP)
        pygame.draw.rect(window, (12, 14, 20), strip)
        pygame.draw.line(window, PANEL_LINE, (0, STRIP_TOP), (WINDOW_SIZE[0], STRIP_TOP))
        line = session.plan_line or "한 턴의 행동을 문장으로 적고 Enter를 누르세요"
        if animator is not None and animator.current_line and session.phase in ("animating", "idle"):
            line = animator.current_line
        color = RED if line.startswith(("거부", "다시 입력")) else (GOLD if line.startswith("계획") else TEXT)
        y = STRIP_TOP + 6
        for w in wrap(f.body, line, WINDOW_SIZE[0] - 32)[:2]:
            _text(window, f.body, w, (16, y), color, shadow=False)
            y += f.body.get_linesize()
        # 최근 기록 두 줄 (전체 기록은 파일에 남는다)
        if animator is not None and session.phase == "animating":
            recent = [h for h in animator.played_lines if h != line][-2:]
        else:
            recent = [h for h in list(session.history)[-6:] if h != line and not h.startswith(">")][-2:]
        for h in recent:
            _text(window, f.small, h[:110], (16, y + 2), DIM, shadow=False)
            y += f.small.get_linesize()
        box = pygame.Rect(16, WINDOW_SIZE[1] - 36, WINDOW_SIZE[0] - 32, 30)
        pygame.draw.rect(window, (26, 30, 40), box, border_radius=4)
        pygame.draw.rect(window, PANEL_LINE, box, 1, border_radius=4)
        _text(window, f.small, "행동 입력", (box.x + 10, box.y + 7), DIM, shadow=False)
        tx = box.x + 84
        t = f.body.render(text_input.text, True, TEXT)
        window.blit(t, (tx, box.y + 3))
        tx += t.get_width()
        if text_input.composition:
            c = f.body.render(text_input.composition, True, GOLD)
            window.blit(c, (tx, box.y + 3))
            pygame.draw.line(window, GOLD, (tx, box.bottom - 4), (tx + c.get_width(), box.bottom - 4), 2)
            tx += c.get_width()
        pygame.draw.line(window, TEXT, (tx + 2, box.y + 5), (tx + 2, box.bottom - 5))
        elapsed = session.elapsed()
        if elapsed is not None:
            status = f"AI 해석 중… {elapsed:.1f}초"
        elif session.phase == "planned":
            status = "계획을 확인하세요 · 잠시 뒤 자동으로 실행해요"
        elif session.phase == "animating":
            status = "연출 중"
        else:
            status = session.notice
        if status:
            _text(window, f.small, status, (box.right - 10, box.y + 7), GOLD, "topright", shadow=False)


def ease(t: float) -> float:
    return 1 - (1 - t) ** 2


def result_text(session) -> tuple[str, str]:
    s = session.state
    title = f"승리! {s.turn}턴" if s.outcome == "win" else f"패배… {s.turn}턴"
    return title, "'다시 시작'을 입력하면 새 판을 시작해요"
