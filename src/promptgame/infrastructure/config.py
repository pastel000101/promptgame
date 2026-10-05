"""설정 한 곳 (설계서 §6). 환경변수로 바꾼다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL = "gemma4:12b-it-qat"
DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 15.0
DEFAULT_LOG_DIR = "logs"


@dataclass(frozen=True)
class Config:
    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_URL
    timeout: float = DEFAULT_TIMEOUT
    log_dir: str = DEFAULT_LOG_DIR
    seed: int | None = None


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    seed = env.get("PROMPTGAME_SEED", "").strip()
    return Config(
        model=env.get("PROMPTGAME_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        ollama_url=(env.get("PROMPTGAME_OLLAMA_URL", DEFAULT_URL).strip() or DEFAULT_URL).rstrip("/"),
        timeout=float(env.get("PROMPTGAME_TIMEOUT", "").strip() or DEFAULT_TIMEOUT),
        log_dir=env.get("PROMPTGAME_LOG_DIR", DEFAULT_LOG_DIR).strip() or DEFAULT_LOG_DIR,
        seed=int(seed) if seed else None,
    )
