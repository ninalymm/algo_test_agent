"""澄清与多轮槽位填充。

原则（对齐 D1）：能猜的默认为「不确定就问」，不能猜的一律问；
用户答一句就补一格，补完立即出确认卡，不重复问已填的槽。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from skills import cards

SCENE_RE = re.compile(r"\d{8}-\d{4}")
TYPE_WORDS = {
    "load": ("压测", "加压", "性能", "qps"),
    "diff": ("diff", "比对", "一致性", "结果对比"),
}


@dataclass
class Pending:
    intent: str
    awaiting: str                      # "scene" | "types"
    slots: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"intent": self.intent, "awaiting": self.awaiting, "slots": self.slots}

    @staticmethod
    def from_dict(d: dict) -> "Pending":
        return Pending(d["intent"], d["awaiting"], dict(d.get("slots") or {}))


# ---------- 槽位抽取 ----------

def match_scene(text: str, known: list[str]) -> str | None:
    m = SCENE_RE.search(text)
    if m and m.group(0) in known:
        return m.group(0)
    if m:
        return m.group(0)          # 没见过也认，后面再校验存在性
    # 允许只答后四位，如“0001”
    tail = re.fullmatch(r"\s*(\d{3,4})\s*", text)
    if tail:
        hits = [s for s in known if s.endswith(tail.group(1))]
        if len(hits) == 1:
            return hits[0]
    return None


def match_types(text: str) -> str | None:
    low = text.lower()
    has_load = any(w in low for w in TYPE_WORDS["load"])
    has_diff = any(w in low for w in TYPE_WORDS["diff"])
    if has_load and has_diff:
        return "both"
    if re.search(r"(都|两个|全部|全跑|一起|both)", text, re.I):
        return "both"
    if has_load:
        return "load"
    if has_diff:
        return "diff"
    return None


def match_task(text: str, known: list[str]) -> str | None:
    """认任务 id：T-005 / 005 / 序号。"""
    m = re.search(r"T-(\d{3,})", text, re.I)
    if m:
        tid = f"T-{m.group(1)}"
        return tid if tid in known else (tid if not known else None)
    bare = re.fullmatch(r"\s*(\d{3,})\s*", text)
    if bare:
        tid = f"T-{bare.group(1)}"
        return tid if tid in known else None
    return None


def is_cancel(text: str) -> bool:
    return bool(re.search(r"(取消|算了|不跑了|cancel)", text, re.I))


# ---------- 提问 ----------

def ask_scene(known: list[str], title: str = "跑哪个场景？") -> dict:
    body = cards.ask_card(title, [f"{s}" for s in known[:5]],
                          hint="直接回场景 id，或回序号")
    body["slot"] = "scene"
    return body


def ask_task(known: list[str]) -> dict:
    body = cards.ask_card("诊断哪个任务？", [f"{t}" for t in known[:5]],
                          hint="回任务 id，或回序号")
    body["slot"] = "task"
    return body


def ask_types() -> dict:
    body = cards.ask_card("跑什么？", ["压测", "diff", "两个都跑"], hint="回一个即可")
    body["slot"] = "types"
    return body


def ask_intent() -> dict:
    return cards.ask_card("你想做什么？",
                          ["对比场景", "诊断任务", "跑压测/diff", "研发自测"],
                          hint="用一句话描述也行")


def resolve_choice(text: str, options: list[str]) -> str | None:
    """支持「回序号」或「回原文」。"""
    t = text.strip()
    if t.isdigit():
        i = int(t) - 1
        if 0 <= i < len(options):
            return options[i]
    for o in options:
        if o in t:
            return o
    return None
