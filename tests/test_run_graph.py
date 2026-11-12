"""LangGraph 版本的 run 链路（未安装 langgraph 时自动跳过）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import run_graph
from store.db import connect, init_db
from store.seed import seed

HAS_LG = run_graph.available()


@unittest.skipUnless(HAS_LG, "未安装 langgraph，跳过图版本测试")
class TestRunGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()
        init_db(cls.conn)

    def test_multi_turn_flow(self):
        tid = "g-test-1"
        run_graph.reset(self.conn, tid)

        r1 = run_graph.handle(self.conn, "帮我跑一下", tid)
        self.assertEqual(r1["card"]["type"], "ask")
        self.assertTrue(run_graph.pending(self.conn, tid))

        r2 = run_graph.handle(self.conn, "20260301-0001", tid)
        self.assertEqual(r2["card"]["type"], "ask")

        r3 = run_graph.handle(self.conn, "只跑压测", tid)
        self.assertEqual(r3["card"]["type"], "confirm")

        r4 = run_graph.handle(self.conn, "确认执行", tid)
        self.assertEqual(r4["card"]["type"], "verdict")
        self.assertFalse(run_graph.pending(self.conn, tid))

    def test_cancel_clears_state(self):
        tid = "g-test-2"
        run_graph.reset(self.conn, tid)
        run_graph.handle(self.conn, "帮我跑一下", tid)
        r = run_graph.handle(self.conn, "算了", tid)
        self.assertIsNone(r["card"])
        self.assertFalse(run_graph.pending(self.conn, tid))

    def test_state_persists_across_handles(self):
        """checkpointer 让状态跨调用存活，不需要外部 session 字典。"""
        tid = "g-test-3"
        run_graph.reset(self.conn, tid)
        run_graph.handle(self.conn, "帮我跑一下", tid)
        run_graph.handle(self.conn, "20260301-0001", tid)
        # 第三次不提供场景，靠 checkpointer 里的状态
        r = run_graph.handle(self.conn, "跑 diff", tid)
        self.assertEqual(r["card"]["type"], "confirm")


class TestFallback(unittest.TestCase):
    def test_available_flag_is_boolean(self):
        self.assertIsInstance(run_graph.available(), bool)


if __name__ == "__main__":
    unittest.main()
