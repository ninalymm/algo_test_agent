"""LangGraph 版本的 run 链路（未安装 langgraph 时自动跳过）。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills import run_graph
from store.db import connect, init_db
from store.seed import seed

HAS_LG = run_graph.available()


@unittest.skipUnless(HAS_LG, "未安装 langgraph，跳过图版本测试")
class TestRunGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()
        init_db(cls.conn)

    def test_multi_turn_flow(self):
        tid = "g-test-1"
        run_graph.reset(self.conn, tid)

        r1 = run_graph.handle(self.conn, "帮我跑一下", tid)
        self.assertEqual(r1["card"]["type"], "ask")
        self.assertTrue(run_graph.pending(self.conn, tid))

        r2 = run_graph.handle(self.conn, "20260301-0001", tid)
        self.assertEqual(r2["card"]["type"], "ask")

        r3 = run_graph.handle(self.conn, "只跑压测", tid)
        self.assertEqual(r3["card"]["type"], "confirm")

        r4 = run_graph.handle(self.conn, "确认执行", tid)
        self.assertEqual(r4["card"]["type"], "verdict")
        self.assertFalse(run_graph.pending(self.conn, tid))

    def test_cancel_clears_state(self):
        tid = "g-test-2"
        run_graph.reset(self.conn, tid)
        run_graph.handle(self.conn, "帮我跑一下", tid)
        r = run_graph.handle(self.conn, "算了", tid)
        self.assertIsNone(r["card"])
        self.assertFalse(run_graph.pending(self.conn, tid))

    def test_state_persists_across_handles(self):
        """checkpointer 让状态跨调用存活，不需要外部 session 字典。"""
        tid = "g-test-3"
        run_graph.reset(self.conn, tid)
        run_graph.handle(self.conn, "帮我跑一下", tid)
        run_graph.handle(self.conn, "20260301-0001", tid)
        # 第三次不提供场景，靠 checkpointer 里的状态
        r = run_graph.handle(self.conn, "跑 diff", tid)
        self.assertEqual(r["card"]["type"], "confirm")

    def test_new_scene_is_recognized_without_restart(self):
        """场景列表每轮现查，不再在图构建时固化。"""
        new_scene = "20260401-0001"
        self.conn.execute(
            "INSERT INTO scene(id, app_id, name, entry_config, traffic_share) VALUES (?,?,?,?,?)",
            (new_scene, "foxcontent", "新增场景", "首页", 0.1))
        self.conn.commit()
        self.addCleanup(self._delete_scene, new_scene)

        # 先跑一轮，确保图已被构建/使用过
        run_graph.reset(self.conn, "g-test-new-0")
        run_graph.handle(self.conn, "帮我跑一下", "g-test-new-0")

        run_graph.reset(self.conn, "g-test-new-1")
        r = run_graph.handle(self.conn, f"{new_scene} 只跑压测", "g-test-new-1")
        self.assertEqual(r["card"]["type"], "confirm")
        self.assertTrue(any(new_scene in line for line in r["card"]["lines"]))

    def _delete_scene(self, scene_id: str) -> None:
        self.conn.execute("DELETE FROM scene WHERE id = ?", (scene_id,))
        self.conn.commit()

    def test_type_can_be_answered_by_ordinal(self):
        """确认卡上的选项支持回序号，与手写版行为一致。"""
        tid = "g-test-4"
        run_graph.reset(self.conn, tid)
        run_graph.handle(self.conn, "帮我跑一下", tid)
        run_graph.handle(self.conn, "20260301-0001", tid)
        r = run_graph.handle(self.conn, "3", tid)      # 第 3 项 = 两个都跑
        self.assertEqual(r["card"]["type"], "confirm")
        self.assertTrue(any("diff" in line for line in r["card"]["lines"]))
        self.assertFalse(any("未指定类型" in line for line in r["card"]["lines"]))


class TestRouterFallback(unittest.TestCase):
    """图版本抛错时要降级到手写链路，而不是把异常丢给用户。"""

    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()
        init_db(cls.conn)

    def test_graph_failure_falls_back_to_manual_flow(self):
        from skills import router
        with patch.object(run_graph, "available", return_value=True), \
                patch.object(run_graph, "pending", return_value=False), \
                patch.object(run_graph, "handle", side_effect=RuntimeError("boom")), \
                patch.object(run_graph, "reset", return_value=None):
            r = router.route(self.conn, "帮我跑一下 20260301-0001 的压测", {}, "t-fallback")
        self.assertEqual(r["intent"], "run")
        self.assertEqual(r["card"]["type"], "confirm")


class TestFallback(unittest.TestCase):
    def test_available_flag_is_boolean(self):
        self.assertIsInstance(run_graph.available(), bool)


if __name__ == "__main__":
    unittest.main()
