"""极简 trace：一次编排 = 一个 trace，每步 = 一个 span。

落库到 store.span，同时在内存里维护树形结构用于输出。
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

from store import repo


class Span:
    def __init__(self, name: str, attrs: dict | None = None):
        self.name = name
        self.attrs = attrs or {}
        self.start = time.perf_counter()
        self.end: float | None = None
        self.status = "ok"
        self.children: list["Span"] = []

    def close(self, status: str = "ok") -> None:
        self.end = time.perf_counter()
        self.status = status

    @property
    def ms(self) -> int:
        return int(((self.end or time.perf_counter()) - self.start) * 1000)


class Tracer:
    def __init__(self, name: str, conn=None):
        self.trace_id = uuid.uuid4().hex[:8]
        self.name = name
        self.root = Span(name)
        self.stack: list[Span] = [self.root]
        self.conn = conn
        self.task_id: str | None = None

    @contextmanager
    def span(self, name: str, **attrs):
        s = Span(name, attrs)
        self.stack[-1].children.append(s)
        self.stack.append(s)
        try:
            yield s
        except Exception:
            s.close("error")
            raise
        else:
            s.close("ok")
        finally:
            self.stack.pop()
            self._persist(s)

    def _persist(self, s: Span) -> None:
        if self.conn is None:
            return
        try:
            repo.add_span(self.conn, self.trace_id, self.task_id, s.name,
                          int(s.start * 1000), int((s.end or s.start) * 1000),
                          s.status, s.attrs)
            self.conn.commit()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.root.close("error" if exc_type else "ok")
        return False

    def close(self) -> None:
        self.root.close()

    def tree(self) -> str:
        lines = [f"trace={self.trace_id}  {self.name}  {self.root.ms}ms  {'✅' if self.root.status=='ok' else '❌'}"]

        def walk(s: Span, prefix: str, last: bool):
            branch = "└─" if last else "├─"
            attr = "  ".join(f"{k}={v}" for k, v in s.attrs.items())
            lines.append(f"{prefix}{branch} {s.name:<18} {s.ms:>6}ms  {s.status}  {attr}")
            nxt = prefix + ("   " if last else "│  ")
            for i, c in enumerate(s.children):
                walk(c, nxt, i == len(s.children) - 1)

        for i, c in enumerate(self.root.children):
            walk(c, "", i == len(self.root.children) - 1)
        return "\n".join(lines)
