"""LangSmith 开关：默认关闭，且必须「key + 显式开关」同时满足。"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from observe import tracing


class TestSwitch(unittest.TestCase):
    def test_disabled_by_default_even_with_key(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "false"}):
            self.assertFalse(tracing.enabled())

    def test_disabled_when_switch_missing(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k"}, clear=False):
            os.environ.pop("LANGSMITH_ENABLED", None)
            self.assertFalse(tracing.enabled())

    def test_enabled_only_with_both(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "true"}):
            self.assertTrue(tracing.enabled())

    def test_switch_without_key_stays_off(self):
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "true"}, clear=False):
            os.environ.pop("LANGSMITH_API_KEY", None)
            self.assertFalse(tracing.enabled())

    def test_setup_sets_tracing_env_only_when_enabled(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "false"},
                        clear=False):
            os.environ.pop("LANGSMITH_TRACING", None)
            tracing.setup()
            self.assertNotIn("LANGSMITH_TRACING", os.environ)

        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "true"},
                        clear=False):
            tracing.setup()
            self.assertEqual(os.environ.get("LANGSMITH_TRACING"), "true")

    def test_traceable_delegates_when_disabled(self):
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            def fn(x):
                return x * 2

            wrapped = tracing.traceable(fn)
            self.assertEqual(wrapped(3), 6)
            self.assertEqual(wrapped.__name__, "fn")

    def test_switch_is_evaluated_at_call_time(self):
        """装饰时关闭、之后打开也能生效（旧实现会冻结在 import 那一刻）。"""
        def fn(x):
            return x * 2

        wrapped = tracing.traceable(fn)
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            self.assertEqual(wrapped(2), 4)

        calls = []

        def fake_build(func, run_type, name):
            def traced(*args, **kwargs):
                calls.append((run_type, args))
                return func(*args, **kwargs)
            return traced

        with patch.object(tracing, "_build_traced", side_effect=fake_build), \
                patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "true"},
                           clear=False):
            self.assertEqual(wrapped(3), 6)

        self.assertEqual(calls, [("chain", (3,))])

    def test_run_type_is_forwarded(self):
        seen = {}

        def fake_build(func, run_type, name):
            seen["run_type"] = run_type
            return func

        @tracing.traceable(run_type="llm")
        def chat(prompt):
            return prompt

        with patch.object(tracing, "_build_traced", side_effect=fake_build), \
                patch.dict(os.environ, {"LANGSMITH_API_KEY": "k", "LANGSMITH_ENABLED": "true"},
                           clear=False):
            chat("hi")

        self.assertEqual(seen["run_type"], "llm")

    def test_flush_is_noop_when_disabled(self):
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            tracing.flush()

    def test_async_function_keeps_coroutine_identity(self):
        """包一层后仍要能被框架识别为协程函数。"""
        @tracing.traceable
        async def fetch(x):
            return x + 1

        self.assertTrue(asyncio.iscoroutinefunction(fetch))
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            self.assertEqual(asyncio.run(fetch(1)), 2)


class TestEnvFile(unittest.TestCase):
    def _env_file(self, content: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / ".env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_real_env_var_wins_over_file(self):
        path = self._env_file("DEMO_KEY=fromfile\n")
        with patch.dict(os.environ, {"DEMO_KEY": "fromenv"}, clear=False):
            tracing.load_env(path, force=True)
            self.assertEqual(os.environ["DEMO_KEY"], "fromenv")

    def test_empty_env_var_falls_back_to_file(self):
        path = self._env_file("DEMO_KEY=fromfile\n")
        with patch.dict(os.environ, {"DEMO_KEY": ""}, clear=False):
            tracing.load_env(path, force=True)
            self.assertEqual(os.environ["DEMO_KEY"], "fromfile")

    def test_parser_handles_export_quotes_and_comments(self):
        self.assertEqual(tracing._parse_env_line('export A="1 2"'), ("A", "1 2"))
        self.assertEqual(tracing._parse_env_line("B=3  # 注释"), ("B", "3"))
        self.assertEqual(tracing._parse_env_line("C=a#b"), ("C", "a#b"))
        self.assertIsNone(tracing._parse_env_line("# 整行注释"))
        self.assertIsNone(tracing._parse_env_line("没有等号"))


class TestUsageMetadata(unittest.TestCase):
    def test_openai_shape(self):
        meta = tracing.usage_metadata(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        self.assertEqual(meta, {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

    def test_anthropic_shape_with_cache(self):
        meta = tracing.usage_metadata({"input_tokens": 20, "output_tokens": 8,
                                       "cache_read_input_tokens": 12,
                                       "cache_creation_input_tokens": 4})
        self.assertEqual(meta["total_tokens"], 28)
        self.assertEqual(meta["cache_read_tokens"], 12)
        self.assertEqual(meta["cache_write_tokens"], 4)

    def test_deepseek_cache_hit_is_not_double_counted(self):
        meta = tracing.usage_metadata({"prompt_tokens": 30, "completion_tokens": 10,
                                       "total_tokens": 40, "prompt_cache_hit_tokens": 25})
        self.assertEqual(meta["total_tokens"], 40)
        self.assertEqual(meta["cache_read_tokens"], 25)

    def test_openai_nested_details(self):
        meta = tracing.usage_metadata({
            "prompt_tokens": 10, "completion_tokens": 9, "total_tokens": 19,
            "prompt_tokens_details": {"cached_tokens": 6},
            "completion_tokens_details": {"reasoning_tokens": 5},
        })
        self.assertEqual(meta["cache_read_tokens"], 6)
        self.assertEqual(meta["reasoning_tokens"], 5)

    def test_missing_usage_returns_empty(self):
        self.assertEqual(tracing.usage_metadata(None), {})
        self.assertEqual(tracing.usage_metadata({}), {})


if __name__ == "__main__":
    unittest.main()
