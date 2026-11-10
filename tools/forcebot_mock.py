"""ForceBot 压测 Mock。

rt 曲线在 1200qps 之后立方级劣化 —— 与真实项目的拐点一致。
"""

from __future__ import annotations

from tools.base import Tool, ToolResult

KNEE_QPS = 1200
BASE_AVG = 6.0
BASE_P99 = 12.0


def _penalty(qps: int) -> float:
    if qps <= KNEE_QPS:
        return 1.0
    return 1 + ((qps - KNEE_QPS) / KNEE_QPS) ** 3


class ForceBotMock(Tool):
    name = "forcebot"

    def run(self, params: dict) -> ToolResult:
        qps = int(params["qps"])
        p = _penalty(qps)
        return ToolResult(
            ok=True,
            data={
                "qps": qps,
                "avg": round(BASE_AVG * p, 1),
                "p99": round(BASE_P99 * p, 1),
                "cpu": {
                    "qrs": round(min(95.0, qps / KNEE_QPS * 72), 1),
                    "searcher": 46.0,
                },
            },
        )