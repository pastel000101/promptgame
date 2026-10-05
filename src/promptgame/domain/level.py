"""전장과 모든 규칙 수치. 수치는 이 파일에서만 정의한다 (설계서 §1)."""

WIDTH = 10
HEIGHT = 8

MAP_ROWS = (
    "##########",
    "#....#...#",
    "#....#...#",
    "#....~~..#",
    "#..,,~...#",
    "#..,,....#",
    "#........#",
    "##########",
)

FLOOR = "."
WALL = "#"
MUD = "~"
BUSH = ","

# 지형별 걷기 비용(AP 또는 적 이동력). None은 진입 불가.
MOVE_COST = {FLOOR: 1, BUSH: 1, MUD: 2, WALL: None}
DASH_ALLOWED = {FLOOR}
BLOCKS_SIGHT = {WALL, BUSH}

PLAYER_START = (2, 2)
ENEMY_STARTS = (("goblin", (7, 2)), ("orc", (6, 6)))

PLAYER_STATS = {
    "hp": 20,
    "mana": 6,
    "accuracy": 85,
    "evasion": 15,
    "armor": 1,
    "weapon_damage": 5,
}
PLAYER_EQUIPMENT = {"weapon": "장검", "armor": "가죽 갑옷"}
PLAYER_POTIONS = 1
PLAYER_KNIVES = 2

ENEMY_STATS = {
    "goblin": {"hp": 10, "move_points": 2, "accuracy": 60, "evasion": 20, "armor": 0, "weapon_damage": 3},
    "orc": {"hp": 18, "move_points": 1, "accuracy": 55, "evasion": 5, "armor": 2, "weapon_damage": 6},
}
ENEMY_ORDER = ("goblin", "orc")

AP_PER_TURN = 4
MAX_STEPS = 3

# 동작 비용 (§1.3)
ATTACK_AP = 2
WHIRLWIND_AP = 3
WHIRLWIND_COOLDOWN = 2  # 사용한 다음 턴부터 이만큼의 플레이어 턴 동안 사용할 수 없다
WHIRLWIND_HIT_MOD = -10
FIREBALL_AP = 2
FIREBALL_MANA = 3
FIREBALL_RANGE = 4
FIREBALL_HIT_MOD = 10
FIREBALL_DAMAGE = 6
FIREBALL_BURN_TURNS = 2
POTION_AP = 1
POTION_HEAL = 8
KNIFE_AP = 1
KNIFE_RANGE = 3
KNIFE_DAMAGE = 3
GUARD_AP = 1
WAIT_AP = 0
DASH_CELLS_PER_AP = 2
DASH_MAX_CELLS = 4

# 방법 수식 (§1.4)
DASH_ATTACK_MOD = -10
DASH_EVASION_MOD = -10
STRONG_AP = 1
STRONG_HIT_MOD = -10
STRONG_DAMAGE_BONUS = 3
AIM_AP = 1
AIM_HIT_MOD = -20
HEAD_DAMAGE_MULTIPLIER = 1.5
ARM_DAMAGE_PENALTY = 2
LEG_INJURY_TURNS = 2
STAGGER_TURNS = 1

# 판정 (§1.5, §1.6)
HIT_MIN = 5
HIT_MAX = 95
DICE_SIDES = 100
STAGGERED_TARGET_MOD = 15
BUSH_TARGET_MOD = -15
STAGGERED_ATTACKER_MOD = -20
GUARD_EVASION_MOD = 20
BURN_DAMAGE = 2
