"""三个必跑 case：通过 / diff 不通过 / 录制异常自愈。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.executor import Executor
from agent.judge import judge
from agent.planner import plan_from_text
from tools.diff_mock import DiffMock
from tools.forcebot_mock import ForceBotMock
from tools.r2_mock import R2Mock


def run(kind_text, broken=(), dirty=(), aligned=True):
    change, plan = plan_from_text(kind_text)
    plan.metric_aligned = aligned
    ex = Executor(R2Mock(set(broken), set(dirty)), ForceBotMock(), DiffMock())
    return judge(plan, ex.run(plan))


class TestFlow(unittest.TestCase):
    def test_pass(self):
        v = run("图A 召回算子改动")
        self.assertTrue(v.passed, v.reasons)

    def test_diff_fail(self):
        v = run("图A 召回算子改动", aligned=False)
        self.assertFalse(v.passed)
        self.assertTrue(any("diff" in r for r in v.reasons))

    def test_recording_heal(self):
        v = run("图A 召回算子改动", broken={"直播召回-1"})
        # 重启后应恢复，最终仍可通过
        self.assertTrue(v.passed, v.reasons)

    def test_perf_degrade(self):
        _, plan = plan_from_text("排序改动")
        plan.qps_levels = [2500]  # 超过拐点
        plan.metric_aligned = True
        ex = Executor(R2Mock(), ForceBotMock(), DiffMock())
        v = judge(plan, ex.run(plan))
        self.assertFalse(v.passed)
        self.assertTrue(any("p99" in r for r in v.reasons))


if __name__ == "__main__":
    unittest.main()
