"""样例数据：3 张图 / 4 个场景 / 12 次任务，含共享图与对照组。"""

from __future__ import annotations

import json

from store.db import connect, init_db, reset


APPS = [("foxcontent", "直播内容"), ("intelligence-merge", "合并引擎")]

SCENES = [
    ("20260301-0001", "foxcontent", "直播召回-A", "首页双坑", 0.42),
    ("20260301-0002", "foxcontent", "直播召回-B", "频道置顶坑", 0.31),
    ("20260302-0001", "intelligence-merge", "商详排序", "商详页", 0.15),
    ("20260303-0001", "foxcontent", "对照场景", "首页单坑", 0.12),
]

GRAPHS = [
    ("1000001", "直播召回主图"),
    ("1000002", "商详排序图"),
    ("1000003", "对照图"),
]

SCENE_GRAPH = [
    ("20260301-0001", "1000001"),
    ("20260301-0002", "1000001"),   # 共享图：一个图两个场景
    ("20260302-0001", "1000002"),
    ("20260303-0001", "1000003"),
]

CHANGES = [
    ("C-001", "abc123f", "MR-8801", ["1000001"], "algo-wang", "2026-11-05 10:00"),
    ("C-002", "def456a", "MR-8802", ["1000002"], "algo-li", "2026-11-06 14:00"),
]


def _task(tid, scene, graph, change, ts, diff, p99, verdict="pass"):
    return (tid, scene, graph, change, ts, diff, p99, verdict)


# 场景 A：改动前 3 次（p99≈11.2）、改动后 2 次（p99≈13.0）—— 明显劣化
# 对照场景：同期 p99 从 10.0 → 10.2 —— 大盘基本平稳
TASKS = [
    ("T-001", "20260301-0001", "1000001", None, "2026-11-01 09:00", 0.006, 11.0),
    ("T-002", "20260301-0001", "1000001", None, "2026-11-02 09:00", 0.005, 11.4),
    ("T-003", "20260301-0001", "1000001", None, "2026-11-03 09:00", 0.007, 11.2),
    ("T-004", "20260301-0001", "1000001", "C-001", "2026-11-06 09:00", 0.006, 13.1),
    ("T-005", "20260301-0001", "1000001", "C-001", "2026-11-07 09:00", 0.009, 12.9),
    ("T-006", "20260301-0002", "1000001", None, "2026-11-03 10:00", 0.005, 12.4),
    ("T-007", "20260301-0002", "1000001", "C-001", "2026-11-07 10:00", 0.008, 12.6),
    ("T-008", "20260303-0001", "1000003", None, "2026-11-02 11:00", 0.004, 10.0),
    ("T-009", "20260303-0001", "1000003", None, "2026-11-03 11:00", 0.005, 10.1),
    ("T-010", "20260303-0001", "1000003", "C-001", "2026-11-07 11:00", 0.005, 10.2),
    ("T-011", "20260302-0001", "1000002", None, "2026-11-04 15:00", 0.005, 9.8),
    ("T-012", "20260302-0001", "1000002", "C-002", "2026-11-07 15:00", 0.006, 9.9),
]


def seed(path=None) -> None:
    conn = connect(path)
    init_db(conn)
    reset(conn)

    conn.executemany("INSERT INTO app(id, name) VALUES (?,?)", APPS)
    conn.executemany("INSERT INTO scene(id, app_id, name, entry_config, traffic_share) VALUES (?,?,?,?,?)", SCENES)
    conn.executemany("INSERT INTO graph(id, name) VALUES (?,?)", GRAPHS)
    conn.executemany("INSERT INTO scene_graph(scene_id, graph_id) VALUES (?,?)", SCENE_GRAPH)
    conn.executemany("INSERT INTO change(id, commit_id, mr, graph_ids, author, ts) VALUES (?,?,?,?,?,?)",
                     [(c[0], c[1], c[2], json.dumps(c[3]), c[4], c[5]) for c in CHANGES])

    for tid, scene, graph, change, ts, diff, p99 in TASKS:
        conn.execute("INSERT INTO task(id, scene_id, graph_id, change_id, trigger, status, ts) "
                     "VALUES (?,?,?,?,?,?,?)", (tid, scene, graph, change, "cicd" if change else "manual", "done", ts))
        conn.execute("INSERT INTO snapshot(task_id, upstream_model, entry_config, traffic_share) "
                     "SELECT ?, ?, entry_config, traffic_share FROM scene WHERE id = ?",
                     (tid, "rank_v7", scene))
        conn.execute("INSERT INTO report(task_id, diff_rate, p99, avg, verdict, reasons) VALUES (?,?,?,?,?,?)",
                     (tid, diff, p99, round(p99 / 1.9, 1), "pass" if diff < 0.01 else "fail", "[]"))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed()
    print("seeded ->", )
