from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict, total=False):
    text: str
    intent: str | None
    reply: str

def parse(s):
    print("  parse 收到:", dict(s))
    r = {"intent": "run" if "跑" in (s.get("text") or "") else None}
    print("  parse 返回:", r)
    return r

def ask(s):
    print("  ask   收到:", dict(s))
    r = {"reply": "还差信息"}
    print("  ask   返回:", r)
    return r

def run(s):
    print("  run   收到:", dict(s))
    r = {"reply": "开始执行"}
    print("  run   返回:", r)
    return r

def route(s):
    nxt = "run" if s.get("intent") else "ask"
    print("  route 判定 intent=%r → 走 %s" % (s.get("intent"), nxt))
    return nxt

g = StateGraph(S)
g.add_node("parse", parse); g.add_node("ask", ask); g.add_node("run", run)
g.add_edge(START, "parse")
g.add_conditional_edges("parse", route, {"run": "run", "ask": "ask"})
g.add_edge("ask", END); g.add_edge("run", END)
app = g.compile()

for payload in [{"text": "帮我跑一下"}, {"reply": "你好"}]:
    print("\n=== invoke(%r) ===" % payload)
    out = app.invoke(payload)
    print("  → 最终 State:", out)
