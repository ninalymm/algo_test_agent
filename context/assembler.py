"""上下文聚合器：把 任务 / 变更 / 场景 / 图 / 历史 / 对照 拼成一个上下文。

这是三个 Skill 的公共入口 —— Skill 不允许直接查库。
"""

from __future__ import annotations

from context import graph_scene, timeline
from store import repo

# 用于 DiD 的对照场景（生产上应由「同期未改动的相似场景」自动选取）
DEFAULT_CONTROL_SCENE = "20260303-0001"


def build_context(conn, task_id: str) -> dict | None:
    task = repo.get_task(conn, task_id)
    if not task:
        return None

    scene_id = task["scene_id"]
    graph_id = task["graph_id"]
    change = repo.get_change(conn, task["change_id"]) if task["change_id"] else None
    snapshot = repo.get_snapshot(conn, task_id)
    report = repo.get_report(conn, task_id)

    # 同场景历史（不含本次）
    hist = [r for r in timeline.history(conn, scene_id, 12) if r["id"] != task_id]

    # 该图下的兄弟场景（共享图时才有）
    siblings = [s for s in graph_scene.scenes_of(conn, graph_id) if s["id"] != scene_id]

    return {
        "task": task,
        "report": report,
        "scene": {"id": scene_id},
        "graph": {"id": graph_id, "shared": graph_scene.is_shared(conn, graph_id),
                  "sibling_scenes": [s["id"] for s in siblings]},
        "change": change,
        "snapshot": snapshot,
        "history": hist,
        "history_summary": timeline.summary(hist),
        "comparability": comparability(conn, task, snapshot, hist),
    }


def comparability(conn, task: dict, snapshot: dict | None, hist: list[dict]) -> dict:
    """判断「和上次比」这件事在本场景是否成立。"""
    issues = []
    if not snapshot:
        issues.append("缺少场景快照，无法确认环境是否一致")
    if len(hist) < 2:
        issues.append(f"历史样本仅 {len(hist)} 条，分布对比不可靠")
    return {"ok": not issues, "issues": issues}


def did_for_task(conn, task_id: str) -> dict:
    """为某个任务算 DiD：任务所在场景 vs 对照场景，按变更时间切前后。"""
    task = repo.get_task(conn, task_id)
    if not task or not task["change_id"]:
        return {"ok": False, "reason": "该任务未关联变更，无法做 DiD"}

    change = repo.get_change(conn, task["change_id"])
    ts = change["ts"]

    t_rows = timeline.history(conn, task["scene_id"], 20)
    c_rows = timeline.history(conn, DEFAULT_CONTROL_SCENE, 20)

    t_before, t_after = timeline.split_by_change(t_rows, ts)
    c_before, c_after = timeline.split_by_change(c_rows, ts)

    def vals(rows):
        return [r["p99"] for r in rows if r.get("p99") is not None]

    res = timeline.did(vals(t_before), vals(t_after), vals(c_before), vals(c_after))
    res["control_scene"] = DEFAULT_CONTROL_SCENE
    return res


def resolve_task_id(conn, text: str) -> str | None:
    """从「任务 T-004 怎么样」里认出任务 id。"""
    import re
    m = re.search(r"T-\d{3,}", text.upper())
    if m:
        return m.group(0)
    return None
