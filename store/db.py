"""SQLite 连接与初始化。零外部依赖。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "agent.db"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


MIGRATIONS = {
    "change": [("title", "TEXT"), ("files", "TEXT")],
    "attempt": [("stage", "TEXT"), ("failure_type", "TEXT"), ("detail", "TEXT")],
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """给已有库补列（演示环境用，生产应上迁移工具）。"""
    for table, cols in MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def reset(conn: sqlite3.Connection) -> None:
    for t in ("span", "attempt", "report", "snapshot", "task", "change",
              "scene_graph", "graph", "scene", "app"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
