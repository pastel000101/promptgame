"""해석 정확도·응답 시간 측정 도구 (설계서 §8.1, 기능 정의서 T01). 플레이 기능이 아니다.

모델을 미리 적재한 뒤 문장마다 1회 해석해, 정규화한 계획 JSON이 기대 계획 후보 중 하나와 같으면 정답으로 센다.
응답 시간에는 형식 오류 재시도가 포함된다. 결과는 docs/eval/에 JSON으로 저장한다.

    uv run python tools/eval_interpreter.py [--model gemma4:12b-it-qat]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from promptgame.application.interpreter import Interpreter  # noqa: E402
from promptgame.domain.state import GameState, new_game  # noqa: E402
from promptgame.infrastructure.config import load_config  # noqa: E402
from promptgame.infrastructure.ollama import OllamaClient  # noqa: E402

CASES = Path(__file__).with_name("eval_cases.json")
STEP_DEFAULTS = {"target": None, "move": None, "aim": "none", "power": "normal", "ability": None, "item": None}
MOVE_DEFAULTS = {"toward": None, "away_from": None, "direction": None, "cells": None}


def _target(raw):
    if raw is None:
        return None
    return {"kind": raw["kind"], "relation": raw.get("relation")}


def normalize(plan: dict) -> dict:
    """생략한 필드를 기본값으로 채워 비교 가능한 형태로 만든다."""
    steps = []
    for raw in plan.get("steps", []):
        step = {**STEP_DEFAULTS, **raw}
        step["target"] = _target(step["target"])
        if step["move"] is not None:
            move = {**MOVE_DEFAULTS, **step["move"]}
            move["toward"] = _target(move["toward"])
            move["away_from"] = _target(move["away_from"])
            step["move"] = move
        steps.append({k: step[k] for k in ("act", *STEP_DEFAULTS)})
    return {"steps": steps, "clarify": plan.get("clarify")}


def build_state(situation: dict) -> GameState:
    s = new_game()
    if "player" in situation:
        s.player.pos = tuple(situation["player"])
    if "hp" in situation:
        s.player.hp = situation["hp"]
    for uid in ("goblin", "orc"):
        enemy = s.enemy(uid)
        if uid in situation:
            enemy.pos = tuple(situation[uid])
        if f"{uid}_hp" in situation:
            enemy.hp = situation[f"{uid}_hp"]
        if f"{uid}_status" in situation:
            enemy.statuses.update(situation[f"{uid}_status"])
    s.last_attacked = situation.get("last_attacked")
    return s


def percentile(values: list[float], q: float) -> float:
    """가장 가까운 순위 방식."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def run(model: str, url: str, timeout: float) -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    client = OllamaClient(url, model, timeout)
    started = time.perf_counter()
    client.preload()
    preload_ms = (time.perf_counter() - started) * 1000
    interpreter = Interpreter(client)
    results = []
    for case in cases:
        r = interpreter.interpret(case["sentence"], build_state(case["situation"]))
        got = None
        if r.source == "llm":
            got = normalize({"steps": r.plan.to_dict()["steps"] if r.plan else [], "clarify": r.clarify})
        expected = [normalize(e) for e in case["expected"]]
        correct = got is not None and got in expected
        results.append({
            "id": case["id"], "category": case["category"], "example": case.get("example"),
            "sentence": case["sentence"], "correct": correct, "source": r.source, "failure": r.failure,
            "attempts": r.attempts, "elapsed_ms": round(r.elapsed_ms, 1), "got": got, "expected": expected,
            "raw": r.raw,
        })
        mark = "O" if correct else "X"
        print(f"{mark} {case['id']} {r.elapsed_ms:7.0f} ms  {case['sentence']}")
    times = [x["elapsed_ms"] for x in results]
    by_category = {}
    for x in results:
        c = by_category.setdefault(x["category"], {"correct": 0, "total": 0})
        c["total"] += 1
        c["correct"] += int(x["correct"])
    examples = [x for x in results if x["example"]]
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model,
        "ollama_url": url,
        "timeout_s": timeout,
        "method": "모델 미리 적재 후 문장마다 1회, 재시도 포함 응답 시간, 정규화 계획이 기대 후보 중 하나와 같으면 정답",
        "preload_ms": round(preload_ms, 1),
        "total": len(results),
        "correct": sum(x["correct"] for x in results),
        "by_category": by_category,
        "examples_correct": f"{sum(x['correct'] for x in examples)}/{len(examples)}",
        "median_ms": round(statistics.median(times), 1),
        "p95_ms": round(percentile(times, 95), 1),
        "retries": sum(1 for x in results if x["attempts"] > 1),
        "failures": sum(1 for x in results if x["source"] != "llm"),
        "results": results,
    }


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=config.model)
    parser.add_argument("--url", default=config.ollama_url)
    parser.add_argument("--timeout", type=float, default=config.timeout)
    parser.add_argument("--out", default=str(ROOT / "docs" / "eval"))
    args = parser.parse_args()
    report = run(args.model, args.url, args.timeout)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = args.model.replace(":", "_").replace("/", "_")
    path = out_dir / f"eval-{safe}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"정답 {report['correct']}/{report['total']} · 중앙값 {report['median_ms']} ms · 95퍼센타일 {report['p95_ms']} ms "
          f"· 재시도 {report['retries']} · 실패 {report['failures']}")
    print(f"결과 파일: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
