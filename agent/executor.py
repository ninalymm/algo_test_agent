"""执行层：按 DAG 跑步骤，带重试与自愈。

执行层只负责拿数据，不做判定 —— 判定在 judge.py。
"""

from __future__ import annotations

from typing import Callable

from agent.models import Plan
from tools.base import ToolResult


class Executor:
    def __init__(self, r2, forcebot, diff, max_retry: int = 2):
        self.r2 = r2
        self.forcebot = forcebot
        self.diff = diff
        self.max_retry = max_retry
        self.state: dict = {}

    def run(self, plan: Plan) -> dict:
        for name, deps in plan.steps:
            if not all(d in self.state for d in deps):
                continue
            self.state[name] = getattr(self, f"_step_{name}")(plan)
        return self.state

    # ---- steps ----

    def _step_check_recording(self, plan: Plan) -> dict:
        results = {}
        for scene in plan.scenes:
            r = self._with_retry(lambda s=scene: self.r2.run({"scene": s}))
            if not r.ok:
                # 自愈：脏流量/失败 → 重启一次
                r = self.r2.restart(scene)
            results[scene] = r.data
        return results

    def _step_load_test(self, plan: Plan) -> dict:
        out = {}
        for scene in plan.scenes:
            out[scene] = {qps: self.forcebot.run({"scene": scene, "qps": qps}).data
                          for qps in plan.qps_levels}
        return out

    def _step_diff(self, plan: Plan) -> dict:
        return {scene: self.diff.run({"scene": scene,
                                      "metric_aligned": plan.__dict__.get("metric_aligned", True)}).data
                for scene in plan.scenes}

    def _step_judge(self, plan: Plan) -> dict:
        return {"ready": True}

    # ---- helpers ----

    def _with_retry(self, fn: Callable[[], ToolResult]) -> ToolResult:
        last = None
        for _ in range(self.max_retry):
            last = fn()
            if last.ok:
                return last
        return last