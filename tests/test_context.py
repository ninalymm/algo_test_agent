"""上下文聚合：共享图、DiD、可比性。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context import assembler, graph_scene
from store.db import connect
from store.seed import seed


class TestContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.conn = connect()

    def test_shared_graph_detected(self):
        self.assertTrue(graph_scene.is_shared(self.conn, "1000001"))
        self.assertFalse(graph_scene.is_shared(self.conn, "1000002"))

    def test_expand_scenes(self):
        r = graph_scene.expand_scenes(self.conn, "1000001")
        self.assertTrue(r["shared"])
        self.assertEqual(len(r["scenes"]), 2)

    def test_build_context(self):
        ctx = assembler.build_context(self.conn, "T-005")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["graph"]["id"], "1000001")
        self.assertIn("20260301-0002", ctx["graph"]["sibling_scenes"])

    def test_did_detects_degradation(self):
        r = assembler.did_for_task(self.conn, "T-005")
        self.assertTrue(r["ok"])
        self.assertGreater(r["net"], 1.0)          # 净影响约 +1.65ms
        self.assertEqual(r["verdict"], "显著劣化")

    def test_did_without_change(self):
        r = assembler.did_for_task(self.conn, "T-001")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
