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
from observe.tracing import traceable
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

    perf = types in ("perf", "both")
    diff = types in ("diff", "both")
    if types is None:
        perf = diff = True

    return {"scene": scene, "qps": sorted(set(qps)), "perf": perf, "diff": diff,
            "types_explicit": types is not None}


def _confirm(parsed: dict) -> dict:
    kinds = []
    if parsed["perf"]:
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
                t = {"压测": "perf", "diff": "diff", "两个都跑": "both"}.get(choice or "")
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
            "perf": t in ("perf", "both"), "diff": t in ("diff", "both"),
            "types_explicit": True}


def _normalize(parsed: dict) -> dict:
    out = {"scene": parsed.get("scene"), "qps": parsed.get("qps") or DEFAULT_QPS,
           "perf": True, "diff": True, "types_explicit": True}
    t = parsed.get("types")
    if t == "perf":
        out["perf"], out["diff"] = True, False
    elif t == "diff":
        out["perf"], out["diff"] = False, True
    return out


def _plan_of(parsed: dict) -> dict:
    return {"scene": parsed.get("scene"), "qps": parsed.get("qps") or DEFAULT_QPS,
            "perf": parsed.get("perf", True), "diff": parsed.get("diff", True)}


def _scenes(conn) -> list[dict]:
    from context import graph_scene
    return [{"id": r["id"]} for r in repo._rows(conn.execute("SELECT id FROM scene ORDER BY id"))]


# ---------- 执行 ----------

@traceable
def execute(conn, plan: dict) -> dict:
    """一次执行请求 = 一个 job，内含 diff / 压测两个独立分支。

    分支互不影响：diff 挂了，压测照样出结果（job 状态为 partial）。
    """
    scene = plan.get("scene")
    scenes = plan.get("scenes") or ([scene] if scene else [])
    scene = scenes[0]
    qps = plan.get("qps") or DEFAULT_QPS
    perf, do_diff = plan.get("perf", True), plan.get("diff", True)
    sim = plan.get("simulate_fail")
    parent = plan.get("retry_of")

    job = repo.new_job(conn, scene)
    branches: dict[str, dict] = {}

    with Tracer("run", conn) as t:
        if perf:
            branches["perf"] = _branch(conn, t, job, scene, "perf", sim, parent,
                                       lambda: _run_perf(scene, qps))
        if do_diff:
            branches["diff"] = _branch(conn, t, job, scene, "diff", sim, parent,
                                       lambda: _run_diff(scene))

        aa_emr = plan.get("aa_emr")
        validity = repo.validity_from_aa(aa_emr)
        status = repo.job_status_from_branches({k: v["ok"] for k, v in branches.items()})
        note = "；".join(f"{k}:{v['label']}" for k, v in branches.items() if not v["ok"])
        repo.finish_job(conn, job, status, validity, note)

    # 有产出才写历史
    task_id = None
    if status in ("completed", "partial"):
        task_id = f"T-{job.split('-', 1)[1]}"
        diff_rate = branches.get("diff", {}).get("diff_rate", 0.0)
        p99 = branches.get("perf", {}).get("p99", 0.0)
        repo.insert_task_report(conn, task_id, scene, _graph_of(conn, scene),
                                diff_rate, p99, round(p99 / 1.9, 1) if p99 else 0,
                                "pass" if status == "completed" else "partial")

    metrics = []
    if "diff" in branches:
        b = branches["diff"]
        metrics.append({"name": "diff", "value": f"{b['diff_rate']:.2%}" if b["ok"] else "未产出",
                        "ok": b["ok"]})
    if "perf" in branches:
        b = branches["perf"]
        metrics.append({"name": "p99", "value": f"{b['p99']:.1f}ms" if b["ok"] else "未产出",
                        "ok": b["ok"]})

    title = {"completed": "✅ 全部完成", "partial": "⚠️ 部分完成", "failed": "❌ 全部失败"}[status]
    note = _note_for(status, validity, branches, aa_emr)

    card = cards.verdict_card(f"执行结果 · {scene}", "pass" if status == "completed" else (
        "warn" if status == "partial" else "fail"), metrics, note)
    card["job"] = job
    card["job_status"] = status
    card["validity"] = validity
    card["branches"] = {k: {"ok": v["ok"], "label": v["label"]} for k, v in branches.items()}
    card["title"] = title + " · " + scene

    return {"reply": _reply(status, validity), "card": card, "job": job,
            "task_id": task_id, "trace_id": t.trace_id}


def _note_for(status: str, validity: str, branches: dict, aa_emr) -> str:
    parts = []
    for name, b in branches.items():
        parts.append(f"{name}：{'成功' if b['ok'] else b['label']}")
    note = "；".join(parts)
    if validity == "invalid":
        note += f"。⚠️ 结论无效：AA 观测一致率 {aa_emr:.0%} 低于阈值，A/B 差异不可信"
    elif validity == "unknown":
        note += "。结论有效性未知（未提供 AA 观测一致率）"
    return note


def _reply(status: str, validity: str) -> str:
    base = {"completed": "全部完成。", "partial": "部分完成。",
            "failed": "全部失败，本轮数据已保留。"}[status]
    if validity == "invalid":
        base += "但结论无效（AA 不一致）。"
    return base


def _branch(conn, tracer, job, scene, name, sim, parent, fn) -> dict:
    att = repo.new_attempt(conn, scene, parent=parent, job_id=job, branch=name)
    fail_sim = {"perf": "perf", "diff": "diff"}.get(sim)
    try:
        with tracer.span(f"branch_{name}", branch=name, attempt=att):
            if sim == "sandbox" or fail_sim == name:
                raise RuntimeError(f"{name} 分支执行失败（模拟）")
            data = fn()
        repo.finish_attempt(conn, att, "completed")
        data["ok"] = True
        data["label"] = "成功"
        data["attempt"] = att
        return data
    except Exception as e:
        ftype = "sandbox_unavailable" if sim == "sandbox" else "run_error"
        repo.finish_attempt(conn, att, "aborted", note=str(e),
                            stage=tax.stage_of(ftype), failure_type=ftype, detail=str(e))
        return {"ok": False, "label": tax.label(ftype), "attempt": att,
                "diff_rate": 0.0, "p99": 0.0}


def _run_perf(scene: str, qps: list[int]) -> dict:
    data = ForceBotMock().run({"scene": scene, "qps": max(qps)}).data
    return {"p99": data["p99"], "avg": data["avg"], "qps": data["qps"]}


def _run_diff(scene: str) -> dict:
    data = DiffMock().run({"scene": scene}).data
    return {"diff_rate": data["diff_rate"]}


def _graph_of(conn, scene_id: str) -> str:
    row = conn.execute("SELECT graph_id FROM scene_graph WHERE scene_id = ?", (scene_id,)).fetchone()
    return row[0] if row else ""
