"""R2 录制回放 Mock。

模拟录制任务的状态机：
    status=20  正常
    status=-1  录制失败（重启后可恢复）
    status=1/10 脏流量（需要先暂停再重启，否则服务端忽略）
"""

from __future__ import annotations

from tools.base import Tool, ToolResult

STATUS_OK = 20
STATUS_FAILED = -1
STATUS_DIRTY = 10


class R2Mock(Tool):
    name = "r2"

    def __init__(self, broken_scenes: set[str] | None = None, dirty_scenes: set[str] | None = None):
        self.broken = set(broken_scenes or ())
        self.dirty = set(dirty_scenes or ())
        self.restarted: list[str] = []

    def run(self, params: dict) -> ToolResult:
        scene = params["scene"]
        if scene in self.broken:
            return ToolResult(ok=False, data={"status": STATUS_FAILED, "record_success": 0, "msg": "录制失败"})
        if scene in self.dirty:
            return ToolResult(ok=False, data={"status": STATUS_DIRTY, "record_success": 3, "msg": "脏流量"})
        return ToolResult(ok=True, data={"status": STATUS_OK, "record_success": 98, "msg": ""})

    def restart(self, scene: str) -> ToolResult:
        """重启录制任务：先摘掉异常状态，再重新拉起。"""
        if scene in self.dirty:
            self.dirty.discard(scene)
        self.broken.discard(scene)
        self.restarted.append(scene)
        return ToolResult(ok=True, data={"status": STATUS_OK, "record_success": 98, "msg": "已重启"})