"""Skill：趋势分析 —— 分布对比 + DiD，结论必须指向动作。"""

from __future__ import annotations

from context import assembler, timeline
from skills import cards
from store import repo


def run(conn, scene_id: str) -> dict:
    rows = timeline.history(conn, scene_id, 20)
    if len(rows) < 3:
        return {"reply": f"场景 {scene_id} 历史样本不足（{len(rows)} 条），无法做趋势。", "card": None}

    # 按最新一次带变更的任务切前后
    changed = [r for r in rows if r.get("change_id")]
    change_id = changed[0]["change_id"] if changed else None
    change_ts = repo.get_change(conn, change_id)["ts"] if change_id else None

    before, after = (timeline.split_by_change(rows, change_ts) if change_ts
                     else (rows[len(rows)//2:], rows[:len(rows)//2]))

    def vals(rs):
        return [r["p99"] for r in rs if r.get("p99") is not None]

    c_rows = timeline.history(conn, assembler.DEFAULT_CONTROL_SCENE, 20)
    c_before, c_after = (timeline.split_by_change(c_rows, change_ts) if change_ts
                         else (c_rows[len(c_rows)//2:], c_rows[:len(c_rows)//2]))

    did = timeline.did(vals(before), vals(after), vals(c_before), vals(c_after))

    table = [
        {"stage": "变更前", "n": len(before), "median": timeline.summary(before).get("median")},
        {"stage": "变更后", "n": len(after), "median": timeline.summary(after).get("median")},
        {"stage": "对照(前→后)", "n": len(c_rows),
         "median": f"{timeline.summary(c_before).get('median')} → {timeline.summary(c_after).get('median')}"},
    ]

    if did.get("ok"):
        note = (f"目标 {did['target_delta']:+.2f}ms，对照 {did['control_delta']:+.2f}ms，"
                f"净影响 {did['net']:+.2f}ms → {did['verdict']}。")
        if did["net"] > 0.5:
            note += " 动作建议：先查该图最近一次改动的算子/参数，再决定是否回滚。"
        elif did["net"] < -0.5:
            note += " 动作建议：记录为有效优化，可推广到同图其他场景。"
        else:
            note += " 动作建议：无需动作，继续观察。"
    else:
        note = did.get("reason", "")

    return {"reply": f"场景 {scene_id} 的趋势分析如下。",
            "card": cards.trend_card(f"趋势 · {scene_id}", table, note)}
