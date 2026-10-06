"""실제 게임 코드로 한 턴을 돌리며 화면을 저장한다 (창 없이, 검증·보고용).

가짜 해석기가 정해진 계획을 돌려주고, 나머지(검증·실행·판정·연출·그리기)는 실제 코드가 한다.
    uv run python tools/capture_frames.py --scenario e1 --out docs/frames
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

from promptgame.application.interpreter import Interpretation  # noqa: E402
from promptgame.application.session import GameSession  # noqa: E402
from promptgame.domain.plan import MoveSpec, Plan, Step, TargetRef  # noqa: E402
from promptgame.presentation import render  # noqa: E402
from promptgame.presentation.app import App  # noqa: E402

ENEMY = TargetRef("enemy")
SCENARIOS = {
    # (상태 조정, 문장, 계획, 시드)
    "e1": (lambda s: (setattr(s.player, "pos", (7, 5)), setattr(s.enemy("orc"), "pos", (2, 6))),
           "신속하게 다가가서 녀석의 머리를 벤다",
           Plan((Step("dash", move=MoveSpec(toward=ENEMY)), Step("attack", target=ENEMY, aim="head"))), 5643),
    "e2": (lambda s: setattr(s.enemy("orc"), "pos", (2, 6)),
           "화염구로 오크를 태워",
           Plan((Step("cast", target=TargetRef("orc"), ability="fireball"),)), 186),
    "walk": (lambda s: None, "고블린에게 3칸 다가가서 방어 자세를 잡아",
             Plan((Step("move", move=MoveSpec(toward=TargetRef("goblin"), cells=3)), Step("guard"))), 2026),
    "e6": (lambda s: (setattr(s.player, "pos", (7, 3)), setattr(s.enemy("orc"), "pos", (6, 5)),
                      setattr(s.enemy("goblin"), "hp", 3), s.enemy("goblin").statuses.__setitem__("stagger", 1)),
           "비틀거리는 고블린을 베고 또 벤다",
           Plan((Step("attack", target=TargetRef("goblin", "staggered")), Step("attack", target=TargetRef("goblin", "staggered")))), 55),
}


class ScriptedInterpreter:
    def __init__(self, plan: Plan):
        self.plan = plan

    def interpret(self, sentence, state):
        return Interpretation(source="llm", plan=self.plan, attempts=1, elapsed_ms=0.0)


class NoLog:
    path = None

    def write(self, record):
        pass


def run(scenario: str, out: Path, every: int = 3, debug: bool = False) -> list[Path]:
    setup, sentence, plan, seed = SCENARIOS[scenario]
    pygame.init()
    surface = pygame.Surface(render.WINDOW_SIZE)
    session = GameSession(ScriptedInterpreter(plan), NoLog(), lambda: seed, spawn=lambda fn: fn(), model="scripted",
                          plan_display_seconds=0.5)
    setup(session.state)
    app = App(session, debug=debug)
    app.open(headless_surface=surface)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    dt = 1 / 30
    frame = 0

    def snap(tag: str) -> None:
        p = out / f"{scenario}-{frame:03d}-{tag}.png"
        pygame.image.save(surface, str(p))
        saved.append(p)

    app.frame([], dt)
    snap("start")
    session.submit(sentence)
    phase_seen = set()
    for _ in range(400):
        app.frame([], dt)
        frame += 1
        phase = session.phase
        if phase not in phase_seen:
            phase_seen.add(phase)
            snap(phase)
        elif phase == "animating" and frame % every == 0:
            snap("anim")
        if phase == "idle" and "animating" in phase_seen:
            snap("end")
            break
    pygame.quit()
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="e1", choices=sorted(SCENARIOS))
    ap.add_argument("--out", default="docs/frames")
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    files = run(a.scenario, Path(a.out), a.every, a.debug)
    print(len(files), "frames ->", a.out)
