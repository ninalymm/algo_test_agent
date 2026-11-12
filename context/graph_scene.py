"""场景 ↔ 图 的双向索引（含共享图识别）。"""

from __future__ import annotations

from store import repo


def scenes_of(conn, graph_id: str) -> list[dict]:
    return repo.scenes_of_graph(conn, graph_id)


def graph_of(conn, scene_id: str) -> dict | None:
    return repo.graph_of_scene(conn, scene_id)


def is_shared(conn, graph_id: str) -> bool:
    return repo.is_shared_graph(conn, graph_id)


def expand_scenes(conn, graph_id: str) -> dict:
    """给定图，返回该跑的场景清单 + 是否共享图。"""
    scenes = scenes_of(conn, graph_id)
    return {
        "graph_id": graph_id,
        "scenes": [s["id"] for s in scenes],
        "shared": len(scenes) > 1,
        "reason": "共享图：一次改动影响多个场景，需全量验证" if len(scenes) > 1 else "独占图：单场景验证",
    }
