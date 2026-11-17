"""LangSmith 埋点：默认关闭，需要两个条件同时满足才启用。

    1. .env 或环境变量里配了 LANGSMITH_API_KEY
    2. 显式打开 LANGSMITH_ENABLED=true

只设 key 不会启用 —— 避免「拿了 key 就自动上传」这种意外。
"""

from __future__ import annotations

import atexit
import functools
import inspect
import os
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTHY = {"1", "true", "yes", "on"}
_ENV_LOADED = False
_FLUSH_REGISTERED = False


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """解析一行 .env：支持 `export K=V`、引号包裹、`V  # 注释`。"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    else:
        # 只在 # 前有空白时当作注释，避免把 key 里的 # 切断
        for i, ch in enumerate(value):
            if ch == "#" and (i == 0 or value[i - 1].isspace()):
                value = value[:i].rstrip()
                break
    return (key, value) if key else None


def load_env(path: Path | None = None, *, force: bool = False) -> None:
    """极简 .env 解析（不引第三方依赖）。

    真实环境变量优先，只填空缺或空串；默认只加载一次，
    显式传 path 或 force=True 可重复加载。
    """
    global _ENV_LOADED
    if _ENV_LOADED and path is None and not force:
        return
    p = path or (ROOT / ".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if not os.environ.get(key, "").strip():
                os.environ[key] = value
    if path is None:
        _ENV_LOADED = True


load_env()


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
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", "").strip() or "(默认)",
        "sampling_rate": os.getenv("LANGSMITH_SAMPLING_RATE", "").strip() or "1.0",
    }


def setup() -> dict:
    """在服务启动时调用一次。未启用就什么都不做。"""
    st = status()
    if not st["enabled"]:
        return st
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", st["project"])
    _ensure_flush_on_exit()
    return st


def flush() -> None:
    """把后台队列里没发出去的 run 发完（短命脚本结束前调用）。"""
    if not enabled():
        return
    try:
        from langsmith import Client
        Client().flush()
    except Exception:
        pass


def _ensure_flush_on_exit() -> None:
    global _FLUSH_REGISTERED
    if not _FLUSH_REGISTERED:
        atexit.register(flush)
        _FLUSH_REGISTERED = True


_INPUT_KEYS = ("input_tokens", "prompt_tokens")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens")
_CACHE_READ_KEYS = ("cache_read_input_tokens", "prompt_cache_hit_tokens")
_CACHE_WRITE_KEYS = ("cache_creation_input_tokens",)


def usage_metadata(usage: dict | None) -> dict:
    """把各家 API 的 usage 归一化成 langsmith 认识的 usage_metadata。

    只统计 input/output/total；缓存命中、缓存写入、推理 token 单价不同，
    一并附上便于成本回溯。流式响应没带 usage 时返回空 dict。

        @traceable(run_type="llm")
        def chat(prompt: str) -> dict:
            resp = call_llm(prompt)
            return {"content": resp["content"],
                    "usage_metadata": usage_metadata(resp.get("usage"))}
    """
    if not usage:
        return {}

    def pick(keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int):
                return value
        return None

    details_in = usage.get("prompt_tokens_details")
    details_out = usage.get("completion_tokens_details")

    meta: dict = {}
    if (n := pick(_INPUT_KEYS)) is not None:
        meta["input_tokens"] = n
    if (n := pick(_OUTPUT_KEYS)) is not None:
        meta["output_tokens"] = n
    total = pick(("total_tokens",))
    if total is None and "input_tokens" in meta and "output_tokens" in meta:
        total = meta["input_tokens"] + meta["output_tokens"]
    if total is not None:
        meta["total_tokens"] = total

    cache_read = pick(_CACHE_READ_KEYS)
    if cache_read is None and isinstance(details_in, dict):
        cached = details_in.get("cached_tokens")
        cache_read = cached if isinstance(cached, int) else None
    if cache_read is not None:
        meta["cache_read_tokens"] = cache_read

    cache_write = pick(_CACHE_WRITE_KEYS)
    if cache_write is not None:
        meta["cache_write_tokens"] = cache_write

    reasoning = None
    if isinstance(details_out, dict):
        value = details_out.get("reasoning_tokens")
        reasoning = value if isinstance(value, int) else None
    if reasoning is not None:
        meta["reasoning_tokens"] = reasoning

    return meta


def _build_traced(func, run_type: str, name: str | None,
                  metadata: dict | None = None):
    """构造真正的 langsmith 包装；失败则降级为原函数并告警一次。

    metadata 会挂到每一次 run 上，用来记录「模型名 / prompt 版本 / 实验标签」这类
    不参与业务逻辑、但排查和成本回溯需要的字段。
    """
    try:
        from langsmith import traceable as ls_traceable
    except Exception as exc:  # langsmith 是可选依赖
        warnings.warn(f"langsmith 不可用，{getattr(func, '__name__', func)} 不会被追踪：{exc}",
                      RuntimeWarning, stacklevel=3)
        return func
    kwargs = {"run_type": run_type}
    if name:
        kwargs["name"] = name
    if metadata:
        kwargs["metadata"] = dict(metadata)
    return ls_traceable(func, **kwargs)


def traceable(fn=None, *, run_type: str = "chain", name: str | None = None,
              metadata: dict | None = None):
    """LangSmith 装饰器；未启用时就是原函数的一层薄包装。

    开关在每次调用时求值，运行中打开 LANGSMITH_ENABLED 也能生效。

        @traceable                                    # 业务函数 → chain
        @traceable(run_type="llm")                    # LLM 调用 → UI 显示为 llm
        @traceable(run_type="llm", metadata={"model": "deepseek"})  # 附带自定义字段
    """

    def decorate(func):
        state: dict = {"impl": None}

        def resolve():
            if state["impl"] is None:
                extra = {"metadata": metadata} if metadata else {}
                state["impl"] = _build_traced(func, run_type, name, **extra) or func
                _ensure_flush_on_exit()
            return state["impl"]

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not enabled():
                    return await func(*args, **kwargs)
                return await resolve()(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not enabled():
                return func(*args, **kwargs)
            return resolve()(*args, **kwargs)

        return wrapper

    return decorate(fn) if fn is not None else decorate
