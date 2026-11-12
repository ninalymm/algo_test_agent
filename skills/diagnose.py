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

    # ④ 本次改动
    change = ctx.get("change")
    change_block = None
    if change:
        scenes = _affected_scenes(conn, change)
        change_block = {
            "id": change["id"],
            "commit": change["commit_id"],
            "mr": change.get("mr"),
            "author": change.get("author"),
            "ts": change.get("ts"),
            "title": change.get("title") or "（未填写改动说明）",
            "files": change.get("files") or [],
            "graphs": change.get("graph_ids") or [],
            "scenes": scenes,
        }
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

    # ⑤ 近 N 次趋势摘要（一行）
    series = timeline.series(conn, ctx["scene"]["id"], 5)
    trend = None
    if len(series) >= 3:
        p99s = [x["p99"] for x in series]
        diffs = [x["diff"] for x in series]
        trend = {
            "n": len(series),
            "p99": f"{p99s[0]:.1f} → {p99s[-1]:.1f}ms（{timeline.trend_label(p99s)}）",
            "diff": f"{diffs[0]:.2%} → {diffs[-1]:.2%}（{timeline.trend_label(diffs)}）",
        }
    summary = repo.attempt_summary(conn, ctx["scene"]["id"])
    from agent import failure_taxonomy as tax
    failures = {
        "total": summary["aborted"],
        "items": [{"label": tax.label(t), "count": c}
                  for t, c in sorted(summary["by_type"].items(), key=lambda x: -x[1])],
    }

    card = cards.verdict_card(f"任务 {task_id} 诊断", status, metrics, note,
                              ["展开趋势", "trace"])
    card["change"] = change_block
    card["trend"] = trend
    card["failures"] = failures
    card["jobs"] = repo.job_summary(conn, ctx["scene"]["id"])
    return {"reply": f"{task_id} 的诊断结果：", "card": card}


def _affected_scenes(conn, change: dict) -> list[str]:
    """图 → 场景展开（1:N）。"""
    out = []
    for gid in change.get("graph_ids") or []:
        out.extend(s["id"] for s in repo.scenes_of_graph(conn, gid))
    return out
