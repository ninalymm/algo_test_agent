"""LangSmith 开关：默认关闭，且必须「key + 显式开关」同时满足。"""

import os
import sys
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

    def test_traceable_is_noop_when_disabled(self):
        with patch.dict(os.environ, {"LANGSMITH_ENABLED": "false"}, clear=False):
            def fn(x):
                return x
            self.assertIs(tracing.traceable(fn), fn)


if __name__ == "__main__":
    unittest.main()
