"""同场景历史时间线 + 分布对比 + DiD 双重差分。"""

from __future__ import annotations

from statistics import median

from store import repo


def history(conn, scene_id: str, limit: int = 10) -> list[dict]:
    return repo.reports_with_task(conn, scene_id, limit)


def _p99s(rows: list[dict]) -> list[float]:
    return [r["p99"] for r in rows if r.get("p99") is not None]


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def summary(rows: list[dict]) -> dict:
    vals = _p99s(rows)
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "median": round(median(vals), 2),
        "p90": round(quantile(vals, 0.9), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
    }


def did(target_before: list[float], target_after: list[float],
        control_before: list[float], control_after: list[float]) -> dict:
    """双重差分：扣掉对照组的同期变化。

    DiD = (目标后 - 目标前) - (对照后 - 对照前)
    """
    if not (target_before and target_after and control_before and control_after):
        return {"ok": False, "reason": "样本不足，无法计算 DiD"}

    t_delta = median(target_after) - median(target_before)
    c_delta = median(control_after) - median(control_before)
    net = t_delta - c_delta

    return {
        "ok": True,
        "target_delta": round(t_delta, 2),
        "control_delta": round(c_delta, 2),
        "net": round(net, 2),
        "verdict": "显著劣化" if net > 0.5 else ("显著改善" if net < -0.5 else "无显著变化"),
    }


def split_by_change(rows: list[dict], change_ts: str) -> tuple[list[dict], list[dict]]:
    """按变更时间把任务切成前后两段。"""
    before = [r for r in rows if (r.get("ts") or "") < change_ts]
    after = [r for r in rows if (r.get("ts") or "") >= change_ts]
    return before, after


# ---------- 序列分析（压测 + diff 双维度） ----------

def series(conn, scene_id: str, n: int = 5) -> list[dict]:
    """最近 n 次任务的压测与 diff 双维度序列（按时间正序）。"""
    rows = repo.reports_with_task(conn, scene_id, n)
    rows = list(reversed(rows))
    return [{"id": r["id"], "ts": r["ts"], "diff": r["diff_rate"], "p99": r["p99"]}
            for r in rows if r.get("p99") is not None]


def robust_z(values: list[float], target: float) -> float:
    """基于 MAD 的稳健 z 分数 —— 比均值/标准差抗离群点。"""
    if len(values) < 3:
        return 0.0
    med = median(values)
    deviations = [abs(v - med) for v in values]
    mad = median(deviations) or 1e-9
    return (target - med) / (1.4826 * mad)


def trend_label(values: list[float]) -> str:
    """用前后半段中位数判断趋势，避免被单点带偏。"""
    if len(values) < 4:
        return "样本不足"
    half = len(values) // 2
    first, second = median(values[:half]), median(values[half:])
    delta = second - first
    base = abs(first) or 1e-9
    ratio = delta / base
    if ratio > 0.05:
        return "上升"
    if ratio < -0.05:
        return "下降"
    return "平稳"
