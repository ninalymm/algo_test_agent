"""用 LangGraph 重写「自然语言驱动执行」这一条链路。

对比手写版本（skills/run.py）：
    手写：SESSIONS 字典 + Pending 结构 + 自己判「是不是在回答」
    图版：checkpointer 存状态 + interrupt 停在确认卡 + 条件边决定下一步

设计原则不变（D1）：意图与槽位仍用规则抽取，模型不参与决策。
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import TypedDict

from skills import clarify, run
from store import repo

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "graph.db"

_EMPTY_STATE = {"scene": None, "types": None, "types_explicit": False, "text": None,
                "approved": False, "awaiting": None, "card": None, "reply": ""}


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
    types_explicit: bool       # 用户是否明确说过类型（供确认卡提示用）
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
    """构图，返回 (graph, saver)；saver 的连接由调用方负责关闭。"""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import interrupt

    def known_scenes() -> list[str]:
        """每轮现查，新增场景不需要重启进程。"""
        return [r["id"] for r in repo._rows(
            conn.execute("SELECT id FROM scene ORDER BY id"))]

    def parse_node(s: RunState) -> RunState:
        text = s.get("text") or ""
        parsed = run.parse(text, known_scenes())
        types = parsed["types"]
        types_explicit = parsed["types_explicit"]
        if types is None and s.get("awaiting") == "types":
            types = clarify.match_types_or_choice(text)
            types_explicit = types is not None     # 用户是明确回答的
        return {
            "scene": parsed["scene"] or s.get("scene"),
            "types": types or s.get("types"),
            "types_explicit": types_explicit or bool(s.get("types_explicit")),
            "qps": parsed["qps"] if parsed["qps_explicit"] else (s.get("qps") or parsed["qps"]),
            "awaiting": None,
        }

    def ask_scene_node(s: RunState) -> RunState:
        return {"reply": "还差一个信息：跑哪个场景？",
                "card": clarify.ask_scene(known_scenes()), "awaiting": "scene"}

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

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    ckpt_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    saver = SqliteSaver(ckpt_conn)
    return g.compile(checkpointer=saver), saver


def _to_parsed(s: RunState) -> dict:
    t = s.get("types") or "both"
    return {"scene": s.get("scene"), "qps": s.get("qps") or run.DEFAULT_QPS,
            "perf": t in ("perf", "both"), "diff": t in ("diff", "both"),
            "types_explicit": bool(s.get("types_explicit"))}


# ---------- 对外入口 ----------

@contextlib.contextmanager
def _open(conn):
    """每次调用独立构图 + 独立 checkpoint 连接，用完即关。

    早期实现是模块级单例：图绑死第一次传入的 conn，checkpoint 连接也从不关闭。
    现在按调用构建，避免跨连接串味和连接泄漏（SQLite 句柄 + WAL 文件）。
    """
    graph, saver = build(conn)
    try:
        yield graph
    finally:
        with contextlib.suppress(Exception):
            saver.conn.close()


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _reset(g, thread_id: str) -> None:
    g.update_state(_cfg(thread_id), dict(_EMPTY_STATE))


def reset(conn, thread_id: str) -> None:
    with _open(conn) as g:
        _reset(g, thread_id)


def pending(conn, thread_id: str) -> bool:
    """这个会话是否还有未完成的一轮（在提问 / 等确认）。"""
    if not available():
        return False
    with _open(conn) as g:
        snap = g.get_state(_cfg(thread_id))
        return bool(snap.interrupts or (snap.values or {}).get("awaiting"))


def handle(conn, text: str, thread_id: str = "default") -> dict:
    """一轮对话：可能在提问、可能在等确认、也可能直接执行完。"""
    with _open(conn) as g:
        cfg = _cfg(thread_id)

        if clarify.is_cancel(text):
            if g.get_state(cfg).interrupts:
                g.invoke(_resume("取消"), cfg)
            _reset(g, thread_id)
            return {"reply": "已取消。", "card": None, "job": None, "trace_id": None}

        if g.get_state(cfg).interrupts:        # 正停在确认卡
            out = g.invoke(_resume(text), cfg)
        else:
            out = g.invoke({"text": text}, cfg)

        result = _shape(g, cfg, out)
        # 执行完或取消后清空槽位，避免下一轮复用
        if result.get("card") is None or (result.get("card") or {}).get("type") == "verdict":
            _reset(g, thread_id)
        return result


def _resume(value: str):
    from langgraph.types import Command
    return Command(resume=value)


def _shape(g, cfg, out: dict) -> dict:
    # 用公开 API（StateSnapshot.interrupts）判断挂起，不再依赖输出里的私有键 __interrupt__
    snap = g.get_state(cfg)
    if snap.interrupts:
        payload = getattr(snap.interrupts[0], "value", None) or {}
        return {"reply": "计划如下，确认后开始。", "card": payload.get("card"),
                "job": None, "trace_id": None, "interrupted": True}
    return {"reply": out.get("reply", ""), "card": out.get("card"),
            "job": out.get("job"), "trace_id": out.get("trace_id")}
