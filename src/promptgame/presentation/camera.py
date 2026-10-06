"""격자 좌표 → 화면 좌표 투영 (설계서 §4.2).

내부 좌표는 domain의 (x, y) 칸이다. 화면에서는 x가 왼쪽→오른쪽 열, y가 먼 쪽(위, 북)→가까운 쪽(아래, 남) 행이다.
지면은 평면 호모그래피 하나로 투영한다. 네 꼭짓점은 배경 그림(1280×720)의 지면에 맞춘 값이며,
칸 (x, y)의 바닥 중심은 격자 좌표 (x + 0.5, y + 0.5)를 투영한 점이다. 캐릭터의 발을 그 점에 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass

from promptgame.domain import level

Pos = tuple[float, float]

# 배경 그림 기준 지면 사변형 (격자 좌표 (0,1)·(10,1)·(0,7)·(10,7)에 대응). 행 0과 행 7은 벽이라
# 행 0은 뒷벽, 행 7은 화면 아래 경계 너머에 둔다.
GROUND_QUAD = {
    (0.0, 1.0): (252.0, 295.0),
    (10.0, 1.0): (1171.0, 295.0),
    (0.0, 7.0): (-230.0, 735.0),
    (10.0, 7.0): (1646.0, 735.0),
}
SCENE_CROP_TOP = 40  # render.SCENE_CROP_TOP과 같다. 배경 위 40px을 잘라 낸 만큼 화면 y가 올라간다


def _solve(src: list[Pos], dst: list[Pos]) -> list[float]:
    """4점 대응으로 3×3 호모그래피(마지막 원소 1)를 가우스 소거로 푼다."""
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, v])
    n = 8
    for c in range(n):
        pivot = max(range(c, n), key=lambda r: abs(rows[r][c]))
        rows[c], rows[pivot] = rows[pivot], rows[c]
        for r in range(n):
            if r != c and rows[r][c]:
                f = rows[r][c] / rows[c][c]
                rows[r] = [a - f * b for a, b in zip(rows[r], rows[c])]
    return [rows[i][n] / rows[i][i] for i in range(n)] + [1.0]


@dataclass
class Camera:
    h: list[float]
    offset: tuple[int, int] = (0, 0)  # 장면 영역이 창 안에서 시작하는 위치

    @classmethod
    def default(cls, offset: tuple[int, int] = (0, 0)) -> "Camera":
        src = list(GROUND_QUAD.keys())
        dst = list(GROUND_QUAD.values())
        return cls(_solve(src, dst), (offset[0], offset[1] - SCENE_CROP_TOP))

    def project(self, gx: float, gy: float) -> Pos:
        """격자 좌표(연속값)를 화면 좌표로."""
        h = self.h
        w = h[6] * gx + h[7] * gy + 1.0
        return ((h[0] * gx + h[1] * gy + h[2]) / w + self.offset[0], (h[3] * gx + h[4] * gy + h[5]) / w + self.offset[1])

    def cell_center(self, x: int, y: int) -> Pos:
        return self.project(x + 0.5, y + 0.5)

    def foot(self, x: float, y: float) -> Pos:
        """칸 좌표(연속값, 이동 보간용)의 발 위치. 칸 중심에서 약간 아래(앞)."""
        return self.project(x + 0.5, y + 0.72)

    def cell_width(self, y: float) -> float:
        """행 y에서 한 칸의 화면 폭. 캐릭터 크기의 기준."""
        a = self.project(0.0, y + 0.5)
        b = self.project(1.0, y + 0.5)
        return b[0] - a[0]

    def cell_polygon(self, x: int, y: int) -> list[Pos]:
        return [self.project(x, y), self.project(x + 1, y), self.project(x + 1, y + 1), self.project(x, y + 1)]

    def depth(self, y: float) -> float:
        return y

    @staticmethod
    def in_field(x: int, y: int) -> bool:
        return 0 <= x < level.WIDTH and 0 <= y < level.HEIGHT
