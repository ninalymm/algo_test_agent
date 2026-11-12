"""判读层：执行结果 → 结论。

规则给结论，不交给模型。LLM 只负责把结论翻译成人话。
"""

from __future__ import annotations

from agent.models import Plan, Verdict
from observe.tracing import traceable
from tools.llm import explain


@traceable
def judge(plan: Plan, state: dict) -> Verdict:
    reasons, suggestions = [], []

    # 1. 录制就绪
    recording = state.get("check_recording", {})
    not_ready = [s for s, d in recording.items() if d.get("status") != 20]
    if not_ready:
        reasons.append(f"录制未就绪：{','.join(not_ready)}")

    # 2. diff 阈值
    diffs = state.get("diff", {})
    worst = max((d.get("diff_rate", 0) for d in diffs.values()), default=0)
    if worst > plan.diff_threshold:
        reasons.append(f"diff {worst:.2%} > 阈值 {plan.diff_threshold:.0%}")
        suggestions.append("排查度量/口径是否对齐，先看分数是否可比")

    # 3. 性能劣化
    perf = state.get("perf_test", {})
    for scene, by_qps in perf.items():
        for qps, d in by_qps.items():
            limit = plan.p99_baseline * (1 + plan.p99_tolerance)
            if d.get("p99", 0) > limit:
                reasons.append(f"{scene}@{qps}qps p99 {d['p99']}ms > {limit:.1f}ms")
                suggestions.append("容量劣化：扩容或降低档位")

    return Verdict(
        passed=not reasons,
        reasons=reasons,
        suggestions=suggestions,
        evidence={"diff": diffs, "perf": perf, "recording": recording},
    )


def to_card(verdict: Verdict) -> str:
    icon = "✅ 通过" if verdict.passed else "❌ 不通过"
    lines = [icon, "-" * 40]
    for s, d in verdict.evidence.get("diff", {}).items():
        lines.append(f"diff {s:<16} {d['diff_rate']:.2%}")
    for scene, by_qps in verdict.evidence.get("perf", {}).items():
        for qps, d in by_qps.items():
            lines.append(f"p99  {scene}@{qps:<6} {d['p99']}ms")
    lines.append("-" * 40)
    lines.append(f"结论：{explain({'passed': verdict.passed, 'reasons': verdict.reasons})}")
    for sug in verdict.suggestions:
        lines.append(f"建议：{sug}")
    return "\n".join(lines)