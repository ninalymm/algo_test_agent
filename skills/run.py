"""Skill：自然语言驱动压测 / diff（含多轮澄清与执行轮次记录）。

流程：解析 → 缺槽位就提问（写入 session）→ 用户回答后补全 → 确认卡 → 执行
执行失败/超时不覆盖历史：本轮只落 attempt（aborted），不写 task。
"""

from __future__ import annotations

import re

from agent.executor import Executor
from agent.judge import judge
from agent.models import Plan
from observe.tracer import Tracer
from agent import failure_taxonomy as tax
from skills import clarify, cards
from store import repo
from tools.diff_mock import DiffMock
from tools.forcebot_mock import ForceBotMock
from tools.r2_mock import R2Mock

DEFAULT_QPS = [1200, 1600]


def parse(text: str) -> dict:
    scene = clarify.match_scene(text, [])
    qps = [int(x) for x in re.findall(r"(\d{3,4})\s*(?:qps|档)", text)] or DEFAULT_QPS
    types = clarify.match_types(text)

    load = types in ("load", "both")
    diff = types in ("diff", "both")
    if types is None:
        load = diff = True

    return {"scene": scene, "qps": sorted(set(qps)), "load": load, "diff": diff,
            "types_explicit": types is not None}


def _confirm(parsed: dict) -> dict:
    kinds = []
    if parsed["load"]:
        kinds.append("压测 " + ", ".join(f"{q}qps" for q in parsed["qps"]))
    if parsed["diff"]:
        kinds.append("diff 比对")
    lines = [f"场景：{parsed['scene']}", f"类型：{' + '.join(kinds)}", "预计 15–25 分钟"]
    if not parsed.get("types_explicit"):
        lines.append("（未指定类型，默认压测 + diff；只想跑一种可以直接说）")
    return cards.confirm_card("待确认的执行计划", lines)


def run(conn, text: str, session: dict | None = None) -> dict:
    session = session if session is not None else {}
    known = [r["id"] for r in repo._rows(conn.execute("SELECT id FROM scene ORDER BY id"))]

    # ① 有未完成的多轮提问 → 先把这句话当答案
    if session.get("pending"):
        if clarify.is_cancel(text):
            session.pop("pending", None)
            return {"reply": "已取消。", "card": None}

        p = clarify.Pending.from_dict(session["pending"])

        if p.awaiting == "scene":
            scene = clarify.match_scene(text, known)
            if not scene:
                return {"reply": "还是没认出场景。", "card": clarify.ask_scene(known)}
            p.slots["scene"] = scene
            t = clarify.match_types(text)          # 用户可能一次说全
            if t:
                p.slots["types"] = t

        elif p.awaiting == "types":
            t = clarify.match_types(text)
            if t is None:
                choice = clarify.resolve_choice(text, ["压测", "diff", "两个都跑"])
                t = {"压测": "load", "diff": "diff", "两个都跑": "both"}.get(choice or "")
            if t is None:
                return {"reply": "没听懂。", "card": clarify.ask_types()}
            p.slots["types"] = t

        if "types" not in p.slots:
            p.awaiting = "types"
            session["pending"] = p.to_dict()
            return {"reply": "还差一个信息：跑什么？", "card": clarify.ask_types()}

        session.pop("pending", None)
        parsed = _from_slots(p.slots)
        return {"reply": "好，信息齐了。", "card": _confirm(parsed), "plan": _plan_of(parsed)}

    # ② 新的一轮
    parsed = parse(text)
    if not parsed["scene"]:
        session["pending"] = clarify.Pending("run", "scene", {"qps": parsed["qps"]}).to_dict()
        return {"reply": "还差一个信息：跑哪个场景？", "card": clarify.ask_scene(known)}

    if not parsed["types_explicit"]:
        session["pending"] = clarify.Pending(
            "run", "types", {"scene": parsed["scene"], "qps": parsed["qps"]}).to_dict()
        return {"reply": f"场景 {parsed['scene']} 记下了。跑什么？", "card": clarify.ask_types()}

    return {"reply": "计划如下，确认后开始。", "card": _confirm(parsed), "plan": _plan_of(parsed)}


def _from_slots(slots: dict) -> dict:
    t = slots.get("types", "both")
    return {"scene": slots.get("scene"), "qps": slots.get("qps") or DEFAULT_QPS,
            "load": t in ("load", "both"), "diff": t in ("diff", "both"),
            "types_explicit": True}


def _normalize(parsed: dict) -> dict:
    out = {"scene": parsed.get("scene"), "qps": parsed.get("qps") or DEFAULT_QPS,
           "load": True, "diff": True, "types_explicit": True}
    t = parsed.get("types")
    if t == "load":
        out["load"], out["diff"] = True, False
    elif t == "diff":
        out["load"], out["diff"] = False, True
    return out


def _plan_of(parsed: dict) -> dict:
    return {"scene": parsed.get("scene"), "qps": parsed.get("qps") or DEFAULT_QPS,
            "load": parsed.get("load", True), "diff": parsed.get("diff", True)}


