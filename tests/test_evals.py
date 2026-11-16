"""评测判分器：四个指标各自能抓到对应的失败类型。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_polling_is_redundant_without_allowance(self):
        calls = [{"tool": "job_status", "args": {"job_id": "T-001"}}] * 5
        self.assertAlmostEqual(redundant_call_rate(trace(calls)), 0.8)

    def test_repeat_allowance_suppresses_polling(self):
        calls = [{"tool": "job_status", "args": {"job_id": "T-001"}}] * 5
        t = trace(calls)
        t["repeat_allowance"] = {"job_status": 4}
        self.assertEqual(redundant_call_rate(t), 0.0)

    def test_repeat_allowance_is_capped(self):
        calls = [{"tool": "job_status", "args": {"job_id": "T-001"}}] * 5
        t = trace(calls)
        t["repeat_allowance"] = {"job_status": 2}
        self.assertAlmostEqual(redundant_call_rate(t), 0.4)

    def test_repeat_allowance_is_per_tool(self):
        calls = ([{"tool": "job_status", "args": {"job_id": "T-001"}}] * 3
                 + [{"tool": "metric_query", "args": {"s": "A"}}] * 2)
        t = trace(calls)
        t["repeat_allowance"] = {"job_status": 2}
        self.assertAlmostEqual(redundant_call_rate(t), 0.2)

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


class TestRunnerGate(unittest.TestCase):
    """门禁本身要 fail-closed：缺基线、换数据集、基线倒退都必须拦住。"""

    def setUp(self):
        self.agg = runner.aggregate([runner.score_case(c) for c in runner.load_cases()])
        self._orig_baseline = runner.BASELINE
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._restore)
        runner.BASELINE = Path(self._tmp.name) / "baseline.json"

    def _restore(self):
        runner.BASELINE = self._orig_baseline

    def _write_baseline(self, **overrides) -> dict:
        payload = {**self.agg, "dataset_sha": runner.dataset_sha(), **overrides}
        runner.BASELINE.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def _run(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["runner", *argv]), contextlib.redirect_stdout(out):
            rc = runner.main()
        return rc, out.getvalue()

    def test_missing_baseline_fails_closed(self):
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("基线缺失", out)

    def test_update_baseline_records_dataset_sha(self):
        rc, _ = self._run("--update-baseline")
        self.assertEqual(rc, 0)
        payload = json.loads(runner.BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_sha"], runner.dataset_sha())
        self.assertEqual(payload["n"], self.agg["n"])

    def test_dataset_change_blocks_gate_until_baseline_updated(self):
        self._write_baseline(dataset_sha="deadbeef0000")
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("数据集已变更", out)

    def test_legacy_baseline_without_sha_blocks_gate(self):
        payload = dict(self.agg)
        runner.BASELINE.write_text(json.dumps(payload), encoding="utf-8")
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("数据集已变更", out)

    def test_update_refuses_to_lower_baseline(self):
        self._write_baseline(pass_rate=1.0)
        rc, out = self._run("--update-baseline")
        self.assertEqual(rc, 1)
        self.assertIn("不会下调", out)
        self.assertEqual(json.loads(runner.BASELINE.read_text(encoding="utf-8"))["pass_rate"], 1.0)

        rc, _ = self._run("--update-baseline", "--force")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(runner.BASELINE.read_text(encoding="utf-8"))["pass_rate"],
                         self.agg["pass_rate"])

    def test_single_case_regression_is_not_absorbed(self):
        # 40 个 case 时单条退化只值 0.025，旧的 5% 容差会漏报
        base = {"pass_rate": 1.0, "n": 40, "dataset_sha": runner.dataset_sha()}
        self.assertIsNone(runner.check_regression({"pass_rate": 1.0, "n": 40}, base))
        self.assertIsNotNone(runner.check_regression({"pass_rate": 0.975, "n": 40}, base))


if __name__ == "__main__":
    unittest.main()
