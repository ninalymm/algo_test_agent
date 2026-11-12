"""Skill：自然语言驱动压测 / diff。

「帮我跑一下 20260301-0001 的压测，1200 档」
  → 解析出 场景 / QPS / 类型 → 计划确认 → 执行
"""

from __future__ import annotations

import re

from agent.executor import Executor
from agent.judge import judge
from agent.models import Plan
from observe.tracer import Tracer
from skills import cards
from tools.diff_mock import DiffMock
from tools.forcebot_mock import ForceBotMock
from tools.r2_mock import R2Mock

DEFAULT_QPS = [1200, 1600]


def parse(text: str) -> dict:
    scene = re.search(r"(\d{8}-\d{4})", text)
    qps = [int(x) for x in re.findall(r"(\d{3,4})\s*(?:qps|档)", text)] or DEFAULT_QPS

    wants_load = any(k in text for k in ("压测", "加压", "性能", "qps"))
    wants_diff = ("diff" in text.lower()) or any(k in text for k in ("比对", "一致性", "结果对比"))
    if not wants_load and not wants_diff:
        wants_load = wants_diff = True

    return {"scene": scene.group(1) if scene else None,
            "qps": sorted(set(qps)), "load": wants_load, "diff": wants_diff}


def plan_card(parsed: dict) -> dict:
    if not parsed["scene"]:
        return cards.blocked_card("缺少场景", ["请给出场景 id，例如 20260301-0001"])

    kinds = []
    if parsed["load"]:
        kinds.append(f"压测（{', '.join(str(q) + 'qps' for q in parsed['qps'])}）")
    if parsed["diff"]:
        kinds.append("diff 比对")
    lines = [f"场景：{parsed['scene']}", f"类型：{' + '.join(kinds)}", "预计耗时 15–25 分钟"]
    return cards.confirm_card("待确认的执行计划", lines)


def run(conn, text: str) -> dict:
    parsed = parse(text)
    card = plan_card(parsed)
    if card["type"] == "blocked":
        return {"reply": "还差一个信息。", "card": card}
    return {"reply": "计划如下，确认后开始。", "card": card, "plan": parsed}


def execute(conn, plan: dict) -> dict:
    scenes = plan.get("scenes") or ([plan["scene"]] if plan.get("scene") else [])
    qps = plan.get("qps") or DEFAULT_QPS
    steps = [("check_recording", [])]
    if plan.get("load", True):
        steps.append(("load_test", ["check_recording"]))
    if plan.get("diff", True):
        steps.append(("diff", ["check_recording"]))
    steps.append(("judge", [s[0] for s in steps[1:]] or ["check_recording"]))

    p = Plan(scenes=scenes, qps_levels=qps, steps=steps)

    with Tracer("run", conn) as t:
        with t.span("execute", scenes=len(scenes), qps=len(qps)):
            state = Executor(R2Mock(), ForceBotMock(), DiffMock()).run(p)
        with t.span("judge"):
            v = judge(p, state)

    metrics = []
    if "diff" in state:
        worst = max((d.get("diff_rate", 0) for d in state["diff"].values()), default=0)
        metrics.append({"name": "diff", "value": f"{worst:.2%}", "ok": worst <= p.diff_threshold})
    if "load_test" in state:
        worst_p99 = max((d["p99"] for by in state["load_test"].values() for d in by.values()), default=0)
        metrics.append({"name": "p99(最高档)", "value": f"{worst_p99:.1f}ms",
                        "ok": worst_p99 <= p.p99_baseline * 1.1})

    return {"reply": "跑完了。", "card": cards.verdict_card(
        f"执行结果 · {', '.join(scenes)}", "pass" if v.passed else "fail",
        metrics, "；".join(v.reasons) or "各项均在阈值内。"), "trace_id": t.trace_id}
