"""LLM 薄封装 —— 只用于两处：
1) 自然语言变更描述 → 结构化字段
2) 结果 → 人话解释（可选，模板可替代）

未配置 API Key 时自动降级为规则实现，保证仓库可离线运行。
"""

import json
import os


def parse_change(text: str) -> dict:
    """自然语言 → 结构化变更。无 Key 时走关键词规则。"""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return _rule_parse(text)
    # TODO: 接入真实 LLM，要求返回 JSON
    return _rule_parse(text)


def explain(result: dict) -> str:
    """结果 → 一句话解释。无 Key 时走模板。"""
    if not os.getenv("LLM_API_KEY"):
        return _template_explain(result)
    # TODO: 接入真实 LLM
    return _template_explain(result)


def _rule_parse(text: str) -> dict:
    kinds = {"召回": "recall", "排序": "rank", "混排": "merge", "策略": "strategy"}
    kind = next((v for k, v in kinds.items() if k in text), "unknown")
    return {"raw": text, "kind": kind, "app": "unknown", "graph": "unknown"}


def _template_explain(result: dict) -> str:
    verdict = "通过" if result.get("passed") else "不通过"
    reasons = "；".join(result.get("reasons", [])) or "无"
    return f"{verdict}。原因：{reasons}"


if __name__ == "__main__":
    print(json.dumps(parse_change("图A 召回算子改动"), ensure_ascii=False))
