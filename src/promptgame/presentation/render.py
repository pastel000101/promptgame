"""그리기. 상태를 읽기만 하고 규칙 계산이나 LLM 호출을 하지 않는다 (설계서 §4)."""

from __future__ import annotations

import pygame

from promptgame.domain import level
from promptgame.domain.narrate import name

WINDOW_SIZE = (980, 760)
TILE = 50
GRID_ORIGIN = (16, 16)
PANEL_X = GRID_ORIGIN[0] + TILE * level.WIDTH + 24
LOG_LINES = 10

BG = (24, 26, 32)
TEXT = (230, 230, 230)
DIM = (150, 155, 165)
ACCENT = (250, 210, 120)
REJECT = (240, 130, 120)
TERRAIN_COLORS = {level.FLOOR: (196, 186, 156), level.WALL: (62, 64, 74), level.MUD: (122, 92, 60), level.BUSH: (78, 132, 74)}
UNIT_COLORS = {"player": (70, 130, 220), "goblin": (90, 170, 80), "orc": (180, 70, 60)}
UNIT_LETTERS = {"player": "용", "goblin": "고", "orc": "오"}
STATUS_SHORT = {"stagger": "비틀", "burning": "불", "arm_injury": "팔", "leg_injury": "다리"}
STATUS_LONG = {"stagger": "비틀거림", "burning": "불타는", "arm_injury": "팔 부상", "leg_injury": "다리 부상"}

FONT_CANDIDATES = ["malgungothic", "malgun gothic", "nanumgothic", "applegothic", "notosanscjkkr", "notosanskr"]


class Fonts:
    def __init__(self) -> None:
        path = None
        for candidate in FONT_CANDIDATES:
            path = pygame.font.match_font(candidate)
            if path:
                break
        self.found = path is not None
        self.small = pygame.font.Font(path, 15)
        self.normal = pygame.font.Font(path, 17)
        self.tile = pygame.font.Font(path, 20)
        self.big = pygame.font.Font(path, 30)


def wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
    lines, current = [], ""
    for ch in text:
        if font.size(current + ch)[0] > width and current:
            lines.append(current)
            current = ch.lstrip() if ch == " " else ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines or [""]


def _blit(surface, font, text, pos, color=TEXT) -> int:
    surface.blit(font.render(text, True, color), pos)
    return font.get_linesize()


