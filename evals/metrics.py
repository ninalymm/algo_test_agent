"""四个判分器 —— 全部是规则，不依赖模型。

对应 docs/decisions.md 的 D6：判读只信规则。
这里的“被测对象”不是推荐系统，是 **Agent 的执行轨迹**。
"""

from __future__ import annotations

import json
import re


# ---------- ① 参数保真 ----------

def param_fidelity(trace: dict, truth: dict) -> float:
    """工具实参是否来自真值集合。

    只检查 truth 里出现过的字段（没给真值的字段不判，避免误杀）。
    """
    checked = ok = 0
    for call in trace.get("tool_calls", []):
        for key, value in (call.get("args") or {}).items():
            if key not in truth:
                continue
            checked += 1
            if value in truth[key]:
                ok += 1
    return 1.0 if checked == 0 else ok / checked


# ---------- ② 冗余调用 ----------

def redundant_call_rate(trace: dict) -> float:
    """同 (tool, args) 被调用超过一次，即计为浪费。"""
    calls = trace.get("tool_calls", [])
    if not calls:
        return 0.0
    seen = set()
    redundant = 0
    for call in calls:
        key = (call.get("tool"), json.dumps(call.get("args") or {}, sort_keys=True, ensure_ascii=False))
        if key in seen:
            redundant += 1
        seen.add(key)
    return redundant / len(calls)


# ---------- ③ 工具契约 ----------

def contract_validity(trace: dict, contract: dict) -> float:
    """ID 类参数是否符合格式契约（如 graph_parse 只接受 biz-*）。"""
    checked = violated = 0
    for call in trace.get("tool_calls", []):
        rules = contract.get(call.get("tool"))
        if not rules:
            continue
        for key, pattern in rules.items():
            value = (call.get("args") or {}).get(key)
            if value is None:
                continue
            checked += 1
            if not re.match(pattern, str(value)):
                violated += 1
    return 1.0 if checked == 0 else 1 - violated / checked


# ---------- ④ 口径一致 ----------

def label_agreement(trace: dict) -> float:
    """Agent 记录的 task_state 与人工标注是否一致。"""
    human = trace.get("human_label")
    if not human:
        return 1.0          # 没标注就不判
    return 1.0 if trace.get("task_state") == human else 0.0


# ---------- 汇总 ----------

THRESHOLDS = {
    "param_fidelity": 1.0,
    "redundant_call_rate": 0.0,
    "contract_validity": 1.0,
    "label_agreement": 1.0,
}


def score_case(case: dict) -> dict:
    trace = case["trace"]
    scores = {
        "param_fidelity": param_fidelity(trace, case.get("truth") or {}),
        "redundant_call_rate": redundant_call_rate(trace),
        "contract_validity": contract_validity(trace, case.get("contract") or {}),
        "label_agreement": label_agreement(trace),
    }
    failed = [k for k, v in scores.items() if v != THRESHOLDS[k]]
    return {
        "id": case["id"],
        "name": case["name"],
        "scores": scores,
        "passed": not failed,
        "failed_metrics": failed,
    }
