"""D3 分级策略的单测。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.failure import Handling, classify


class TestFailurePolicy(unittest.TestCase):
    def test_self_healable(self):
        self.assertIs(classify("recording_not_ready"), Handling.AUTO_RETRY)
        self.assertIs(classify("timeout"), Handling.AUTO_RETRY)

    def test_judgeable(self):
        self.assertIs(classify("diff_over_threshold"), Handling.FAIL_HARD)
        self.assertIs(classify("perf_degraded"), Handling.FAIL_HARD)

    def test_unknown_goes_to_human(self):
        # 未知失败类型 → 交人，宁可多审不可漏判
        self.assertIs(classify("something_new"), Handling.HUMAN)


if __name__ == "__main__":
    unittest.main()
