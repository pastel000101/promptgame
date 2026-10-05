"""창과 이벤트 루프. 입력을 세션에 넘기고, 매 프레임 끝난 해석을 적용한 뒤 그린다."""

from __future__ import annotations

import pygame

from promptgame.presentation import render
from promptgame.presentation.text_input import TextInput

FPS = 30


class App:
    def __init__(self, session) -> None:
        self.session = session
        self.input = TextInput()
        self.running = False
        self.screen: pygame.Surface | None = None
        self.fonts: render.Fonts | None = None

    def open(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode(render.WINDOW_SIZE)
        pygame.display.set_caption("promptgame — 문장으로 싸우는 턴제 전투")
        self.fonts = render.Fonts()
        if not self.fonts.found:
            print("[promptgame] 한글 글꼴을 찾지 못해 기본 글꼴로 표시합니다")
        pygame.key.start_text_input()
        pygame.key.set_text_input_rect(pygame.Rect(16, render.WINDOW_SIZE[1] - 56, 400, 40))
        self.running = True

    def process_events(self, events) -> None:
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
                return
            submitted = self.input.handle(event)
            if submitted:
                self.session.submit(submitted)

    def frame(self, events) -> None:
        self.process_events(events)
        self.session.poll()
        render.draw(self.screen, self.session, self.input, self.fonts)
        pygame.display.flip()
        self.session.mark_displayed()  # 계획 줄을 그린 뒤에만 자동 실행 시간을 잰다

    def run(self, max_frames: int | None = None) -> None:
        self.open()
        clock = pygame.time.Clock()
        frames = 0
        try:
            while self.running:
                self.frame(pygame.event.get())
                clock.tick(FPS)
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
        finally:
            pygame.key.stop_text_input()
            pygame.quit()
