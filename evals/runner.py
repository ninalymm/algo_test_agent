"""评测执行器：跑批 → 聚合 → 对比基线 → 门禁。

用法：
    python3 -m evals.runner                  # 跑一遍，和基线比
    python3 -m evals.runner --update-baseline
    python3 -m evals.runner --self-check     # 注入式验证：指标真的能发现问题吗
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.metrics import THRESHOLDS, score_case  # noqa: E402

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "dataset" / "cases.json"
BASELINE = ROOT / "dataset" / "baseline.json"


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))


def dataset_sha() -> str:
    """数据集指纹：基线只对生成它的那一版 cases.json 有效。"""
    return hashlib.sha256(CASES.read_bytes()).hexdigest()[:12]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT.parent))
    except ValueError:
        return str(path)


def failed_count(pass_rate: float, n: int) -> int:
    return round((1.0 - pass_rate) * n)


def check_regression(agg: dict, base: dict) -> str | None:
    """返回回归原因；无回归返回 None。

    判分是确定性的（D6）：同一批 case 永远得同样的分，不存在抖动，
    所以门禁不设百分比容差——容差会随 case 集变大而吞掉单条退化
    （case 数 ≥ 20 时，5% 容差已足够覆盖一整个 case）。
    """
    if base.get("dataset_sha") != dataset_sha():
        return ("❌ 基线对应的数据集已变更，旧基线不可比："
                f"\n   基线 sha={base.get('dataset_sha') or '缺失'}  当前 sha={dataset_sha()}"
                "\n   确认新结果符合预期后跑 --update-baseline")
    if base.get("n") != agg["n"]:
        return f"❌ 基线 n={base.get('n')} 与当前 case 数 {agg['n']} 不一致，请重新生成基线"
    current = failed_count(agg["pass_rate"], agg["n"])
    allowed = failed_count(base["pass_rate"], base["n"])
    if current > allowed:
        return (f"❌ 回归：{current} 条未通过，基线为 {allowed} 条"
                f"（pass_rate {agg['pass_rate']} < {base['pass_rate']}）")
    return None


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
    ap.add_argument("--force", action="store_true", help="允许下调基线（默认只准变好）")
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
        if base and agg["pass_rate"] < base["pass_rate"] and not args.force:
            print(f"\n❌ 基线不会下调（{base['pass_rate']} → {agg['pass_rate']}）："
                  "先修好再更新；确认退化可接受请加 --force")
            return 1
        payload = {**agg, "dataset_sha": dataset_sha()}
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线已更新 → {_display(BASELINE)}")
        return 0

    if base is None:
        print("\n❌ 基线缺失，门禁无法判断回归：确认结果无误后跑 --update-baseline 并提交")
        return 1

    problem = check_regression(agg, base)
    if problem:
        print(f"\n{problem}")
        return 1

    print("\n✅ 无回归")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
