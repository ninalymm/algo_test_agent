"""LangSmith 埋点：默认关闭，需要两个条件同时满足才启用。

    1. .env 里配了 LANGSMITH_API_KEY
    2. 显式打开 LANGSMITH_ENABLED=true

只设 key 不会启用 —— 避免「拿了 key 就自动上传」这种意外。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_LOADED = False


def load_env(path: Path | None = None) -> None:
    """极简 .env 解析（不引第三方依赖），已存在的环境变量优先。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    p = path or (ROOT / ".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    _ENV_LOADED = True


load_env()

TRUTHY = {"1", "true", "yes", "on"}


def has_key() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY", "").strip())


def enabled() -> bool:
    """必须显式开关 + 有 key。"""
    return os.getenv("LANGSMITH_ENABLED", "").strip().lower() in TRUTHY and has_key()


def status() -> dict:
    return {
        "key_present": has_key(),
        "switch": os.getenv("LANGSMITH_ENABLED", "").strip() or "(未设置)",
        "enabled": enabled(),
        "project": os.getenv("LANGSMITH_PROJECT", "algo-test-agent"),
    }


def setup() -> dict:
    """在服务启动时调用一次。未启用就什么都不做。"""
    st = status()
    if not st["enabled"]:
        return st
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", st["project"])
    return st


def traceable(fn):
    """启用时包一层 LangSmith tracing，否则原样返回。"""
    if not enabled():
        return fn
    try:
        from langsmith import traceable as ls_traceable
        return ls_traceable(fn)
    except Exception:
        return fn
