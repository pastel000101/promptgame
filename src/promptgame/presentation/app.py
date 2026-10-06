"""창과 이벤트 루프. 입력을 세션에 넘기고, 판정이 끝난 턴의 이벤트를 연출 큐로 재생한 뒤 그린다."""

from __future__ import annotations

import pygame

from promptgame.presentation import render
from promptgame.presentation.animation import Animator
from promptgame.presentation.assets import Assets
from promptgame.presentation.camera import Camera
from promptgame.presentation.display import DisplayState
from promptgame.presentation.text_input import TextInput

FPS = 30


class App:
    def __init__(self, session, debug: bool = False) -> None:
        self.session = session
        self.input = TextInput()
        self.running = False
        self.screen: pygame.Surface | None = None
        self.debug = debug
        self.assets: Assets | None = None
        self.renderer: render.Renderer | None = None
        self.cam = Camera.default()
        self.display: DisplayState | None = None
        self.animator: Animator | None = None
        self._game_id = None
        self._pending_validation = None

    def open(self, headless_surface: pygame.Surface | None = None) -> None:
        pygame.init()
        if headless_surface is None:
            self.screen = pygame.display.set_mode(render.WINDOW_SIZE)
            pygame.display.set_caption("promptgame — 문장으로 싸우는 턴제 전투")
        else:
            self.screen = headless_surface
        self.assets = Assets(render.SCENE_SIZE)
        self.renderer = render.Renderer(self.assets, self.cam, self.debug)
        self.display = DisplayState.from_game(self.session.state)
        self.animator = Animator(self.display, self.cam)
        self._game_id = self.session.game_id
        pygame.key.start_text_input()
        pygame.key.set_text_input_rect(pygame.Rect(16, render.WINDOW_SIZE[1] - 36, 600, 30))
        self.running = True

    def process_events(self, events) -> None:
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                self.debug = not self.debug
                if self.renderer:
                    self.renderer.debug = self.debug
                continue
            submitted = self.input.handle(event)
            if submitted:
                if self.session.submit(submitted) in ("started", "restart") and self.animator is not None:
                    self.animator.current_line = None

    def frame(self, events, dt: float = 1 / FPS) -> None:
        self.process_events(events)
        if not self.running:
            return
        was_phase = self.session.phase
        self.session.poll()
        if self.session.phase == "interpreting" and was_phase != "interpreting":
            self.animator.current_line = None  # 새 문장: 이전 턴의 결과 줄을 지운다
        if self.session.game_id != self._game_id:
            # 다시 시작: 연출을 끊고 표시 상태를 새 판으로
            self._game_id = self.session.game_id
            self.animator.clear()
            self.animator.restart_fade()
            self.display.sync(self.session.state)
            self._pending_validation = None
        if self.session.phase == "planned":
            self._pending_validation = self.session.current_validation()
        taken = self.session.take_turn_events()
        if taken is not None:
            events_list, _validation = taken
            try:
                self.animator.start(events_list, self.session.state.terrain)
            except Exception as exc:  # 연출 구성 실패는 판정과 무관하므로 건너뛴다
                print(f"[promptgame] 연출을 만들지 못해 건너뜁니다: {exc!r}")
                self.animator.clear()
                self.display.sync(self.session.state)
                self.session.animation_done()
        if self.session.phase == "animating":
            try:
                self.animator.update(dt)
            except Exception as exc:
                print(f"[promptgame] 연출 중 오류, 결과 상태로 맞춥니다: {exc!r}")
                self.animator.clear()
            if not self.animator.running:
                self.display.sync(self.session.state)
                self.session.animation_done()
        else:
            self.animator.update(dt)  # 남은 파티클·팝업만 흘린다
            if self.session.phase == "idle" and not self.display.matches(self.session.state):
                self.display.sync(self.session.state)
        self.renderer.draw(self.screen, self.session, self.display, self.animator, self.input, self._pending_validation)
        if self.screen is pygame.display.get_surface():
            pygame.display.flip()
        self.session.mark_displayed()  # 계획 줄을 그린 뒤에만 자동 실행 시간을 잰다

    def run(self, max_frames: int | None = None) -> None:
        self.open()
        clock = pygame.time.Clock()
        frames = 0
        try:
            while self.running:
                dt = clock.tick(FPS) / 1000.0
                self.frame(pygame.event.get(), min(dt, 0.1))
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
        finally:
            pygame.key.stop_text_input()
            pygame.quit()
