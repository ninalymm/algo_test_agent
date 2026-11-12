"""意图路由：规则优先，未命中才追问（D1：能用规则就不用模型）。

四类意图：
    自测   —— 我改完了 <commit>
    执行   —— 帮我跑一下 <场景> 的压测 / diff
    场景   —— <场景> 最近 N 次怎么样
    诊断   —— 任务 T-xxx 有什么问题
"""

from __future__ import annotations

import re

from skills import clarify, diagnose, run, run_graph, scene_report, selftest
from store import repo

SCENE_RE = re.compile(r"\d{8}-\d{4}")
TASK_RE = re.compile(r"T-\d{3,}", re.I)

HELP = ("我可以做四件事：\n"
        "① 场景对比：场景 20260301-0001 最近 5 次怎么样\n"
        "② 任务诊断：任务 T-005 有什么问题\n"
        "③ 跑任务：帮我跑一下 20260301-0001 的压测，1200 档\n"
        "④ 自测：我改完了 abc123f")


def _strong_intent(text: str) -> str | None:
    """明确表达了另一个意图（不是在对上一轮作答）。"""
    if re.search(r"(改完了|自测|帮我验)", text):
        return "selftest"
    if TASK_RE.search(text) or re.search(r"(诊断|什么问题|什么情况)", text):
        return "diagnose"
    if SCENE_RE.search(text) and re.search(r"(最近|趋势|对比|分析|怎么样|报告)", text):
        return "scene"
    return None


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

    if re.search(r"(诊断|什么问题|什么情况|分析一下)", t):
        return "diagnose"

    if scene:
        return "scene"

    if re.search(r"(场景|趋势|最近|对比|报告)", t):
        return "scene"

    return "unknown"


def _continue_diagnose(conn, text: str, session: dict) -> dict:
    known = [t["id"] for t in repo.list_tasks(conn, 20)]
    task_id = clarify.match_task(text, known) or clarify.resolve_choice(text, known[:5])
    if not task_id:
        return {"reply": "没认出任务 id。", "card": clarify.ask_task(known[:5])}
    session.pop("pending", None)
    return diagnose.run(conn, task_id)


def _continue_scene(conn, text: str, session: dict) -> dict:
    known = [s["id"] for s in repo._rows(conn.execute("SELECT id FROM scene ORDER BY id"))]
    scene = clarify.match_scene(text, known) or clarify.resolve_choice(text, known)
    if not scene:
        return {"reply": "没认出场景 id。", "card": clarify.ask_scene(known, "对比哪个场景？")}
    session.pop("pending", None)
    return scene_report.run(conn, scene)


def route(conn, text: str, session: dict | None = None,
          session_id: str | None = None) -> dict:
    session = session if session is not None else {}
    tid = session_id or "default"

    # LangGraph 版本可用时，run 链路交给图处理（状态在 checkpointer 里）
    if run_graph.available():
        waiting = run_graph.pending(conn, tid)
        strong = _strong_intent(text)

        # 用户改口：明确说了别的意图 → 放弃上一轮，走新意图
        if waiting and strong:
            run_graph.reset(conn, tid)
            waiting = False

        if waiting or (not session.get("pending") and detect(text) == "run"):
            r = run_graph.handle(conn, text, tid)
            r["intent"] = "run"
            return r

    # 有未完成的多轮提问 → 按 pending 的意图续跑
    if session.get("pending"):
        pending = session["pending"]
        intent = pending.get("intent", "run")

        if clarify.is_cancel(text):
            session.pop("pending", None)
            return {"reply": "已取消。", "card": None, "intent": intent}

        if intent == "run":
            r = run.run(conn, text, session)
        elif intent == "diagnose":
            r = _continue_diagnose(conn, text, session)
        else:
            r = _continue_scene(conn, text, session)

        r["intent"] = intent
        return r

    intent = detect(text)

    if intent == "selftest":
        m = re.search(r"([A-Za-z0-9\-]{4,})", text.replace("我改完了", ""))
        r = selftest.run(conn, text, m.group(1) if m else None)

    elif intent == "run":
        r = run.run(conn, text, session)

    elif intent == "scene":
        m = SCENE_RE.search(text)
        if not m:
            known = [s["id"] for s in repo._rows(conn.execute("SELECT id FROM scene ORDER BY id"))]
            session["pending"] = clarify.Pending("scene", "scene", {}).to_dict()
            r = {"reply": "对比哪个场景？", "card": clarify.ask_scene(known, "对比哪个场景？")}
        else:
            n_match = re.search(r"(\d+)\s*次", text)
            r = scene_report.run(conn, m.group(0), int(n_match.group(1)) if n_match else 5)

    elif intent == "diagnose":
        m = TASK_RE.search(text)
        if not m:
            known = [t["id"] for t in repo.list_tasks(conn, 5)]
            session["pending"] = clarify.Pending("diagnose", "task", {}).to_dict()
            r = {"reply": "诊断哪个任务？", "card": clarify.ask_task(known)}
        else:
            r = diagnose.run(conn, m.group(0).upper())

    else:
        r = {"reply": HELP, "card": None}

    r["intent"] = intent
    return r
