"""결과 설명 템플릿 (설계서 §2.7). 이름·조사·단계 표기를 만든다."""

from __future__ import annotations

NAMES = {"player": "용병", "goblin": "고블린", "orc": "오크"}
DIRECTION_NAMES = {"N": "북쪽", "E": "동쪽", "S": "남쪽", "W": "서쪽"}
TERRAIN_NAMES = {"#": "벽", "~": "진흙", ",": "덤불", ".": "바닥"}
AIM_NAMES = {"head": "머리", "arm": "팔", "leg": "다리"}
CIRCLED = "①②③④⑤"


def name(kind: str) -> str:
    return NAMES.get(kind, kind)


def num(index: int) -> str:
    return CIRCLED[index]


def num_range(start: int, end: int) -> str:
    return num(start) if start == end else f"{num(start)}~{num(end)}"


def pos_text(pos: tuple[int, int]) -> str:
    return f"({pos[0]},{pos[1]})"


def _has_batchim(word: str) -> bool:
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - ord("가")) % 28 != 0
    return False


def josa(word: str, pair: str) -> str:
    """pair는 '은/는', '이/가', '을/를', '과/와' 형식. 받침이 있으면 앞쪽."""
    with_batchim, without = pair.split("/")
    return word + (with_batchim if _has_batchim(word) else without)


def attack_label(aim: str, power: str, weapon: str = "베기") -> str:
    core = "강타" if power == "strong" and weapon == "베기" else weapon
    if aim != "none":
        return f"{AIM_NAMES[aim]} 조준 {core}"
    return core


def roll_text(chance: int, dice: int, hit: bool) -> str:
    return f"명중 {chance}% · 주사위 {dice} · " + ("명중!" if hit else "빗나감")


def damage_text(damage: int, before: int, after: int) -> str:
    return f"피해 {damage} ({before}→{after})"
