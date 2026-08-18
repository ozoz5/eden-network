"""Verifier test suite for the generated code-fix family (code-fix/2)."""
import unittest

from stats import mean, median, variance


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


class TestVariance(unittest.TestCase):
    def test_two_points(self):
        self.assertAlmostEqual(variance([1, 3]), 2.0)

    def test_constant(self):
        self.assertAlmostEqual(variance([2, 2, 2]), 0.0)

    def test_basic(self):
        self.assertAlmostEqual(variance([1, 2, 3, 4]), 5.0 / 3.0)

    def test_negatives(self):
        self.assertAlmostEqual(variance([-2, 2]), 8.0)


if __name__ == "__main__":
    unittest.main()
