"""工具层抽象：Mock 与真实平台实现同一个签名，替换只改 import。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class Tool(ABC):
    name: str = "tool"

    @abstractmethod
    def run(self, params: dict) -> ToolResult:
        ...