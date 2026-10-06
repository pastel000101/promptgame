"""이미지·글꼴 적재 (설계서 §4.5). 파일이 없으면 그 항목만 코드 도형으로 대체하고 콘솔에 알린다."""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = ROOT / "assets"
UNIT_FILES = {"player": "seorin", "goblin": "rik", "bru": "bru", "orc": "bru"}
# 컷아웃의 키를 칸 폭의 몇 배로 그릴지. 시안의 체구 차이를 따른다.
UNIT_HEIGHT_IN_CELLS = {"player": 1.95, "goblin": 1.35, "orc": 2.15}
# 컷아웃에서 발이 닿는 점의 가로 위치(0~1, 왼쪽 기준)와 허리 높이(0~1, 위 기준). 상체 회전의 기준이다.
UNIT_FOOT_X = {"player": 0.45, "goblin": 0.5, "orc": 0.5}
UNIT_WAIST = {"player": 0.52, "goblin": 0.55, "orc": 0.5}
# 원본 컷아웃이 바라보는 방향 (+1 오른쪽, -1 왼쪽)
UNIT_FACING = {"player": 1, "goblin": -1, "orc": -1}
FALLBACK_COLORS = {"player": (70, 130, 220), "goblin": (90, 170, 80), "orc": (180, 70, 60)}


def _warn(msg: str) -> None:
    print(f"[promptgame] {msg}", file=sys.stderr)


def _load_image(path: Path) -> pygame.Surface | None:
    if not path.exists():
        _warn(f"자산 없음, 대체 도형 사용: {path.name}")
        return None
    try:
        img = pygame.image.load(str(path))
        # 창이 있으면 화면 형식으로 바꿔 두고, 창 없는 테스트·캡처에서는 그대로 쓴다
        return img.convert_alpha() if pygame.display.get_surface() is not None else img
    except pygame.error as exc:
        _warn(f"자산을 읽지 못함, 대체 도형 사용: {path.name} ({exc})")
        return None


def _fallback_unit(kind: str) -> pygame.Surface:
    """컷아웃이 없을 때: 색 기둥과 머리 원."""
    s = pygame.Surface((120, 260), pygame.SRCALPHA)
    color = FALLBACK_COLORS[kind]
    pygame.draw.rect(s, color, (35, 80, 50, 170), border_radius=14)
    pygame.draw.circle(s, color, (60, 50), 40)
    pygame.draw.circle(s, (20, 20, 20), (60, 50), 40, 3)
    return s


class Fonts:
    def __init__(self) -> None:
        sans = ASSET_DIR / "fonts" / "NotoSansKR-VF.ttf"
        serif = ASSET_DIR / "fonts" / "NotoSerifKR-VF.ttf"
        self.bundled = sans.exists() and serif.exists()
        sans_path = str(sans) if sans.exists() else pygame.font.match_font("malgungothic")
        serif_path = str(serif) if serif.exists() else sans_path
        if not self.bundled:
            _warn("동봉 글꼴이 없어 시스템 글꼴을 씁니다")
        self.small = pygame.font.Font(sans_path, 15)
        self.body = pygame.font.Font(sans_path, 18)
        self.label = pygame.font.Font(serif_path, 19)
        self.title = pygame.font.Font(serif_path, 26)
        self.number = pygame.font.Font(serif_path, 34)
        self.big = pygame.font.Font(serif_path, 54)
        for f in (self.label, self.title, self.number, self.big):
            f.set_bold(True)


class Assets:
    def __init__(self, scene_size: tuple[int, int]) -> None:
        self.scene_size = scene_size
        self.missing: list[str] = []
        self.backdrop = self._backdrop(scene_size)
        self.units: dict[str, pygame.Surface] = {}
        for kind, name in (("player", "seorin"), ("goblin", "rik"), ("orc", "bru")):
            img = _load_image(ASSET_DIR / "units" / f"{name}.png")
            if img is None:
                self.missing.append(f"units/{name}.png")
                img = _fallback_unit(kind)
            self.units[kind] = img
        self.portraits: dict[str, pygame.Surface | None] = {}
        for kind, name in (("player", "seorin"), ("goblin", "rik"), ("orc", "bru")):
            img = _load_image(ASSET_DIR / "portraits" / f"{name}.png")
            if img is None:
                self.missing.append(f"portraits/{name}.png")
            self.portraits[kind] = img
        self.fx: dict[str, pygame.Surface | None] = {}
        for name in ("mud", "bush", "wall-stub"):
            img = _load_image(ASSET_DIR / "fx" / f"{name}.png")
            if img is None:
                self.missing.append(f"fx/{name}.png")
            self.fx[name] = img
        self.fonts = Fonts()
        self._scaled: dict[tuple, pygame.Surface] = {}

    def _backdrop(self, size: tuple[int, int]) -> pygame.Surface:
        img = _load_image(ASSET_DIR / "backdrop.png")
        if img is None:
            self.missing.append("backdrop.png")
            s = pygame.Surface(size)
            s.fill((78, 72, 60))
            pygame.draw.rect(s, (50, 60, 80), (0, 0, size[0], size[1] * 0.4))
            return s
        return pygame.transform.smoothscale(img, size)

    def unit_scaled(self, kind: str, height: int, facing: int) -> pygame.Surface:
        """캐릭터 컷아웃을 주어진 키로 축소하고 방향을 맞춘다. 결과는 캐시한다."""
        height = max(8, int(height))
        key = (kind, height, facing)
        if key not in self._scaled:
            src = self.units[kind]
            width = max(1, int(src.get_width() * height / src.get_height()))
            img = pygame.transform.smoothscale(src, (width, height))
            if facing != UNIT_FACING[kind]:
                img = pygame.transform.flip(img, True, False)
            self._scaled[key] = img
        return self._scaled[key]

    def fx_scaled(self, name: str, size: tuple[int, int]) -> pygame.Surface | None:
        src = self.fx.get(name)
        if src is None:
            return None
        key = (name, size)
        if key not in self._scaled:
            self._scaled[key] = pygame.transform.smoothscale(src, (max(1, size[0]), max(1, size[1])))
        return self._scaled[key]
