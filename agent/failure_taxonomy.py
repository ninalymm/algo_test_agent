"""失败口径：每一次失败必须标注「发生在哪个阶段」和「属于哪种类型」。

没有口径的失败率是没有意义的数字——「2 轮失败」既可能是沙箱没起来，
也可能是报告没落库，处置方式完全不同。
"""

from __future__ import annotations

# 阶段：流水线的六个位置
STAGES = {
    "precheck": "预检",
    "sandbox": "环境准备",
    "recording": "录制就绪",
    "run": "执行",
    "report": "报告生成",
    "judge": "判读",
}

# 类型 → (阶段, 是否可自动重试, 处置说明)
TYPES = {
    "param_invalid":       ("precheck",  False, "参数/变更不合法，需人工修正后重提"),
    "sandbox_unavailable": ("sandbox",   True,  "沙箱/资源不可用，可重试；连续失败需找环境负责人"),
    "recording_not_ready": ("recording", True,  "录制未就绪，可自愈重启（D3）"),
    "run_timeout":         ("run",       True,  "执行超时，可重跑；连续超时怀疑容量或数据量"),
    "run_error":           ("run",       True,  "执行报错，可重跑并保留现场"),
    "report_failed":       ("report",    False, "报告落库失败，需检查存储；重跑不能解决"),
    "judge_error":         ("judge",     False, "判读异常，属代码缺陷，需修代码"),
}


def stage_of(failure_type: str) -> str:
    return TYPES.get(failure_type, ("run", False, ""))[0]


def retryable(failure_type: str) -> bool:
    return TYPES.get(failure_type, ("run", False, ""))[1]


def describe(failure_type: str) -> str:
    return TYPES.get(failure_type, ("run", False, "未知失败类型"))[2]


def label(failure_type: str) -> str:
    """给人看的一行：环境准备 · 沙箱不可用"""
    stage = stage_of(failure_type)
    name = {
        "param_invalid": "参数不合法",
        "sandbox_unavailable": "沙箱不可用",
        "recording_not_ready": "录制未就绪",
        "run_timeout": "执行超时",
        "run_error": "执行报错",
        "report_failed": "报告落库失败",
        "judge_error": "判读异常",
    }.get(failure_type, failure_type)
    return f"{STAGES.get(stage, stage)} · {name}"
