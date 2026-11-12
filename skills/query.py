"""Skill：任务查询（只读，不触发任何东西）。"""

from __future__ import annotations

from context import assembler
from skills import cards


def run(conn, text: str) -> dict:
    task_id = assembler.resolve_task_id(conn, text)
    if not task_id:
        return {"reply": "请给我一个任务 id，比如「任务 T-004 怎么样」。", "card": None}

    ctx = assembler.build_context(conn, task_id)
    if not ctx:
        return {"reply": f"没找到任务 {task_id}。", "card": None}

    rep = ctx["report"] or {}
    did = assembler.did_for_task(conn, task_id)
    comp = ctx["comparability"]

    metrics = [
        {"name": "diff", "value": f"{(rep.get('diff_rate') or 0):.2%}",
         "ok": (rep.get("diff_rate") or 0) < 0.01},
        {"name": "p99", "value": f"{rep.get('p99')}ms", "ok": True},
    ]
    if did.get("ok"):
        metrics.append({"name": "净影响(DiD)", "value": f"{did['net']:+.2f}ms",
                        "ok": did["net"] <= 0.5})

    note = f"同期对照图 {did.get('control_delta')}ms" if did.get("ok") else did.get("reason", "")
    if not comp["ok"]:
        note += "；" + "；".join(comp["issues"])

    status = "pass" if all(m["ok"] for m in metrics) else "fail"
    body = cards.verdict_card(f"任务 {task_id}", status, metrics, note,
                              ["历史 5 次", "trace", "同图其他场景"])

    if ctx["graph"]["shared"]:
        body["note"] += f"（共享图，另影响 {', '.join(ctx['graph']['sibling_scenes'])}）"

    return {"reply": f"{task_id} 的结果如下。", "card": body, "trace_id": None}
