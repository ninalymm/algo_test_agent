"""入口：跑一个变更的完整编排链路。

用法：
    python3 agent/main.py --change "图A 召回算子改动" --scenario pass
    python3 agent/main.py --change "图A 召回算子改动" --scenario diff_fail
    python3 agent/main.py --change "图A 召回算子改动" --scenario recording_broken
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.executor import Executor
from agent.judge import judge, to_card
from agent.planner import plan_from_text
from tools.diff_mock import DiffMock
from tools.forcebot_mock import ForceBotMock
from tools.r2_mock import R2Mock

SCENARIOS = {
    "pass": dict(broken=set(), dirty=set(), metric_aligned=True),
    "diff_fail": dict(broken=set(), dirty=set(), metric_aligned=False),
    "recording_broken": dict(broken={"直播召回-1"}, dirty=set(), metric_aligned=True),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--change", default="图A 召回算子改动")
    ap.add_argument("--scenario", default="pass", choices=list(SCENARIOS))
    args = ap.parse_args()

    cfg = SCENARIOS[args.scenario]
    change, plan = plan_from_text(args.change)
    plan.metric_aligned = cfg["metric_aligned"]

    print(f"[plan] {change.kind} → 场景 {plan.scenes} 档位 {plan.qps_levels}")
    if plan.notes:
        print(f"[plan] {'; '.join(plan.notes)}")

    executor = Executor(
        R2Mock(broken_scenes=cfg["broken"], dirty_scenes=cfg["dirty"]),
        ForceBotMock(),
        DiffMock(),
    )
    state = executor.run(plan)
    verdict = judge(plan, state)
    print()
    print(to_card(verdict))
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
