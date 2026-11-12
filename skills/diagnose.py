"""Skill：单次任务诊断 —— 这次任务的问题在哪。"""

from __future__ import annotations

from context import assembler, timeline
from skills import cards
from store import repo

DIFF_THRESHOLD = 0.01


def run(conn, task_id: str) -> dict:
    ctx = assembler.build_context(conn, task_id)
    if not ctx:
        return {"reply": f"没找到任务 {task_id}。", "card": None}

    rep = ctx["report"] or {}
    hist = [r for r in ctx["history"] if r.get("p99") is not None]
    p99s = [r["p99"] for r in hist]
    base = timeline.quantile(p99s, 0.5) if p99s else None

    metrics, problems = [], []

    # ① diff
    diff = rep.get("diff_rate") or 0
    diff_ok = diff <= DIFF_THRESHOLD
    metrics.append({"name": "diff", "value": f"{diff:.2%}", "ok": diff_ok})
    if not diff_ok:
        problems.append(f"diff {diff:.2%} 超过阈值 {DIFF_THRESHOLD:.0%}")
    elif diff > DIFF_THRESHOLD * 0.8:
        problems.append(f"diff {diff:.2%} 已接近阈值，处于警戒区")

    # ② p99 相对历史
    p99 = rep.get("p99")
    if p99 and base:
        delta = (p99 - base) / base
        z = timeline.robust_z(p99s, p99)
        metrics.append({"name": "p99", "value": f"{p99:.1f}ms（基线 {base:.1f}ms）", "ok": delta <= 0.10})
        if delta > 0.10:
            problems.append(f"p99 较历史中位数高 {delta:.0%}（稳健 z={z:.1f}）")

    # ③ 录制 / 环境
    snap = ctx.get("snapshot") or {}
    if not snap:
        problems.append("缺少场景快照，本次结果与环境的关系不可确认")

    # ④ 变更关联
    change = ctx.get("change")
    if change:
        metrics.append({"name": "关联变更", "value": f"{change['id']}（{change['commit_id']}）", "ok": True})
    else:
        problems.append("本次任务未关联代码变更，无法做前后归因")

    # ⑤ 可比性
    comp = ctx["comparability"]
    if not comp["ok"]:
        problems.extend(comp["issues"])

    did = assembler.did_for_task(conn, task_id)
    if did.get("ok"):
        metrics.append({"name": "净影响(DiD)", "value": f"{did['net']:+.2f}ms", "ok": did["net"] <= 0.5})

    status = "fail" if any(m["name"] == "diff" and not m["ok"] for m in metrics) else (
        "warn" if problems else "pass")

    note = "；".join(problems) if problems else "未发现异常。"
    if did.get("ok"):
        note += f" DiD：目标 {did['target_delta']:+.2f} / 对照 {did['control_delta']:+.2f} → 净 {did['net']:+.2f}ms。"

    card = cards.verdict_card(f"任务 {task_id} 诊断", status, metrics, note,
                              ["历史 5 次", "场景对比"])
    return {"reply": f"{task_id} 的诊断结果：", "card": card}
