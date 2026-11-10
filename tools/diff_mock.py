"""Diff Mock。

metric_aligned=False 时复现「度量选型不一致」：diff 率 97%、Top100 全不一致。
metric_aligned=True  时是修复后的状态：0.5%、Top100 一致。
"""

from __future__ import annotations

from tools.base import Tool, ToolResult

BROKEN_DIFF_RATE = 0.97
FIXED_DIFF_RATE = 0.005


class DiffMock(Tool):
    name = "diff"

    def run(self, params: dict) -> ToolResult:
        aligned = params.get("metric_aligned", True)
        rate = FIXED_DIFF_RATE if aligned else BROKEN_DIFF_RATE
        return ToolResult(
            ok=True,
            data={
                "diff_rate": rate,
                "top100_consistent": aligned,
                "fields": params.get("fields", ["itemId", "score"]),
                "ordered": params.get("ordered", True),
            },
        )