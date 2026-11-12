"""评测判分器：四个指标各自能抓到对应的失败类型。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import runner
from evals.metrics import (contract_validity, label_agreement, param_fidelity,
                           redundant_call_rate, score_case)


def trace(calls, state="completed", human="completed"):
    return {"task_state": state, "human_label": human, "tool_calls": calls}


class TestMetrics(unittest.TestCase):
    def test_param_fidelity_detects_hallucination(self):
        t = trace([{"tool": "q", "args": {"sign": "FAKE"}}])
        self.assertEqual(param_fidelity(t, {"sign": ["REAL"]}), 0.0)

    def test_param_fidelity_ignores_unknown_fields(self):
        t = trace([{"tool": "q", "args": {"other": "x"}}])
        self.assertEqual(param_fidelity(t, {"sign": ["REAL"]}), 1.0)

    def test_redundant_calls(self):
        t = trace([{"tool": "q", "args": {"a": 1}}] * 4)
        self.assertEqual(redundant_call_rate(t), 0.75)

    def test_retry_with_different_args_not_redundant(self):
        t = trace([{"tool": "q", "args": {"a": 1}}, {"tool": "q", "args": {"a": 2}}])
        self.assertEqual(redundant_call_rate(t), 0.0)

    def test_contract_violation(self):
        t = trace([{"tool": "graph_parse", "args": {"graph_id": "merger-1"}}])
        self.assertEqual(contract_validity(t, {"graph_parse": {"graph_id": r"^biz-\d+$"}}), 0.0)

    def test_label_agreement(self):
        self.assertEqual(label_agreement(trace([], state="failed", human="completed")), 0.0)
        self.assertEqual(label_agreement(trace([], state="completed", human="completed")), 1.0)


class TestRunner(unittest.TestCase):
    def test_real_dataset_runs(self):
        cases = runner.load_cases()
        results = [score_case(c) for c in cases]
        agg = runner.aggregate(results)
        self.assertEqual(agg["n"], len(cases))
        # 数据集中 4 个负例、2 个正例
        self.assertAlmostEqual(agg["pass_rate"], 2 / 6, places=3)

    def test_self_check_passes(self):
        self.assertTrue(runner.self_check(runner.load_cases()))


if __name__ == "__main__":
    unittest.main()
