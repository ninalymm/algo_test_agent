"""失败分级处置策略 —— 对应 docs/decisions.md 的 D3。

三类失败的「信息量」不同：
    可自愈的   → 自动重试，人不用管
    可判定的   → 已经不合格，直接判死，人不用管
    不可判定的 → 真的不知道，才交给人
"""

from __future__ import annotations

from enum import Enum


class Handling(Enum):
    AUTO_RETRY = "auto_retry"   # 自动重试，≤2 次
    FAIL_HARD = "fail_hard"     # 结论已明确，直接判不通过
    HUMAN = "human"             # 信息不足，人工介入


SELF_HEALABLE = {"recording_not_ready", "timeout", "transient_error"}
JUDGEABLE = {"diff_over_threshold", "perf_degraded", "redline_hit"}


def classify(failure_type: str) -> Handling:
    """把失败类型映射到处置动作。未知类型一律交人 —— 宁可多审，不可漏判。"""
    if failure_type in SELF_HEALABLE:
        return Handling.AUTO_RETRY
    if failure_type in JUDGEABLE:
        return Handling.FAIL_HARD
    return Handling.HUMAN
