import unittest

from freemad import TokenBudget, BudgetExceeded


class TestTokenBudget(unittest.TestCase):
    def test_accumulates_without_enforcement(self):
        tb = TokenBudget(max_total_tokens=10, enforce=False)
        tb.add(3)
        tb.add(4)
        self.assertEqual(tb.used, 7)
        tb.add(10)
        self.assertEqual(tb.used, 17)

    def test_enforcement_raises(self):
        tb = TokenBudget(max_total_tokens=5, enforce=True)
        tb.add(3)
        with self.assertRaises(BudgetExceeded):
            tb.add(3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
