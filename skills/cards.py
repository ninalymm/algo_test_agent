"""统一的返回卡片结构 —— 前后端共用。"""

from __future__ import annotations


def verdict_card(title: str, status: str, metrics: list[dict], note: str = "",
                 actions: list[str] | None = None) -> dict:
    return {"type": "verdict", "title": title, "status": status,
            "metrics": metrics, "note": note, "actions": actions or []}


def confirm_card(title: str, lines: list[str], actions: list[str] | None = None) -> dict:
    return {"type": "confirm", "title": title, "lines": lines,
            "actions": actions or ["确认执行", "取消"]}


def blocked_card(title: str, reasons: list[str]) -> dict:
    return {"type": "blocked", "title": title, "reasons": reasons,
            "actions": ["修改参数"]}


def trend_card(title: str, rows: list[dict], note: str) -> dict:
    return {"type": "trend", "title": title, "rows": rows, "note": note}
