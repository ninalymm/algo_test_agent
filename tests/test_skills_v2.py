"""场景对比 / 任务诊断 / 自然语言驱动。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import diagnose, router, run, scene_report
from store.db import connect
from store.seed import seed


class TestSceneReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_returns_table(self):
        r = scene_report.run(self.conn, "20260301-0001", 5)
        card = r["card"]
        self.assertEqual(card["type"], "trend")
        self.assertEqual(len(card["rows"]), 5)
        self.assertIn("p99", card["columns"])

    def test_detects_degradation(self):
        r = scene_report.run(self.conn, "20260301-0001", 5)
        self.assertIn("p99", r["card"]["note"])
        self.assertIn("建议", r["card"]["note"])

    def test_insufficient_samples(self):
        r = scene_report.run(self.conn, "20260302-0001", 5)
        self.assertIsNone(r["card"])


class TestDiagnose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_flags_near_threshold_diff(self):
        r = diagnose.run(self.conn, "T-005")
        self.assertEqual(r["card"]["type"], "verdict")
        self.assertIn("接近阈值", r["card"]["note"])

    def test_p99_deviation_reported(self):
        r = diagnose.run(self.conn, "T-005")
        self.assertIn("p99", r["card"]["note"])

    def test_missing_task(self):
        r = diagnose.run(self.conn, "T-999")
        self.assertIsNone(r["card"])


class TestRunSkill(unittest.TestCase):
    def test_parse_load_only(self):
        p = run.parse("帮我跑一下 20260301-0001 的压测，1200 档")
        self.assertTrue(p["load"])
        self.assertFalse(p["diff"])
        self.assertEqual(p["qps"], [1200])

    def test_parse_diff_only(self):
        p = run.parse("跑个 diff 看看 20260301-0001")
        self.assertFalse(p["load"])
        self.assertTrue(p["diff"])

    def test_parse_default_both(self):
        p = run.parse("20260301-0001 跑一下")
        self.assertTrue(p["load"] and p["diff"])

    def test_execute_returns_verdict(self):
        r = run.execute(None, {"scenes": ["20260301-0001"], "qps": [1200],
                               "load": True, "diff": True})
        self.assertEqual(r["card"]["type"], "verdict")


class TestRouterV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_four_intents(self):
        self.assertEqual(router.route(self.conn, "场景 20260301-0001 最近 5 次怎么样")["intent"], "scene")
        self.assertEqual(router.route(self.conn, "任务 T-005 有什么问题")["intent"], "diagnose")
        self.assertEqual(router.route(self.conn, "帮我跑一下 20260301-0001 的压测")["intent"], "run")
        self.assertEqual(router.route(self.conn, "我改完了 abc123f")["intent"], "selftest")


if __name__ == "__main__":
    unittest.main()
