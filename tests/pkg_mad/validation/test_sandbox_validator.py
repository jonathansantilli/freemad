import unittest

from freemad import SandboxValidator


class TestSandboxValidator(unittest.TestCase):
    def test_disabled_returns_neutral(self):
        sv = SandboxValidator(enabled=False, timeout_ms=200)
        res = sv.validate("A", "print('ok')")
        self.assertTrue(res.passed)
        self.assertAlmostEqual(res.confidence, 0.5, places=2)

    def test_enabled_runs_code(self):
        sv = SandboxValidator(enabled=True, timeout_ms=500)
        res = sv.validate("A", "print('ok')")
        self.assertTrue(res.passed)
        self.assertGreaterEqual(res.confidence, 0.7)

    def test_enabled_runtime_error(self):
        sv = SandboxValidator(enabled=True, timeout_ms=500)
        res = sv.validate("A", "raise ValueError('boom')")
        self.assertFalse(res.passed)
        self.assertIn("runtime:", " ".join(res.errors))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
