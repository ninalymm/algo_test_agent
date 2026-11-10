"""核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Change:
    raw: str
    kind: str = "unknown"          # recall / rank / merge / strategy
    app: str = "unknown"
    graph: str = "unknown"


@dataclass
class Plan:
    scenes: list[str] = field(default_factory=list)
    qps_levels: list[int] = field(default_factory=list)
    diff_threshold: float = 0.01
    p99_baseline: float = 12.0
    p99_tolerance: float = 0.10
    steps: list[tuple[str, list[str]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)