def draw_grid(surface: pygame.Surface, state, fonts: Fonts) -> None:
    ox, oy = GRID_ORIGIN
    for y, row in enumerate(state.grid):
        for x, cell in enumerate(row):
            rect = pygame.Rect(ox + x * TILE, oy + y * TILE, TILE - 1, TILE - 1)
            pygame.draw.rect(surface, TERRAIN_COLORS[cell], rect)
    units = [state.player] + state.alive_enemies()
    for unit in units:
        if not unit.alive:
            continue
        x, y = unit.pos
        center = (ox + x * TILE + TILE // 2, oy + y * TILE + TILE // 2 - 4)
        pygame.draw.circle(surface, UNIT_COLORS[unit.kind], center, TILE // 2 - 8)
        letter = fonts.tile.render(UNIT_LETTERS[unit.kind], True, (255, 255, 255))
        surface.blit(letter, letter.get_rect(center=center))
        hp = fonts.small.render(str(unit.hp), True, (20, 20, 20))
        surface.blit(hp, hp.get_rect(midbottom=(center[0], oy + (y + 1) * TILE - 1)))
        tags = [STATUS_SHORT[k] for k in unit.statuses] if unit.kind != "player" else []
        if unit.kind == "player":
            tags += (["돌진"] if state.dashed else []) + (["방어"] if state.guarding else [])
        if tags:
            tag = fonts.small.render("·".join(tags), True, ACCENT, (0, 0, 0))
            surface.blit(tag, (ox + x * TILE + 1, oy + y * TILE + 1))


def panel_lines(session) -> list[tuple[str, tuple[int, int, int]]]:
    s = session.state
    p = s.player
    status = []
    if s.dashed:
        status.append("돌진 직후(회피 −10)")
    if s.guarding:
        status.append("방어 자세(회피 +20)")
    cooldown = "사용 가능" if s.whirlwind_cooldown == 0 else f"재사용 대기 {s.whirlwind_cooldown}턴"
    eq = level.PLAYER_EQUIPMENT
    lines = [
        (f"턴 {s.turn} · 시드 {session.seed}", ACCENT),
        (f"용병 체력 {p.hp}/{p.max_hp} · 마나 {s.mana} · AP {s.ap}/{level.AP_PER_TURN}", TEXT),
        (f"상태: {', '.join(status) or '없음'}", TEXT),
        (f"장비: {eq['weapon']}(피해 {p.weapon_damage}) · {eq['armor']}(방어 {p.armor})", TEXT),
        (f"가방: 치유 물약 {s.potions} · 투척 단검 {s.knives}", TEXT),
        (f"돌려베기(AP {level.WHIRLWIND_AP}): {cooldown}", TEXT),
        (f"화염구: AP {level.FIREBALL_AP} · 마나 {level.FIREBALL_MANA} · 사거리 {level.FIREBALL_RANGE}", TEXT),
        ("", TEXT),
    ]
    for e in s.enemies:
        if not e.alive:
            lines.append((f"{name(e.kind)}: 쓰러짐", DIM))
            continue
        statuses = ", ".join(STATUS_LONG[k] + ("" if k == "arm_injury" else f" {v}턴") for k, v in e.statuses.items())
        lines.append((f"{name(e.kind)} 체력 {e.hp}/{e.max_hp} · 회피 {e.evasion} · 방어 {e.armor}", TEXT))
        lines.append((f"  위치 ({e.pos[0]},{e.pos[1]}) · 상태: {statuses or '없음'}", DIM))
    lines.append(("", TEXT))
    lines.append((f"모델: {session.model or '없음'}", DIM))
    return lines


def draw(surface: pygame.Surface, session, text_input, fonts: Fonts) -> None:
    surface.fill(BG)
    draw_grid(surface, session.state, fonts)

    y = GRID_ORIGIN[1]
    panel_width = WINDOW_SIZE[0] - PANEL_X - 16
    for text, color in panel_lines(session):
        for line in wrap(fonts.normal, text, panel_width):
            y += _blit(surface, fonts.normal, line, (PANEL_X, y), color)

    # 계획 줄
    width = WINDOW_SIZE[0] - 32
    y = GRID_ORIGIN[1] + TILE * level.HEIGHT + 12
    plan = session.plan_line or "계획: (아직 없음)"
    color = REJECT if plan.startswith(("거부", "다시 입력")) else ACCENT
    for line in wrap(fonts.normal, plan, width)[:2]:
        y += _blit(surface, fonts.normal, line, (16, y), color)

    # 기록 창: 최근 줄
    y += 6
    pygame.draw.line(surface, DIM, (16, y), (WINDOW_SIZE[0] - 16, y))
    y += 4
    wrapped: list[str] = []
    for entry in session.history:
        wrapped.extend(wrap(fonts.small, entry, width))
    for line in wrapped[-LOG_LINES:]:
        color = DIM if line.startswith("적 턴") else TEXT
        y += _blit(surface, fonts.small, line, (16, y), color)

    # 입력창
    box = pygame.Rect(16, WINDOW_SIZE[1] - 56, WINDOW_SIZE[0] - 32, 40)
    pygame.draw.rect(surface, (40, 44, 54), box)
    pygame.draw.rect(surface, DIM, box, 1)
    tx, ty = box.x + 10, box.y + 9
    committed = fonts.normal.render(text_input.text, True, TEXT)
    surface.blit(committed, (tx, ty))
    cx = tx + committed.get_width()
    if text_input.composition:
        comp = fonts.normal.render(text_input.composition, True, ACCENT)
        surface.blit(comp, (cx, ty))
        pygame.draw.line(surface, ACCENT, (cx, ty + comp.get_height()), (cx + comp.get_width(), ty + comp.get_height()), 2)
        cx += comp.get_width()
    pygame.draw.line(surface, TEXT, (cx + 1, ty), (cx + 1, ty + fonts.normal.get_height()))
    elapsed = session.elapsed()
    status = f"AI 해석 중… {elapsed:.1f}초" if elapsed is not None else session.notice
    if status:
        _blit(surface, fonts.small, status, (16, box.y - 20), ACCENT)

    if session.state.outcome:
        _draw_result(surface, session, fonts)


def result_text(session) -> tuple[str, str]:
    s = session.state
    title = f"승리! {s.turn}턴" if s.outcome == "win" else f"패배… {s.turn}턴"
    return title, "'다시 시작'을 입력하면 새 판을 시작해요"


def _draw_result(surface, session, fonts: Fonts) -> None:
    title, hint = result_text(session)
    w, h = TILE * level.WIDTH - 60, 110
    box = pygame.Rect(GRID_ORIGIN[0] + 30, GRID_ORIGIN[1] + (TILE * level.HEIGHT - h) // 2, w, h)
    pygame.draw.rect(surface, (10, 10, 14), box)
    pygame.draw.rect(surface, ACCENT, box, 2)
    t = fonts.big.render(title, True, ACCENT)
    surface.blit(t, t.get_rect(center=(box.centerx, box.y + 36)))
    hnt = fonts.normal.render(hint, True, TEXT)
    surface.blit(hnt, hnt.get_rect(center=(box.centerx, box.y + 80)))
