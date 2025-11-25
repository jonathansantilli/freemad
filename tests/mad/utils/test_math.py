from __future__ import annotations

import unittest

from freemad.utils.math import fibonacci


class TestFibonacci(unittest.TestCase):
    def test_first_terms(self) -> None:
        self.assertEqual(fibonacci(0), 0)
        self.assertEqual(fibonacci(1), 1)
        self.assertEqual(fibonacci(2), 1)
        self.assertEqual(fibonacci(3), 2)
        self.assertEqual(fibonacci(7), 13)

    def test_sequence_matches_lookup(self) -> None:
        expected = [0, 1, 1, 2, 3, 5, 8, 13, 21]
        actual = [fibonacci(idx) for idx in range(len(expected))]
        self.assertEqual(actual, expected)

    def test_negative_index_raises(self) -> None:
        with self.assertRaises(ValueError):
            fibonacci(-1)
