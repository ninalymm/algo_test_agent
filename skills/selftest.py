"""Skill：研发自测 —— 预检 → 计划 → 确认后执行。

执行本身仍走原来的 planner/executor/judge（Mock 链路），
新增的是「变更上下文」和「预检」。
"""

from __future__ import annotations

import json

from context import graph_scene
from observe.tracer import Tracer
from skills import cards
from tools.r2_mock import R2Mock

REQUIRED = ("scene", "qps", "threshold")


def precheck(change: dict, scenes: list[str]) -> list[str]:
    """启动前的确定性检查 —— 只挡「确定有问题」的，不挡「可能有风险」的。"""
    problems = []
    if not change:
        problems.append("未关联到代码变更，无法确认影响面")
    if not scenes:
        problems.append("未匹配到任何场景，检查图 id 是否正确")
    if change and not change.get("graph_ids"):
        problems.append("变更缺少 graph_id，无法展开场景")
    return problems


def run(conn, text: str, commit: str | None = None) -> dict:
    if commit is None:
        import re
        m = re.search(r"([A-Za-z0-9\-]{4,})", text.replace("我改完了", ""))
        commit = m.group(1) if m else None

    with Tracer("selftest", conn) as t:
        with t.span("resolve_change", commit=commit or "-"):
            change = _find_change(conn, commit) if commit else None

        if not change:
            return {"reply": "没找到这个提交关联的变更，请提供 commit 或 MR 号。", "card": None}

        graph_ids = change["graph_ids"]
        with t.span("expand_scenes", graph=",".join(graph_ids)):
            expanded = [graph_scene.expand_scenes(conn, g) for g in graph_ids]
            scenes = sorted({s for e in expanded for s in e["scenes"]})

        with t.span("precheck", scenes=len(scenes)):
            problems = precheck(change, scenes)

        if problems:
            return {"reply": "预检没通过，先别跑任务。",
                    "card": cards.blocked_card("预检未通过", problems)}

        shared = [e for e in expanded if e["shared"]]
        lines = [
            f"变更：{change['id']}（{change['commit_id']}）",
            f"影响图：{', '.join(graph_ids)}",
            f"待跑场景：{', '.join(scenes)}",
        ]
        if shared:
            lines.append(f"⚠️ {'、'.join(e['graph_id'] for e in shared)} 是共享图，已自动扩到全部场景")
        lines.append("预计耗时 20 分钟")

        return {"reply": "计划如下，确认后我就开始跑。",
                "card": cards.confirm_card("待确认的执行计划", lines),
                "plan": {"change": change["id"], "scenes": scenes},
                "trace_id": t.trace_id}


def execute(conn, plan: dict) -> dict:
    """确认后真正执行（当前跑 Mock 链路）。"""
    from agent.executor import Executor
    from agent.judge import judge
    from agent.models import Plan
    from tools.diff_mock import DiffMock
    from tools.forcebot_mock import ForceBotMock

    p = Plan(
        scenes=plan["scenes"],
        qps_levels=[1200, 1600],
        steps=[
            ("check_recording", []),
            ("perf_test", ["check_recording"]),
            ("diff", ["check_recording"]),
            ("judge", ["perf_test", "diff"]),
        ],
    )
    with Tracer("execute", conn) as t:
        with t.span("check_recording", scenes=len(p.scenes)):
            ex = Executor(R2Mock(), ForceBotMock(), DiffMock())
            state = ex.run(p)
        with t.span("judge"):
            v = judge(p, state)

    diffs = v.evidence.get("diff", {})
    worst = max((d.get("diff_rate", 0) for d in diffs.values()), default=0.0)
    metrics = [{"name": "diff", "value": f"{worst:.2%}", "ok": worst <= p.diff_threshold}]
    return {"reply": "跑完了。", "card": cards.verdict_card("自测结果", "pass" if v.passed else "fail",
                                                           metrics, "；".join(v.reasons)),
            "trace_id": t.trace_id}


def _find_change(conn, commit: str) -> dict | None:
    row = conn.execute("SELECT id FROM change WHERE commit_id LIKE ? OR mr LIKE ? OR id = ?",
                       (f"%{commit}%", f"%{commit}%", commit)).fetchone()
    if not row:
        return None
    from store import repo
    return repo.get_change(conn, row["id"])
