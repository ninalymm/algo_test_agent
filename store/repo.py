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
    c["files"] = [f for f in (c.get("files") or "").split(",") if f]
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


# ---------- attempt（执行轮次） ----------

def next_round(conn, scene_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(round), 0) FROM attempt WHERE scene_id = ?",
                       (scene_id,)).fetchone()
    return int(row[0]) + 1


def new_attempt(conn, scene_id: str, parent: str | None = None) -> str:
    import datetime
    aid = f"A-{datetime.datetime.now().strftime('%m%d%H%M%S')}-{next_round(conn, scene_id)}"
    conn.execute(
        "INSERT INTO attempt(id, scene_id, task_id, round, status, parent_attempt, created_at, note) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (aid, scene_id, None, next_round(conn, scene_id), "running", parent,
         datetime.datetime.now().isoformat(timespec="seconds"), ""))
    conn.commit()
    return aid


def finish_attempt(conn, attempt_id: str, status: str, task_id: str | None = None,
                   note: str = "") -> None:
    conn.execute("UPDATE attempt SET status = ?, task_id = COALESCE(?, task_id), note = ? WHERE id = ?",
                 (status, task_id, note, attempt_id))
    conn.commit()


def attempts_of_scene(conn, scene_id: str, limit: int = 20) -> list[dict]:
    return _rows(conn.execute(
        "SELECT * FROM attempt WHERE scene_id = ? ORDER BY created_at DESC LIMIT ?",
        (scene_id, limit)))


def attempt_summary(conn, scene_id: str) -> dict:
    rows = attempts_of_scene(conn, scene_id, 100)
    aborted = [r for r in rows if r["status"] in ("failed", "timeout", "aborted")]
    return {"total": len(rows), "aborted": len(aborted),
            "last": rows[0]["id"] if rows else None}


def insert_task_report(conn, task_id: str, scene_id: str, graph_id: str,
                       diff_rate: float, p99: float, avg: float,
                       verdict: str, ts: str | None = None) -> None:
    import datetime
    ts = ts or datetime.datetime.now().isoformat(timespec="minutes")
    conn.execute("INSERT OR REPLACE INTO task(id, scene_id, graph_id, change_id, trigger, status, ts) "
                 "VALUES (?,?,?,?,?,?,?)", (task_id, scene_id, graph_id, None, "agent", "done", ts))
    conn.execute("INSERT OR REPLACE INTO report(task_id, diff_rate, p99, avg, verdict, reasons) "
                 "VALUES (?,?,?,?,?,?)", (task_id, diff_rate, p99, avg, verdict, "[]"))
    conn.commit()
