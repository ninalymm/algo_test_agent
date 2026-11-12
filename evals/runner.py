"""评测执行器：跑批 → 聚合 → 对比基线 → 门禁。

用法：
    python3 -m evals.runner                  # 跑一遍，和基线比
    python3 -m evals.runner --update-baseline
    python3 -m evals.runner --self-check     # 注入式验证：指标真的能发现问题吗
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.metrics import THRESHOLDS, score_case  # noqa: E402

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "dataset" / "cases.json"
BASELINE = ROOT / "dataset" / "baseline.json"
TOLERANCE = 0.05


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))


def aggregate(results: list[dict]) -> dict:
    n = len(results) or 1
    keys = list(THRESHOLDS)
    avg = {k: round(sum(r["scores"][k] for r in results) / n, 3) for k in keys}
    passed = sum(1 for r in results if r["passed"])
    return {"pass_rate": round(passed / n, 3), "metrics": avg, "n": len(results)}


def render(results: list[dict], agg: dict, base: dict | None) -> str:
    lines = []
    def row(tag, mark, m, name="", tail=""):
        return (f"{tag:<7}{mark:<5}"
                f"{m['param_fidelity']:>8.2f}{m['redundant_call_rate']:>10.2f}"
                f"{m['contract_validity']:>8.2f}{m['label_agreement']:>8.2f}  {name}{tail}")

    lines.append(f"{'ID':<7}{'':<5}{'参数保真':>8}{'冗余率':>10}{'契约':>9}{'口径':>8}  案例")
    lines.append("-" * 86)
    for r in results:
        mark = "✅" if r["passed"] else "❌"
        lines.append(row(r["id"], mark, r["scores"], r["name"]))
    lines.append("-" * 86)
    lines.append(row("汇总", "", agg["metrics"], "", f"pass_rate={agg['pass_rate']:.2f}"))
    if base:
        delta = agg["pass_rate"] - base["pass_rate"]
        arrow = "→" if abs(delta) < 1e-9 else ("↑" if delta > 0 else "↓")
        lines.append(row("基线", "", base["metrics"], "",
                         f"pass_rate={base['pass_rate']:.2f}  {arrow}{abs(delta):.2f}"))
    return "\n".join(lines)


def self_check(cases: list[dict]) -> bool:
    """注入式验证：把真值字段改成编造值，指标必须下降。

    如果改了还满分，说明这个指标根本测不出问题。
    """
    ok = True
    for case in cases:
        truth = case.get("truth") or {}
        if not truth:
            continue
        field = next(iter(truth))
        mutated = copy.deepcopy(case)
        calls = mutated["trace"].get("tool_calls") or []
        if not calls:
            continue
        calls[0].setdefault("args", {})[field] = "__HALLUCINATED__"

        before = score_case(case)["scores"]["param_fidelity"]
        after = score_case(mutated)["scores"]["param_fidelity"]
        if before == 0.0:
            print(f"  ⏭  {case['id']} 原本已为 0（该 case 本就是负例），跳过")
            continue
        if before <= after:
            print(f"  ❌ {case['id']} 注入编造值后 param_fidelity 未下降（{before} → {after}）")
            ok = False
        else:
            print(f"  ✅ {case['id']} 注入后下降：{before:.2f} → {after:.2f}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    cases = load_cases()

    if args.self_check:
        print("注入式验证（指标有效性）")
        ok = self_check(cases)
        print("\n结论：" + ("指标有效 ✅" if ok else "指标失效 ❌"))
        return 0 if ok else 1

    results = [score_case(c) for c in cases]
    agg = aggregate(results)

    base = None
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))

    print(render(results, agg, base))

    if args.update_baseline:
        BASELINE.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线已更新 → {BASELINE.relative_to(ROOT.parent)}")
        return 0

    if base and agg["pass_rate"] < base["pass_rate"] - TOLERANCE:
        print(f"\n❌ 回归：pass_rate {agg['pass_rate']} 低于基线 {base['pass_rate']} - {TOLERANCE}")
        return 1

    print("\n✅ 无回归")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
