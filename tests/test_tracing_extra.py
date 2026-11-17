"""只测「开关 + 纯函数 + 包装层」，全程不联网、不真上报。

原则：LangSmith 自己会不会发数据，是 SDK 的事；我们要测的是自己这层的行为。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from observe import tracing


class TestEnvLineBoundary(unittest.TestCase):
    """_parse_env_line：纯函数，直接调，不需要任何环境。"""

    def test_hash_without_leading_space_is_kept(self):
        # KEY=ab#cd 里的 # 前面没有空白 → 不是注释，要保留
        k, v = tracing._parse_env_line("KEY=ab#cd")
        self.assertEqual((k, v), ("KEY", "ab#cd"))

    def test_hash_with_space_is_comment(self):
        k, v = tracing._parse_env_line("KEY=abc  # 注释")
        self.assertEqual(v, "abc")

    def test_export_and_quotes(self):
        self.assertEqual(tracing._parse_env_line('export K="v1"'), ("K", "v1"))


class TestUsageNormalization(unittest.TestCase):
    """usage_metadata：纯函数，输入各家 usage 形态，输出标准字段。"""

    def test_total_tokens_derived_when_absent(self):
        meta = tracing.usage_metadata({"prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual(meta["total_tokens"], 15)

    def test_non_int_value_ignored(self):
        meta = tracing.usage_metadata({"prompt_tokens": "12"})   # 字符串不是 int
        self.assertNotIn("input_tokens", meta)

    def test_none_returns_empty(self):
        self.assertEqual(tracing.usage_metadata(None), {})


class TestDegrade(unittest.TestCase):
    """降级：langsmith 不可用时，业务照跑、只告警、不抛异常。"""

    def test_build_traced_falls_back_when_langsmith_missing(self):
        def fn(x):
            return x * 2

        with patch.dict(sys.modules, {"langsmith": None}):
            with self.assertWarns(RuntimeWarning):
                wrapped = tracing._build_traced(fn, "chain", None)
        self.assertIs(wrapped, fn)          # 原样返回，不是包装
        self.assertEqual(wrapped(3), 6)     # 行为不变


class TestMetadataForwarding(unittest.TestCase):
    """想 trace 自定义字段时，metadata 必须被透传给 langsmith。"""

    def test_build_traced_forwards_metadata(self):
        captured = {}

        class FakeTraceable:
            def __init__(self, fn, **kw):
                captured.update(kw)

            def __call__(self, *a, **k):
                return "traced"

        fake_mod = type(sys)("langsmith")
        fake_mod.traceable = FakeTraceable

        def fn():
            return "orig"

        with patch.dict(sys.modules, {"langsmith": fake_mod}):
            tracing._build_traced(fn, "llm", "my_llm", metadata={"model": "deepseek"})

        self.assertEqual(captured["run_type"], "llm")
        self.assertEqual(captured["name"], "my_llm")
        self.assertEqual(captured["metadata"], {"model": "deepseek"})


if __name__ == "__main__":
    unittest.main()


class TestSdkFlagBackfill(unittest.TestCase):
    """回归 BUG：只设 ENABLED 时 langsmith SDK 的 LANGSMITH_TRACING 仍为空，
    装饰器静默不产生 run（CLI 入口不调 setup() 时会踩到）。"""

    def test_resolve_backfills_sdk_tracing_flag(self):
        def fake_build(func, run_type, name):
            return func

        @tracing.traceable
        def f():
            return 1

        env = {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGSMITH_TRACING", None)   # 模拟 CLI 场景：没人调 setup()
            with patch.object(tracing, "_build_traced", side_effect=fake_build):
                self.assertEqual(f(), 1)
            self.assertEqual(os.environ.get("LANGSMITH_TRACING"), "true")

    def test_disabled_does_not_backfill(self):
        @tracing.traceable
        def f():
            return 1

        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            os.environ.pop("LANGSMITH_TRACING", None)
            f()
            self.assertIsNone(os.environ.get("LANGSMITH_TRACING"))
