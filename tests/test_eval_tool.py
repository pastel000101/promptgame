"""측정 도구의 문장 구성·정규화 (LLM 호출 없음)."""

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import eval_interpreter as ev  # noqa: E402
from promptgame.application.intent import Clarify, parse_response  # noqa: E402
from promptgame.application.prompt import EXAMPLES  # noqa: E402


def load_cases():
    return json.loads((TOOLS / "eval_cases.json").read_text(encoding="utf-8"))["cases"]


def test_thirty_cases_in_three_groups_with_design_examples():
    cases = load_cases()
    assert len(cases) == 30
    assert {c: sum(1 for x in cases if x["category"] == c) for c in ("single", "compound", "target")} == {
        "single": 10, "compound": 10, "target": 10}
    sentences = {c["sentence"] for c in cases}
    assert all(sentence in sentences for sentence, _ in EXAMPLES)


def test_expected_plans_are_valid_responses():
    for case in load_cases():
        ev.build_state(case["situation"])
        for expected in case["expected"]:
            parsed = parse_response(json.dumps(ev.normalize(expected)))
            assert isinstance(parsed, Clarify) == bool(expected.get("clarify")), case["id"]


def test_normalize_matches_full_plan_json():
    sentence, plan = EXAMPLES[0]
    full = ev.normalize({**plan.to_dict(), "clarify": None})
    short = ev.normalize({"steps": [{"act": "dash", "move": {"toward": {"kind": "enemy"}}},
                                    {"act": "attack", "target": {"kind": "enemy"}, "aim": "head"}]})
    assert full == short


def test_percentile_nearest_rank():
    assert ev.percentile(list(range(1, 21)), 95) == 19
    assert ev.percentile([5.0], 95) == 5.0
