import unittest

from freemad import load_config
from freemad import ScoreTracker


class TestScoreTracker(unittest.TestCase):
    def test_initial_and_keep(self):
        cfg = load_config()
        st = ScoreTracker(cfg)
        # Round 0 initial
        st.record_initial(agent_id="a1", answer_id="X", round_idx=0)
        raw = st.get_raw_scores()
        self.assertAlmostEqual(raw["X"], cfg.scoring.weights[0])

        # Round 1 keep
        st.record_keep(agent_id="a1", answer_id="X", round_idx=1)
        f = 1 / (1 + 1)
        self.assertAlmostEqual(st.get_raw_scores()["X"], cfg.scoring.weights[0] + cfg.scoring.weights[3] * f)

        # Normalized by contributors (still 1)
        self.assertAlmostEqual(st.get_all_scores()["X"], st.get_raw_scores()["X"])  # one contributor

    def test_change_and_contributor_normalization(self):
        cfg = load_config()
        st = ScoreTracker(cfg)
        # Two agents start with X and Y
        st.record_initial(agent_id="a1", answer_id="X", round_idx=0)
        st.record_initial(agent_id="a2", answer_id="Y", round_idx=0)

        # Round 1: a2 switches to X (adopts X)
        st.record_change(agent_id="a2", old_answer_id="Y", new_answer_id="X", round_idx=1)

        raw = st.get_raw_scores()
        f1 = 1 / (1 + 1)
        self.assertAlmostEqual(raw["Y"], cfg.scoring.weights[0] - cfg.scoring.weights[1] * f1)
        self.assertAlmostEqual(raw["X"], cfg.scoring.weights[0] + cfg.scoring.weights[2] * f1)

        # Now X has two contributors (a1 and a2) → normalized score halves
        norm = st.get_all_scores()
        self.assertAlmostEqual(norm["X"], raw["X"] / 2)
        # Y has one contributor (a2 did not count as contributor anymore for Y)
        self.assertAlmostEqual(norm["Y"], raw["Y"])  # contributors count is 1

    def test_explain_history(self):
        cfg = load_config()
        st = ScoreTracker(cfg)
        st.record_initial(agent_id="a1", answer_id="X", round_idx=0)
        st.record_keep(agent_id="a1", answer_id="X", round_idx=1)
        hist = st.explain_score("X")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0].action, "initial")
        self.assertEqual(hist[1].action, "keep")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
