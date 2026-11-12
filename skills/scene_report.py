"""Skill：场景近 N 次报告分析（压测 + diff 双维度）。"""

from __future__ import annotations

from context import assembler, timeline
from observe.tracing import traceable
from skills import cards
from store import repo

DIFF_THRESHOLD = 0.01
P99_DRIFT = 0.20          # 单次 p99 偏离历史中位数超过 20% 视为异常


@traceable
def run(conn, scene_id: str, n: int = 5) -> dict:
    rows = timeline.series(conn, scene_id, n)
    if len(rows) < 3:
        return {"reply": f"场景 {scene_id} 近 {n} 次任务不足（{len(rows)} 条），无法对比。", "card": None}

    p99s = [r["p99"] for r in rows]
    diffs = [r["diff"] for r in rows]
    base_p99 = timeline.quantile(p99s[:-1], 0.5)

    table = []
    for r in rows:
        flags = []
        if r["diff"] is not None and r["diff"] > DIFF_THRESHOLD:
            flags.append("diff 超限")
        elif r["diff"] is not None and r["diff"] > DIFF_THRESHOLD * 0.8:
            flags.append("diff 接近阈值")
        if base_p99 and abs(r["p99"] - base_p99) / base_p99 > P99_DRIFT:
            flags.append("p99 偏离")
        table.append({"id": r["id"], "ts": (r["ts"] or "")[5:10],
                      "diff": f"{(r['diff'] or 0):.2%}",
                      "p99": f"{r['p99']:.1f}ms",
                      "flag": "、".join(flags) or "—"})

    p_trend = timeline.trend_label(p99s)
    d_trend = timeline.trend_label(diffs)
    latest = rows[-1]

    did = {"ok": False}
    change_id = repo.get_task(conn, latest["id"]).get("change_id")
    if change_id:
        did = assembler.did_for_task(conn, latest["id"])

    suggestions = _suggest(latest, p_trend, d_trend, did, base_p99)
    status = "fail" if (latest["diff"] or 0) > DIFF_THRESHOLD else (
        "warn" if suggestions else "pass")

    note = (f"p99 趋势：{p_trend}；diff 趋势：{d_trend}。")
    if did.get("ok"):
        note += f" 净影响(DiD) {did['net']:+.2f}ms（{did['verdict']}）。"
    note += " 建议：" + ("；".join(suggestions) if suggestions else "无需动作，继续观察。")

    card = cards.trend_card(f"场景 {scene_id} · 近 {len(rows)} 次", table, note)
    card["status"] = status
    card["columns"] = ["任务", "日期", "diff", "p99", "标记"]
    return {"reply": f"{scene_id} 近 {len(rows)} 次的双维度对比：", "card": card}


def _suggest(latest: dict, p_trend: str, d_trend: str, did: dict, base_p99: float) -> list[str]:
    out = []
    diff = latest.get("diff") or 0
    if diff > DIFF_THRESHOLD:
        out.append("diff 超阈值，优先查度量/口径是否对齐（先看分数是否可比）")
    elif diff > DIFF_THRESHOLD * 0.8:
        out.append("diff 已接近阈值，关注是否持续劣化")

    if base_p99 and (latest["p99"] - base_p99) / base_p99 > P99_DRIFT:
        out.append(f"p99 较历史中位数高 {(latest['p99']-base_p99)/base_p99:.0%}，怀疑容量或本次改动")

    if p_trend == "上升" and d_trend == "上升":
        out.append("两个维度同向变差，建议对照该图最近一次改动做归因")

    if did.get("ok") and did.get("net", 0) > 0.5:
        out.append("扣除大盘后仍是劣化，可考虑回滚或扩容")
    elif did.get("ok") and abs(did.get("net", 0)) <= 0.5:
        out.append("扣除大盘后无显著变化，暂不需要动作")

    return out
