import unittest

from freemad import parse_generation, parse_critique
from freemad import Decision
from freemad import canonicalize_solution, compute_answer_id


class TestParser(unittest.TestCase):
    def test_generation_ok(self):
        raw = """
SOLUTION:
print('hi')

REASONING:
Simple.
"""
        res = parse_generation(raw)
        self.assertFalse(res.needs_retry)
        self.assertEqual(res.solution.strip(), "print('hi')")
        self.assertEqual(res.reasoning.strip(), "Simple.")

    def test_generation_case_tolerance(self):
        raw = """
SoLuTiOn: answer

ReAsOnInG: why
"""
        res = parse_generation(raw)
        self.assertFalse(res.needs_retry)
        self.assertEqual(res.solution, "answer")
        self.assertEqual(res.reasoning, "why")

    def test_generation_missing_section(self):
        raw = """
SOLUTION: only one
"""
        res = parse_generation(raw)
        self.assertTrue(res.needs_retry)
        self.assertIn("missing REASONING",
                      ",".join(res.errors))

    def test_critique_keep_ok(self):
        raw = """
DECISION: KEEP

REASONING: solid
"""
        res = parse_critique(raw)
        self.assertFalse(res.needs_retry)
        self.assertEqual(res.decision, Decision.KEEP)
        self.assertIsNone(res.solution)
        self.assertEqual(res.reasoning, "solid")

    def test_critique_revise_ok(self):
        raw = """
DECISION: REVISE

REVISED_SOLUTION:
print(42)

REASONING: bug fix
"""
        res = parse_critique(raw)
        self.assertFalse(res.needs_retry)
        self.assertEqual(res.decision, Decision.REVISE)
        self.assertEqual(res.solution.strip() if res.solution else "", "print(42)")

    def test_critique_missing_decision(self):
        raw = """
REVISED_SOLUTION: x
REASONING: y
"""
        res = parse_critique(raw)
        self.assertTrue(res.needs_retry)
        self.assertIn("missing or invalid DECISION", ",".join(res.errors))

    def test_critique_revise_needs_solution(self):
        raw = """
DECISION: REVISE
REASONING: will change
"""
        res = parse_critique(raw)
        self.assertTrue(res.needs_retry)
        self.assertIn("REVISED_SOLUTION required", ",".join(res.errors))


class TestCanonicalization(unittest.TestCase):
    def test_eol_and_trim(self):
        s1 = "a\r\nb\n"
        s2 = "a\nb"
        self.assertEqual(canonicalize_solution(s1), canonicalize_solution(s2))
        self.assertEqual(compute_answer_id(s1), compute_answer_id(s2))

    def test_code_fence_extraction(self):
        raw = """
Here is code:
```python
print('A')
```
And more:
```js
console.log('B')
```
"""
        canon = canonicalize_solution(raw)
        self.assertIn("print('A')", canon)
        self.assertIn("console.log('B')", canon)
        # Ensure IDs stable
        self.assertEqual(compute_answer_id(raw), compute_answer_id("""
```python
print('A')
```

```js
console.log('B')
```
"""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
