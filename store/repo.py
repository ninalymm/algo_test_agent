"""仓储层：所有 SQL 只在这里出现。"""

from __future__ import annotations

import json
from typing import Any

from store.db import connect


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- scene / graph ----------

def scenes_of_graph(conn, graph_id: str) -> list[dict]:
    return _rows(conn.execute(
        "SELECT s.* FROM scene s JOIN scene_graph sg ON s.id = sg.scene_id "
        "WHERE sg.graph_id = ? ORDER BY s.id", (graph_id,)))


def graph_of_scene(conn, scene_id: str) -> dict | None:
    rows = _rows(conn.execute(
        "SELECT g.* FROM graph g JOIN scene_graph sg ON g.id = sg.graph_id "
        "WHERE sg.scene_id = ?", (scene_id,)))
    return rows[0] if rows else None


def is_shared_graph(conn, graph_id: str) -> bool:
    n = conn.execute("SELECT COUNT(*) FROM scene_graph WHERE graph_id = ?",
                     (graph_id,)).fetchone()[0]
    return n > 1


# ---------- task ----------

def get_task(conn, task_id: str) -> dict | None:
    rows = _rows(conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)))
    return rows[0] if rows else None


def tasks_of_scene(conn, scene_id: str, limit: int = 20) -> list[dict]:
    return _rows(conn.execute(
        "SELECT * FROM task WHERE scene_id = ? ORDER BY ts DESC LIMIT ?",
        (scene_id, limit)))


def tasks_of_graph(conn, graph_id: str, limit: int = 20) -> list[dict]:
    return _rows(conn.execute(
        "SELECT * FROM task WHERE graph_id = ? ORDER BY ts DESC LIMIT ?",
        (graph_id, limit)))


def list_tasks(conn, limit: int = 20) -> list[dict]:
    return _rows(conn.execute("SELECT * FROM task ORDER BY ts DESC LIMIT ?", (limit,)))


# ---------- change ----------

def get_change(conn, change_id: str) -> dict | None:
    rows = _rows(conn.execute("SELECT * FROM change WHERE id = ?", (change_id,)))
    if not rows:
        return None
    c = rows[0]
    c["graph_ids"] = json.loads(c["graph_ids"] or "[]")
    return c


def change_of_graph(conn, graph_id: str) -> list[dict]:
    rows = _rows(conn.execute("SELECT * FROM change ORDER BY ts DESC"))
    out = []
    for c in rows:
        if graph_id in json.loads(c["graph_ids"] or "[]"):
            c["graph_ids"] = json.loads(c["graph_ids"])
            out.append(c)
    return out


# ---------- snapshot / report ----------

def get_snapshot(conn, task_id: str) -> dict | None:
    rows = _rows(conn.execute("SELECT * FROM snapshot WHERE task_id = ?", (task_id,)))
    return rows[0] if rows else None


def get_report(conn, task_id: str) -> dict | None:
    rows = _rows(conn.execute("SELECT * FROM report WHERE task_id = ?", (task_id,)))
    if not rows:
        return None
    r = rows[0]
    r["reasons"] = json.loads(r["reasons"] or "[]")
    return r


def reports_with_task(conn, scene_id: str, limit: int = 10) -> list[dict]:
    rows = _rows(conn.execute(
        "SELECT t.*, r.diff_rate, r.p99, r.avg, r.verdict "
        "FROM task t LEFT JOIN report r ON r.task_id = t.id "
        "WHERE t.scene_id = ? ORDER BY t.ts DESC LIMIT ?", (scene_id, limit)))
    return rows


# ---------- span ----------

def add_span(conn, trace_id: str, task_id: str | None, name: str,
             start_ms: int, end_ms: int, status: str, attrs: dict) -> None:
    conn.execute(
        "INSERT INTO span(trace_id, task_id, name, start_ms, end_ms, status, attrs) "
        "VALUES (?,?,?,?,?,?,?)",
        (trace_id, task_id, name, start_ms, end_ms, status, json.dumps(attrs, ensure_ascii=False)))


def spans_of_trace(conn, trace_id: str) -> list[dict]:
    return _rows(conn.execute(
        "SELECT * FROM span WHERE trace_id = ? ORDER BY start_ms", (trace_id,)))
