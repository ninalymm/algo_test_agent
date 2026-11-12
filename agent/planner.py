"""规划层：变更 → 执行计划。

规则优先：变更类型 → 场景清单 → 档位 → 阈值，全部来自 data/ 下的配置。
LLM 仅在变更类型无法识别时兜底（当前返回全量场景，宁慢不漏）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from agent.models import Change, Plan
from tools.llm import parse_change

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load_mapping() -> dict[str, dict]:
    with open(DATA / "mapping.csv", encoding="utf-8") as f:
        return {row["change_kind"]: row for row in csv.DictReader(f)}


def load_scenes() -> list[dict]:
    return json.loads((DATA / "scenes.json").read_text(encoding="utf-8"))


def build_plan(change: Change) -> Plan:
    mapping = load_mapping()
    scenes = load_scenes()
    rule = mapping.get(change.kind)

    if rule is None:
        # 兜底：类型无法识别 → 跑全量，宁可慢不可漏
        return Plan(
            scenes=[s["name"] for s in scenes],
            qps_levels=[1200],
            notes=["未知变更类型，回退全量场景"],
        )

    names = [s["name"] for s in scenes if s["category"] in rule["categories"].split("|")]
    return Plan(
        scenes=names,
        qps_levels=[int(x) for x in rule["qps_levels"].split("|")],
        diff_threshold=float(rule["diff_threshold"]),
        steps=[
            ("check_recording", []),
            ("perf_test", ["check_recording"]),
            ("diff", ["check_recording"]),
            ("judge", ["perf_test", "diff"]),
        ],
        notes=[f"命中规则：{change.kind}"],
    )


def plan_from_text(text: str) -> tuple[Change, Plan]:
    parsed = parse_change(text)
    change = Change(raw=text, kind=parsed.get("kind", "unknown"),
                    app=parsed.get("app", "unknown"), graph=parsed.get("graph", "unknown"))
    return change, build_plan(change)