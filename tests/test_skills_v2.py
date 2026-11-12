"""场景对比 / 任务诊断 / 自然语言驱动。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import diagnose, router, run, scene_report
from store import repo
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

    def test_change_block(self):
        r = diagnose.run(self.conn, "T-005")
        c = r["card"]["change"]
        self.assertEqual(c["id"], "C-001")
        self.assertEqual(c["title"], "召回算子打分逻辑调整")
        self.assertIn("1000001", c["graphs"])
        self.assertEqual(len(c["scenes"]), 2)      # 共享图展开

    def test_trend_summary(self):
        r = diagnose.run(self.conn, "T-005")
        t = r["card"]["trend"]
        self.assertEqual(t["n"], 5)
        self.assertIn("上升", t["p99"])

    def test_task_without_change(self):
        r = diagnose.run(self.conn, "T-001")
        self.assertIsNone(r["card"]["change"])

    def test_missing_task(self):
        r = diagnose.run(self.conn, "T-999")
        self.assertIsNone(r["card"])


class TestRunSkill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

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
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True})
        self.assertEqual(r["card"]["type"], "verdict")
        self.assertTrue(r["job"].startswith("J-"))
        self.assertEqual(r["card"]["job_status"], "completed")
        self.assertEqual(set(r["card"]["branches"]), {"diff", "load"})

    def test_all_branches_failed_keeps_no_task(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "simulate_fail": "sandbox"})
        self.assertEqual(r["card"]["job_status"], "failed")
        self.assertIsNone(r["task_id"])          # 全失败不写历史
        self.assertIn("已保留", r["reply"])

    def test_partial_diff_failed_load_ok(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "simulate_fail": "diff"})
        self.assertEqual(r["card"]["job_status"], "partial")
        self.assertIsNotNone(r["task_id"])       # 有产出就写历史
        self.assertTrue(r["card"]["branches"]["load"]["ok"])
        self.assertFalse(r["card"]["branches"]["diff"]["ok"])

    def test_partial_load_failed_diff_ok(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "simulate_fail": "load"})
        self.assertEqual(r["card"]["job_status"], "partial")
        self.assertFalse(r["card"]["branches"]["load"]["ok"])
        self.assertTrue(r["card"]["branches"]["diff"]["ok"])

    def test_invalid_when_aa_low(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "aa_emr": 0.85})
        self.assertEqual(r["card"]["validity"], "invalid")
        self.assertIn("结论无效", r["card"]["note"])

    def test_valid_when_aa_ok(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "aa_emr": 0.97})
        self.assertEqual(r["card"]["validity"], "valid")


class TestClarify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_multi_turn_fills_slots(self):
        sess = {}
        r1 = run.run(self.conn, "帮我跑一下", sess)
        self.assertEqual(r1["card"]["type"], "ask")
        self.assertEqual(r1["card"]["slot"], "scene")

        r2 = run.run(self.conn, "20260301-0001", sess)
        self.assertEqual(r2["card"]["type"], "ask")
        self.assertEqual(r2["card"]["slot"], "types")

        r3 = run.run(self.conn, "只跑压测", sess)
        self.assertEqual(r3["card"]["type"], "confirm")
        self.assertTrue(r3["plan"]["load"])
        self.assertFalse(r3["plan"]["diff"])
        self.assertNotIn("pending", sess)

    def test_one_shot_skips_questions(self):
        sess = {}
        r = run.run(self.conn, "帮我跑一下 20260301-0001 的压测 1200 档", sess)
        self.assertEqual(r["card"]["type"], "confirm")
        self.assertEqual(r["plan"]["qps"], [1200])

    def test_diagnose_asks_then_answers(self):
        sess = {}
        r1 = router.route(self.conn, "诊断一下", sess)
        self.assertEqual(r1["card"]["type"], "ask")
        self.assertEqual(r1["card"]["slot"], "task")
        r2 = router.route(self.conn, "T-005", sess)
        self.assertEqual(r2["card"]["type"], "verdict")
        self.assertNotIn("pending", sess)

    def test_scene_asks_then_answers(self):
        sess = {}
        r1 = router.route(self.conn, "对比一下", sess)
        self.assertEqual(r1["card"]["type"], "ask")
        self.assertEqual(r1["card"]["slot"], "scene")
        r2 = router.route(self.conn, "20260301-0001", sess)
        self.assertEqual(r2["card"]["type"], "trend")
        self.assertNotIn("pending", sess)

    def test_cancel_clears_pending_for_diagnose(self):
        sess = {}
        router.route(self.conn, "诊断一下", sess)
        r = router.route(self.conn, "算了", sess)
        self.assertIsNone(r["card"])
        self.assertNotIn("pending", sess)

    def test_cancel_clears_pending(self):
        sess = {}
        run.run(self.conn, "跑一下", sess)
        r = run.run(self.conn, "算了", sess)
        self.assertIsNone(r["card"])
        self.assertNotIn("pending", sess)


class TestFailureTaxonomy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_labels_are_staged(self):
        from agent import failure_taxonomy as tax
        self.assertEqual(tax.label("sandbox_unavailable"), "环境准备 · 沙箱不可用")
        self.assertEqual(tax.label("report_failed"), "报告生成 · 报告落库失败")
        self.assertTrue(tax.retryable("run_timeout"))
        self.assertFalse(tax.retryable("report_failed"))

    def test_branch_failure_is_classified(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "simulate_fail": "diff"})
        self.assertIn("执行 · 执行报错", r["card"]["branches"]["diff"]["label"])

    def test_sandbox_failure_hits_both_branches(self):
        r = run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                    "load": True, "diff": True, "simulate_fail": "sandbox"})
        self.assertIn("环境准备", r["card"]["branches"]["diff"]["label"])
        self.assertEqual(r["card"]["job_status"], "failed")

    def test_summary_groups_by_type(self):
        run.execute(self.conn, {"scene": "20260301-0001", "qps": [1200],
                                "load": True, "diff": True, "simulate_fail": "sandbox"})
        s = repo.attempt_summary(self.conn, "20260301-0001")
        self.assertIn("sandbox_unavailable", s["by_type"])
        self.assertGreaterEqual(s["by_stage"]["sandbox"], 1)


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
