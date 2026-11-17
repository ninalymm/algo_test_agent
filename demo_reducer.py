"""reducer = 「同一个 key 被写多次时，怎么合并」的函数。

签名固定：(当前值, 新值) -> 合并后的值
"""
import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END


# ---------- 自定义 reducer：去重追加 ----------
def append_unique(old: list, new: list) -> list:
    out = list(old or [])
    for x in new or []:
        if x not in out:
            out.append(x)
    return out


# ---------- 自定义 reducer：只留最近 3 条 ----------
def last3(old: list, new: list) -> list:
    return (list(old or []) + list(new or []))[-3:]


class S(TypedDict, total=False):
    logs:  Annotated[list, operator.add]      # 普通追加
    uniq:  Annotated[list, append_unique]     # 去重追加
    tail:  Annotated[list, last3]             # 只留最近 3 条
    reply: str                                # 没有 reducer → 覆盖


def n1(s):
    return {"logs": ["a"], "uniq": ["a", "b"], "tail": ["a", "b"], "reply": "第1步"}


def n2(s):
    return {"logs": ["b"], "uniq": ["b", "c"], "tail": ["c", "d"], "reply": "第2步"}


def n3(s):
    return {"logs": ["c"], "uniq": ["d"], "tail": ["e"], "reply": "第3步"}


g = StateGraph(S)
for name, fn in [("n1", n1), ("n2", n2), ("n3", n3)]:
    g.add_node(name, fn)
g.add_edge(START, "n1"); g.add_edge("n1", "n2"); g.add_edge("n2", "n3"); g.add_edge("n3", END)
app = g.compile()

out = app.invoke({"logs": [], "uniq": [], "tail": []})
print("=== 三种 reducer 的最终结果 ===")
print("logs  (operator.add) :", out["logs"], "  ← 全追加")
print("uniq  (append_unique):", out["uniq"], "  ← 追加但去重")
print("tail  (last3)        :", out["tail"], "  ← 只留最近 3 条")
print("reply (无 reducer)   :", repr(out["reply"]), " ← 覆盖，只剩最后一步")
