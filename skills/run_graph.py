"""用 LangGraph 重写「自然语言驱动执行」这一条链路。

对比手写版本（skills/run.py）：
    手写：SESSIONS 字典 + Pending 结构 + 自己判「是不是在回答」
    图版：checkpointer 存状态 + interrupt 停在确认卡 + 条件边决定下一步

设计原则不变（D1）：意图与槽位仍用规则抽取，模型不参与决策。
"""

from __future__ import annotations

import re
from typing import TypedDict

from skills import clarify, run
from store import repo

DEFAULT_QPS = [1200, 1600]
DB_PATH = "data/graph.db"


def available() -> bool:
    try:
        import langgraph  # noqa: F401
        return True
    except ImportError:
        return False


class RunState(TypedDict, total=False):
    text: str
    scene: str | None
    types: str | None          # perf / diff / both
    qps: list[int]
    awaiting: str | None       # scene / types / confirm / None
    plan: dict
    approved: bool
    reply: str
    card: dict | None
    job: str
    trace_id: str


# ---------- 构图 ----------

def build(conn):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import interrupt

    known_scenes = [r["id"] for r in repo._rows(
        conn.execute("SELECT id FROM scene ORDER BY id"))]

    def parse_node(s: RunState) -> RunState:
        text = s.get("text") or ""
        scene = clarify.match_scene(text, known_scenes) or s.get("scene")
        types = clarify.match_types(text) or s.get("types")
        qps = [int(x) for x in re.findall(r"(\d{3,4})\s*(?:qps|档)", text)] or s.get("qps") or DEFAULT_QPS
        return {"scene": scene, "types": types, "qps": qps, "awaiting": None}

    def ask_scene_node(s: RunState) -> RunState:
        return {"reply": "还差一个信息：跑哪个场景？",
                "card": clarify.ask_scene(known_scenes), "awaiting": "scene"}

    def ask_types_node(s: RunState) -> RunState:
        return {"reply": f"场景 {s['scene']} 记下了。跑什么？",
                "card": clarify.ask_types(), "awaiting": "types"}

    def confirm_node(s: RunState) -> RunState:
        card = run._confirm(_to_parsed(s))
        answer = interrupt({"card": card})
        return {"approved": answer in ("确认执行", "确认", "yes", "ok"),
                "awaiting": None}

    def execute_node(s: RunState) -> RunState:
        if not s.get("approved"):
            return {"reply": "已取消。", "card": None}
        result = run.execute(conn, run._plan_of(_to_parsed(s)))
        return {"reply": result["reply"], "card": result["card"],
                "job": result.get("job"), "trace_id": result.get("trace_id")}

    def next_step(s: RunState) -> str:
        if not s.get("scene"):
            return "ask_scene"
        if not s.get("types"):
            return "ask_types"
        return "confirm"

    g = StateGraph(RunState)
    g.add_node("parse", parse_node)
    g.add_node("ask_scene", ask_scene_node)
    g.add_node("ask_types", ask_types_node)
    g.add_node("confirm", confirm_node)
    g.add_node("execute", execute_node)

    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", next_step,
                            {"ask_scene": "ask_scene", "ask_types": "ask_types",
                             "confirm": "confirm"})
    g.add_edge("ask_scene", END)
    g.add_edge("ask_types", END)
    g.add_conditional_edges("confirm", lambda s: "execute" if s.get("approved") else END,
                            {"execute": "execute", END: END})
    g.add_edge("execute", END)

    # from_conn_string 返回上下文管理器；这里直接持有连接，让 saver 长期可用
    import sqlite3
    ckpt_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    return g.compile(checkpointer=checkpointer)


def _to_parsed(s: RunState) -> dict:
    t = s.get("types") or "both"
    return {"scene": s.get("scene"), "qps": s.get("qps") or DEFAULT_QPS,
            "perf": t in ("perf", "both"), "diff": t in ("diff", "both"),
            "types_explicit": True}


# ---------- 对外入口 ----------

_GRAPH = None


def _graph(conn):
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build(conn)
    return _GRAPH


def reset(conn, thread_id: str) -> None:
    _graph(conn).update_state(
        {"configurable": {"thread_id": thread_id}},
        {"scene": None, "types": None, "text": None, "approved": False,
         "awaiting": None, "card": None, "reply": ""})


def pending(conn, thread_id: str) -> bool:
    """这个会话是否还有未完成的一轮（在提问 / 等确认）。"""
    if not available():
        return False
    st = _graph(conn).get_state({"configurable": {"thread_id": thread_id}})
    if st.interrupts:
        return True
    return bool((st.values or {}).get("awaiting"))


def handle(conn, text: str, thread_id: str = "default") -> dict:
    """一轮对话：可能在提问、可能在等确认、也可能直接执行完。"""
    g = _graph(conn)
    cfg = {"configurable": {"thread_id": thread_id}}

    if clarify.is_cancel(text):
        state = g.get_state(cfg)
        if state.interrupts:
            out = g.invoke(_resume("取消"), cfg)
            return _shape(out)
        reset(conn, thread_id)
        return {"reply": "已取消。", "card": None}

    state = g.get_state(cfg)
    if state.interrupts:                       # 正停在确认卡
        out = g.invoke(_resume(text), cfg)
    else:
        out = g.invoke({"text": text}, cfg)

    result = _shape(out)
    # 执行完或取消后清空槽位，避免下一轮复用
    if result.get("card") is None or (result.get("card") or {}).get("type") == "verdict":
        reset(conn, thread_id)
    return result


def _resume(value: str):
    from langgraph.types import Command
    return Command(resume=value)


def _shape(out: dict) -> dict:
    # 图被 interrupt 挂起时，真正的卡片在 __interrupt__ 里
    interrupts = out.get("__interrupt__") or []
    if interrupts:
        payload = getattr(interrupts[0], "value", None) or {}
        return {"reply": "计划如下，确认后开始。", "card": payload.get("card"),
                "job": None, "trace_id": None, "interrupted": True}
    return {"reply": out.get("reply", ""), "card": out.get("card"),
            "job": out.get("job"), "trace_id": out.get("trace_id")}