def _scenes(conn) -> list[dict]:
    from context import graph_scene
    return [{"id": r["id"]} for r in repo._rows(conn.execute("SELECT id FROM scene ORDER BY id"))]


# ---------- 执行 ----------

def execute(conn, plan: dict) -> dict:
    scene = plan.get("scene")
    scenes = plan.get("scenes") or ([scene] if scene else [])
    qps = plan.get("qps") or DEFAULT_QPS
    load, do_diff = plan.get("load", True), plan.get("diff", True)

    parent = plan.get("retry_of")
    attempt = repo.new_attempt(conn, scenes[0], parent=parent)
    attempt_count = len(repo.attempts_of_scene(conn, scenes[0], 50))

    steps = [("check_recording", [])]
    if load:
        steps.append(("load_test", ["check_recording"]))
    if do_diff:
        steps.append(("diff", ["check_recording"]))
    steps.append(("judge", [s[0] for s in steps[1:]] or ["check_recording"]))

    p = Plan(scenes=scenes, qps_levels=qps, steps=steps)

    sim = plan.get("simulate_fail")
    simulated = {"sandbox": ("sandbox", "sandbox_unavailable", RuntimeError("沙箱启动失败")),
                 "timeout": ("run", "run_timeout", TimeoutError("执行超时 1800s")),
                 "report": ("report", "report_failed", IOError("报告落库失败")),
                 "judge": ("judge", "judge_error", RuntimeError("判读异常"))}

    try:
        if sim == "sandbox":
            raise simulated["sandbox"][2]
        with Tracer("run", conn) as t:
            with t.span("execute", scenes=len(scenes), qps=len(qps), attempt=attempt):
                state = Executor(R2Mock(), ForceBotMock(), DiffMock()).run(p)
            with t.span("judge"):
                v = judge(p, state)
        if sim == "timeout":
            raise simulated["timeout"][2]
        if sim == "judge":
            raise simulated["judge"][2]
    except Exception as e:
        stage, ftype, _ = simulated.get(sim, ("run", "run_error", None))
        repo.finish_attempt(conn, attempt, "aborted", note=str(e),
                            stage=stage, failure_type=ftype, detail=str(e))
        return {
            "reply": f"这一轮失败了：{tax.label(ftype)}。数据已保留。",
            "card": cards.verdict_card(
                f"执行失败 · {', '.join(scenes)}", "fail", [],
                f"{tax.label(ftype)}｜attempt={attempt}（第 {attempt_count} 轮，状态 aborted）。"
                f"处置建议：{tax.describe(ftype)}。失败轮次不计入历史趋势，可保留现场重跑。"),
            "attempt": attempt,
            "failure_type": ftype,
            "stage": stage,
            "actions_extra": ["重跑上一轮"],
        }

    if sim == "report":
        repo.finish_attempt(conn, attempt, "aborted", note="报告落库失败",
                            stage="report", failure_type="report_failed",
                            detail="模拟落库失败")
        return {"reply": "这一轮失败了：报告生成 · 报告落库失败。数据已保留。",
                "card": cards.verdict_card(f"执行失败 · {', '.join(scenes)}", "fail", [],
                                           f"{tax.label('report_failed')}｜attempt={attempt}。"
                                           f"处置建议：{tax.describe('report_failed')}。"),
                "attempt": attempt, "failure_type": "report_failed", "stage": "report"}

    # 成功：落一条 task + report，历史可见
    task_id = f"T-{attempt.split('-', 1)[1]}"
    diff_rate = max((d.get("diff_rate", 0) for d in state.get("diff", {}).values()), default=0.0)
    p99 = max((d["p99"] for by in state.get("load_test", {}).values() for d in by.values()), default=0.0)
    repo.insert_task_report(conn, task_id, scenes[0], _graph_of(conn, scenes[0]),
                            diff_rate, p99, round(p99 / 1.9, 1),
                            "pass" if v.passed else "fail")
    repo.finish_attempt(conn, attempt, "completed", task_id=task_id)

    metrics = []
    if do_diff:
        metrics.append({"name": "diff", "value": f"{diff_rate:.2%}", "ok": diff_rate <= p.diff_threshold})
    if load:
        metrics.append({"name": "p99", "value": f"{p99:.1f}ms", "ok": p99 <= p.p99_baseline * 1.1})

    return {"reply": f"跑完了，已记为 {task_id}。",
            "card": cards.verdict_card(f"执行结果 · {', '.join(scenes)}",
                                       "pass" if v.passed else "fail", metrics,
                                       "；".join(v.reasons) or "各项均在阈值内。"),
            "trace_id": t.trace_id, "attempt": attempt, "task_id": task_id}


def _graph_of(conn, scene_id: str) -> str:
    row = conn.execute("SELECT graph_id FROM scene_graph WHERE scene_id = ?", (scene_id,)).fetchone()
    return row[0] if row else ""
