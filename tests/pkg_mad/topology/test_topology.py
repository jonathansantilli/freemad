import unittest

from freemad import load_config
from freemad import build_topology


class TestTopology(unittest.TestCase):
    def test_all_to_all_two_agents(self):
        cfg = load_config()
        t = build_topology(cfg)
        peers = t.assign_peers(["claude", "codex"])
        self.assertEqual(peers["claude"], ["codex"])
        self.assertEqual(peers["codex"], ["claude"])
        self.assertEqual(t.info()["type"], "all_to_all")

    def test_k_reviewers_deterministic(self):
        cfg = load_config(overrides={"topology": {"type": "k_reviewers", "k": 1, "seed": 42}})
        t1 = build_topology(cfg)
        t2 = build_topology(cfg)
        ids = ["a", "b", "c", "d"]
        p1 = t1.assign_peers(ids)
        p2 = t2.assign_peers(ids)
        self.assertEqual(p1, p2)
        # each has exactly 1 peer and not itself
        for a in ids:
            self.assertEqual(len(p1[a]), 1)
            self.assertNotIn(a, p1[a])

    def test_ring(self):
        cfg = load_config(overrides={"topology": {"type": "ring"}})
        t = build_topology(cfg)
        ids = ["a", "b", "c"]
        peers = t.assign_peers(ids)
        self.assertEqual(peers["a"], ["b"])
        self.assertEqual(peers["b"], ["c"])
        self.assertEqual(peers["c"], ["a"])

    def test_star(self):
        cfg = load_config(overrides={
            "agents": [
                {"id": "a", "type": "claude_code"},
                {"id": "b", "type": "openai_codex"},
                {"id": "c", "type": "openai_codex"},
            ],
            "topology": {"type": "star", "hub_agent": "a"},
        })
        t = build_topology(cfg)
        ids = ["a", "b", "c"]
        peers = t.assign_peers(ids)
        self.assertEqual(set(peers["a"]), {"b", "c"})
        self.assertEqual(peers["b"], ["a"])
        self.assertEqual(peers["c"], ["a"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
