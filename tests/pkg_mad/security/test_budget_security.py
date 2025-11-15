import unittest

from freemad import Redactor
from freemad import enforce_size, BudgetGuard, truncate_to_tokens


class TestSecurityBudget(unittest.TestCase):
    def test_redaction(self):
        r = Redactor([r"sk-[A-Za-z0-9_\-]+"])
        s = "here sk-ABC123 and more"
        out = r.redact(s)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("sk-ABC123", out)

    def test_enforce_size(self):
        text = "x" * 10
        out, truncated = enforce_size(text, max_size=5, label="solution")
        self.assertTrue(truncated)
        self.assertTrue(out.endswith("solution]"))
        self.assertTrue(out.startswith("x" * 5))

    def test_budget_guard(self):
        guard = BudgetGuard(max_total_time_sec=0.05, max_round_time_sec=0.05)
        guard.check_total()
        rs = guard.round_start()
        guard.check_round(rs)

    def test_truncate_to_tokens_cap(self):
        text = "abcd" * 100  # ~100 tokens by 4-char heuristic
        cap = 10
        out, truncated = truncate_to_tokens(text, max_tokens=cap, label="prompt")
        self.assertTrue(truncated)
        # Ensure main body trimmed near token cap (pre-marker length)
        pre = out.split("[TRUNCATED")[0]
        self.assertLessEqual(len(pre), cap * 4 + 2)  # includes two newlines before marker


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
