"""턴 기록 JSON Lines 파일. 기록 실패는 플레이를 막지 않는다."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path


class JsonlTurnLog:
    def __init__(self, log_dir: str):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path: str | None = str(Path(log_dir) / f"turns-{stamp}.jsonl")
        self._lock = threading.Lock()
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")
        except OSError as exc:
            print(f"[promptgame] 기록 파일을 열 수 없어 기록 없이 진행합니다: {exc}", file=sys.stderr)
            self._file = None
            self.path = None

    def write(self, record: dict) -> None:
        if self._file is None:
            return
        try:
            with self._lock:
                self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._file.flush()
        except (OSError, TypeError, ValueError) as exc:
            print(f"[promptgame] 기록 실패: {exc}", file=sys.stderr)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
