"""三个 Skill 与意图路由。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import query, router, selftest, trend
from store.db import connect
from store.seed import seed


class TestSkills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_route_intents(self):
        self.assertEqual(router.route(self.conn, "任务 T-005 怎么样")["intent"], "query")
        self.assertEqual(router.route(self.conn, "我改完了 abc123f")["intent"], "selftest")
        self.assertEqual(router.route(self.conn, "场景 20260301-0001 最近趋势")["intent"], "trend")
        self.assertEqual(router.route(self.conn, "你好")["intent"], "unknown")

    def test_query_card(self):
        r = query.run(self.conn, "任务 T-005")
        self.assertEqual(r["card"]["type"], "verdict")
        names = [m["name"] for m in r["card"]["metrics"]]
        self.assertIn("净影响(DiD)", names)

    def test_selftest_confirm(self):
        r = selftest.run(self.conn, "我改完了 abc123f")
        self.assertEqual(r["card"]["type"], "confirm")
        # 共享图应自动扩到 2 个场景
        self.assertEqual(len(r["plan"]["scenes"]), 2)

    def test_precheck_blocks_unknown_change(self):
        r = selftest.run(self.conn, "我改完了", commit="nope")
        self.assertIsNone(r["card"])

    def test_trend_has_action(self):
        r = trend.run(self.conn, "20260301-0001")
        self.assertEqual(r["card"]["type"], "trend")
        self.assertIn("动作建议", r["card"]["note"])


if __name__ == "__main__":
    unittest.main()
