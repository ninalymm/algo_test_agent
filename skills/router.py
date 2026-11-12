"""意图路由：规则优先，未命中才交给 LLM（当前降级为追问）。"""

from __future__ import annotations

import re

from skills import query, selftest, trend

RULES = [
    (re.compile(r"(趋势|环比|最近|一直在)"), "trend"),
    (re.compile(r"(改完了|帮我验|自测|跑一下|启动任务)"), "selftest"),
    (re.compile(r"T-\d{3,}"), "query"),
]


def route(conn, text: str) -> dict:
    intent = None
    for pattern, name in RULES:
        if pattern.search(text):
            intent = name
            break

    if intent is None:
        return {"reply": "我可以做三件事：查任务（如「任务 T-004」）、做自测（如「我改完了 abc123」）、看趋势（如「场景 20260301-0001 最近怎么样」）。",
                "card": None, "intent": "unknown"}

    if intent == "query":
        r = query.run(conn, text)
    elif intent == "selftest":
        m = re.search(r"([A-Za-z0-9\-]{4,})", text.replace("我改完了", ""))
        r = selftest.run(conn, text, m.group(1) if m else None)
    else:
        m = re.search(r"\d{8}-\d{4}", text)
        scene = m.group(0) if m else "20260301-0001"
        r = trend.run(conn, scene)

    r["intent"] = intent
    return r
