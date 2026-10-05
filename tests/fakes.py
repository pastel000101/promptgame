"""대역: 정해진 응답을 돌려주는 가짜 LLM 클라이언트와 메모리 기록."""

import json

from promptgame.application.ports import LlmError


class FakeClient:
    model = "fake"

    def __init__(self, *replies):
        """replies: 문자열(응답 본문), dict(JSON으로 직렬화), LlmError(예외로 던짐)."""
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages, schema):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, LlmError):
            raise reply
        if isinstance(reply, dict):
            return json.dumps(reply, ensure_ascii=False)
        return reply

    def preload(self):
        pass


class MemoryLog:
    path = "memory"

    def __init__(self):
        self.records = []

    def write(self, record):
        json.dumps(record, ensure_ascii=False)  # 직렬화 가능한지 확인
        self.records.append(record)


def step(act, **kw):
    base = {"act": act, "target": None, "move": None, "aim": "none", "power": "normal", "ability": None, "item": None}
    base.update(kw)
    return base


def target(kind="enemy", relation=None):
    return {"kind": kind, "relation": relation}


def move_spec(toward=None, away_from=None, direction=None, cells=None):
    return {"toward": toward, "away_from": away_from, "direction": direction, "cells": cells}


def reply(*steps, clarify=None):
    return {"steps": list(steps), "clarify": clarify}
