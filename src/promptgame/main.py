"""구성 요소 생성과 연결: 설정 → 클라이언트 → 기록 → 해석기 → 세션 → 화면."""

from __future__ import annotations

import random
import threading

from promptgame.application.interpreter import Interpreter
from promptgame.application.session import GameSession
from promptgame.infrastructure.config import Config, load_config
from promptgame.infrastructure.ollama import OllamaClient
from promptgame.infrastructure.turn_log import JsonlTurnLog


def seed_source(config: Config):
    if config.seed is not None:
        return lambda: config.seed
    system = random.SystemRandom()
    return lambda: system.randrange(1, 1_000_000)


def build(config: Config) -> tuple[GameSession, OllamaClient, JsonlTurnLog]:
    client = OllamaClient(config.ollama_url, config.model, config.timeout)
    log = JsonlTurnLog(config.log_dir)
    session = GameSession(Interpreter(client), log, seed_source(config), model=config.model)
    return session, client, log


def main(max_frames: int | None = None) -> int:
    from promptgame.presentation.app import App

    config = load_config()
    session, client, log = build(config)
    threading.Thread(target=client.preload, daemon=True).start()
    try:
        App(session).run(max_frames=max_frames)
    finally:
        log.close()
        print(f"[promptgame] 기록 파일: {log.path or '없음'}")
    return 0
