"""한 줄 한글 입력: SDL TEXTEDITING(조합)·TEXTINPUT(확정)·KEYDOWN 처리."""

from __future__ import annotations

import pygame


class TextInput:
    def __init__(self) -> None:
        self.text = ""  # 확정된 글자
        self.composition = ""  # IME 조합 중인 글자
        self._committed_on_enter = ""

    def handle(self, event: pygame.event.Event) -> str | None:
        """이벤트를 반영하고, Enter로 제출된 문장(앞뒤 공백 제거, 비어 있지 않음)을 돌려준다."""
        if event.type == pygame.TEXTEDITING:
            self.composition = event.text
            return None
        if event.type == pygame.TEXTINPUT:
            if self._committed_on_enter and event.text == self._committed_on_enter:
                # Enter 때 직접 확정한 조합 글자를 IME가 뒤늦게 다시 확정하는 경우
                self._committed_on_enter = ""
                return None
            self._committed_on_enter = ""
            self.text += event.text
            self.composition = ""
            return None
        if event.type != pygame.KEYDOWN:
            return None
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.composition:
                self._committed_on_enter = self.composition
                self.text += self.composition
                self.composition = ""
            submitted = self.text.strip()
            self.text = ""
            return submitted or None
        if event.key == pygame.K_BACKSPACE:
            if not self.composition:  # 조합 중이면 IME가 조합만 지운다
                self.text = self.text[:-1]
            return None
        if event.key == pygame.K_ESCAPE:
            self.text = ""
            self.composition = ""
        return None
