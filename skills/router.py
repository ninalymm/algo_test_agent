"""意图路由：规则优先，未命中才追问（D1：能用规则就不用模型）。

四类意图：
    自测   —— 我改完了 <commit>
    执行   —— 帮我跑一下 <场景> 的压测 / diff
    场景   —— <场景> 最近 N 次怎么样
    诊断   —— 任务 T-xxx 有什么问题
"""

from __future__ import annotations

import re

from skills import diagnose, run, scene_report, selftest

SCENE_RE = re.compile(r"\d{8}-\d{4}")
TASK_RE = re.compile(r"T-\d{3,}", re.I)

HELP = ("我可以做四件事：\n"
        "① 场景对比：场景 20260301-0001 最近 5 次怎么样\n"
        "② 任务诊断：任务 T-005 有什么问题\n"
        "③ 跑任务：帮我跑一下 20260301-0001 的压测，1200 档\n"
        "④ 自测：我改完了 abc123f")


def detect(text: str) -> str:
    t = text.strip()
    scene = SCENE_RE.search(t)

    if re.search(r"(改完了|自测|帮我验)", t):
        return "selftest"

    if re.search(r"(跑|执行|压一下|加压|启动|跑个|来一轮)", t):
        return "run"

    if scene and re.search(r"(最近|趋势|对比|分析|怎么样|报告)", t):
        return "scene"

    if TASK_RE.search(t):
        return "diagnose"

    if scene:
        return "scene"
    return "unknown"


def route(conn, text: str) -> dict:
    intent = detect(text)

    if intent == "selftest":
        m = re.search(r"([A-Za-z0-9\-]{4,})", text.replace("我改完了", ""))
        r = selftest.run(conn, text, m.group(1) if m else None)

    elif intent == "run":
        r = run.run(conn, text)

    elif intent == "scene":
        scene = SCENE_RE.search(text).group(0)
        n_match = re.search(r"(\d+)\s*次", text)
        r = scene_report.run(conn, scene, int(n_match.group(1)) if n_match else 5)

    elif intent == "diagnose":
        task_id = TASK_RE.search(text).group(0).upper()
        r = diagnose.run(conn, task_id)

    else:
        r = {"reply": HELP, "card": None}

    r["intent"] = intent
    return r
