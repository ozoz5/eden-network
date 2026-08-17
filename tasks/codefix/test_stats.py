"""Verifier test suite for the code-fix family. 12 tests must pass."""
import unittest

from stats import mean, median


class TestMean(unittest.TestCase):
    def test_ints(self):
        self.assertAlmostEqual(mean([1, 2, 3, 4]), 2.5)

    def test_single(self):
        self.assertAlmostEqual(mean([7]), 7.0)

    def test_negative(self):
        self.assertAlmostEqual(mean([-3, 3]), 0.0)

    def test_floats(self):
        self.assertAlmostEqual(mean([0.5, 1.5]), 1.0)


class TestMedian(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_even_basic(self):
        self.assertAlmostEqual(median([1, 2, 3, 4]), 2.5)

    def test_two_elements(self):
        self.assertAlmostEqual(median([1, 3]), 2.0)

    def test_unsorted_even(self):
        self.assertAlmostEqual(median([9, 1, 5, 3]), 4.0)

    def test_negatives_even(self):
        self.assertAlmostEqual(median([-4, -1, -3, -2]), -2.5)

    def test_floats_even(self):
        self.assertAlmostEqual(median([0.5, 1.5, 2.5, 3.5]), 2.0)

    def test_single(self):
        self.assertEqual(median([42]), 42)

    def test_duplicates_even(self):
        self.assertAlmostEqual(median([2, 2, 2, 8]), 2.0)


if __name__ == "__main__":
    unittest.main()
