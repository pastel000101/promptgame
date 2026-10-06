"""시안 그림에서 게임 자산을 잘라 assets/ 에 저장한다 (Pillow·numpy, 플레이 기능 아님).

입력(기본값은 Vault 첨부 폴더):
  tollgate-spatial-backdrop.png   인물·UI 없는 관문 앞 공간 (1672×941)
  mockup-06-spatial-battle.png    같은 공간에 서린·리크·브루가 선 시안 (1672×941)
출력:
  assets/backdrop.png             1280×720. 오른쪽 아래 웅덩이는 판정 지도에 없어 판석으로 덮었다
  assets/units/{seorin,rik,bru}.png  시안에서 손으로 그린 윤곽 다각형으로 잘라 낸 컷아웃(투명 배경)
  assets/portraits/*.png          시안 HUD의 초상화
  assets/fx/mud.png, bush.png, wall-stub.png  배경에서 잘라 낸 진흙·덤불·낮은 돌담 조각
  assets/fonts/                   Windows 설치 Noto Sans/Serif KR 복사

윤곽은 사람이 좌표를 찍은 것이라 가장자리에 배경 조각이 남을 수 있다. 완성 자산이 아니라
이미지 생성 도구로 투명 배경 컷아웃을 다시 만들 때까지의 임시 가공물이다.

    uv run python tools/build_assets.py [--src <폴더>]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DEFAULT_SRC = Path(r"C:\proj\mainprojact_0815\obs_mark\_Attachments\promptgame")
WINDOW = (1280, 720)

# 시안(1672×941) 좌표계의 인물 윤곽. 시계 방향.
OUTLINES = {
    "seorin": [
        (398, 242), (425, 250), (455, 235), (490, 240), (515, 258), (530, 285), (533, 320), (520, 345), (515, 365),
        (520, 385), (548, 415), (580, 445), (610, 465), (632, 478), (628, 495), (600, 497), (570, 485), (545, 478),
        (525, 480), (520, 500), (545, 555), (578, 595), (600, 632), (614, 672), (622, 706), (612, 728), (580, 722),
        (556, 700), (540, 660), (522, 618), (505, 590), (488, 572), (460, 565), (420, 580), (370, 612), (320, 640),
        (290, 672), (272, 710), (262, 750), (256, 795), (262, 832), (254, 862), (236, 880), (195, 884), (160, 874),
        (148, 852), (165, 826), (185, 790), (200, 750), (206, 700), (216, 660), (240, 622), (268, 592), (300, 566),
        (300, 540), (262, 530), (222, 520), (200, 502), (156, 498), (150, 470), (165, 452), (200, 448), (236, 462),
        (256, 440), (216, 420), (178, 398), (152, 368), (152, 338), (190, 328), (235, 333), (285, 322), (322, 300),
        (348, 274), (372, 254),
    ],
    "rik": [
        (1090, 372), (1110, 368), (1130, 350), (1150, 348), (1175, 360), (1195, 372), (1215, 380), (1198, 392),
        (1180, 400), (1185, 420), (1205, 440), (1230, 460), (1255, 480), (1278, 498), (1292, 512), (1280, 528),
        (1258, 520), (1235, 510), (1215, 505), (1210, 530), (1230, 560), (1260, 575), (1275, 585), (1258, 598),
        (1230, 600), (1215, 585), (1195, 560), (1175, 540), (1150, 535), (1140, 555), (1130, 580), (1120, 600),
        (1090, 602), (1070, 598), (1072, 585), (1095, 570), (1105, 545), (1100, 520), (1085, 500), (1065, 490),
        (1040, 515), (1012, 542), (1005, 538), (1025, 510), (1050, 480), (1068, 462), (1088, 470), (1100, 450),
        (1105, 430), (1098, 405), (1082, 392),
    ],
    "bru": [
        (1462, 228), (1480, 212), (1505, 206), (1530, 212), (1545, 235), (1548, 262), (1540, 282), (1565, 290),
        (1590, 305), (1605, 335), (1612, 370), (1618, 405), (1612, 432), (1598, 445), (1582, 430), (1572, 405),
        (1565, 385), (1560, 420), (1575, 460), (1588, 490), (1592, 520), (1580, 535), (1545, 535), (1528, 520),
        (1522, 490), (1515, 460), (1500, 440), (1480, 445), (1470, 470), (1450, 500), (1440, 530), (1420, 538),
        (1392, 535), (1385, 515), (1395, 490), (1405, 460), (1398, 430), (1382, 445), (1365, 470), (1345, 500),
        (1322, 520), (1310, 505), (1320, 470), (1340, 440), (1362, 410), (1380, 380), (1392, 350), (1395, 320),
        (1408, 295), (1430, 282), (1455, 272), (1460, 250),
    ],
}
# 몸 윤곽과 겹치지 않는 가는 무기 부분
EXTRA = {
    "seorin": [[(195, 490), (215, 480), (520, 712), (510, 730), (190, 510)]],
    "rik": [[(1068, 478), (1084, 488), (1018, 548), (1004, 538)]],
}
# 발 위치(시안 좌표): 지면에 닿는 점. 컷아웃 하단 중앙과의 차이를 메타로 남긴다
PORTRAITS = {"seorin": (30, 24, 134, 128), "rik": (1233, 28, 1297, 92), "bru": (1441, 28, 1505, 92)}


def cutout(mockup: Image.Image, name: str) -> Image.Image:
    mask = Image.new("L", mockup.size, 0)
    d = ImageDraw.Draw(mask)
    d.polygon(OUTLINES[name], fill=255)
    for poly in EXTRA.get(name, []):
        d.polygon(poly, fill=255)
    mask = mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.0))
    box = mask.getbbox()
    rgba = mockup.crop(box).convert("RGBA")
    rgba.putalpha(mask.crop(box))
    return rgba


def clone_patch(img: Image.Image, src_box, dst_box) -> None:
    """src 영역을 dst 크기로 늘려 부드러운 테두리로 덮는다 (웅덩이 제거용)."""
    patch = img.crop(src_box).resize((dst_box[2] - dst_box[0], dst_box[3] - dst_box[1]), Image.LANCZOS)
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, patch.width - 1, patch.height - 1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(14))
    img.paste(patch, (dst_box[0], dst_box[1]), mask)


def build(src: Path) -> None:
    backdrop = Image.open(src / "tollgate-spatial-backdrop.png").convert("RGB")
    mockup = Image.open(src / "mockup-06-spatial-battle.png").convert("RGB")
    for sub in ("units", "portraits", "fx", "fonts"):
        (ASSETS / sub).mkdir(parents=True, exist_ok=True)

    # 지형 조각은 웅덩이를 지우기 전에 잘라 둔다
    mud = backdrop.crop((1250, 660, 1660, 850)).convert("RGBA")
    m = Image.new("L", mud.size, 0)
    ImageDraw.Draw(m).ellipse((6, 6, mud.width - 7, mud.height - 7), fill=255)
    mud.putalpha(m.filter(ImageFilter.GaussianBlur(10)))
    mud.save(ASSETS / "fx" / "mud.png")
    bush = backdrop.crop((0, 560, 170, 720)).convert("RGBA")
    bm = Image.new("L", bush.size, 0)
    ImageDraw.Draw(bm).ellipse((4, 20, bush.width - 5, bush.height - 5), fill=255)
    bush.putalpha(bm.filter(ImageFilter.GaussianBlur(8)))
    bush.save(ASSETS / "fx" / "bush.png")
    wall = backdrop.crop((1290, 262, 1460, 352)).convert("RGBA")
    wall.save(ASSETS / "fx" / "wall-stub.png")

    # 웅덩이 제거: 왼쪽 아래 판석을 복제
    clone_patch(backdrop, (560, 640, 1000, 860), (1200, 620, 1672, 880))
    clone_patch(backdrop, (700, 700, 1000, 860), (1380, 700, 1672, 900))
    backdrop.resize(WINDOW, Image.LANCZOS).save(ASSETS / "backdrop.png")

    for name in OUTLINES:
        cutout(mockup, name).save(ASSETS / "units" / f"{name}.png")
    for name, box in PORTRAITS.items():
        mockup.crop(box).resize((96, 96), Image.LANCZOS).save(ASSETS / "portraits" / f"{name}.png")

    fonts = Path(r"C:\Windows\Fonts")
    for f in ("NotoSansKR-VF.ttf", "NotoSerifKR-VF.ttf"):
        if (fonts / f).exists():
            shutil.copy(fonts / f, ASSETS / "fonts" / f)
    print("assets written to", ASSETS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    build(Path(ap.parse_args().src))
