from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict, total=False):
    text: str
    intent: str | None
    reply: str

def parse(s):
    return {"intent": "run" if "跑" in (s.get("text") or "") else None}

def ask(s):
    return {"reply": "还差信息"}

def run(s):
    return {"reply": "开始执行"}

def route(s):
    return "ask" if s.get("intent") else "ask"

g = StateGraph(S)
g.add_node("parse", parse); g.add_node("ask", ask); g.add_node("run", run)
g.add_edge(START, "parse")
g.add_node("retry", lambda s: {"reply": "重试"})
g.add_conditional_edges("parse", route, {"run": "run", "ask": "ask"})
g.add_edge("ask", END); g.add_edge("run", END)
app = g.compile()

for t in ["帮跑我一下场景A", "你好"]:
    print(app.invoke({"reply": "你好吗"}))
    print(t, "→", app.invoke({"text": t}))
