"""Tests for the cultural layer: determinism, rarity, constitutional shape."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ore


class TestOre(unittest.TestCase):
    def test_discovery_is_deterministic(self):
        self.assertEqual(ore.discover("abc", "seed"), ore.discover("abc", "seed"))

    def test_leading_zero_bits(self):
        self.assertEqual(ore.leading_zero_bits("ffff"), 0)
        self.assertEqual(ore.leading_zero_bits("7fff"), 1)
        self.assertEqual(ore.leading_zero_bits("0fff"), 4)
        self.assertEqual(ore.leading_zero_bits("00ff"), 8)
        self.assertEqual(ore.leading_zero_bits("001f"), 11)

    def test_tiers(self):
        self.assertIsNone(ore.tier_of(5))
        self.assertEqual(ore.tier_of(6), "SPARK")
        self.assertEqual(ore.tier_of(10), "VEIN")
        self.assertEqual(ore.tier_of(14), "GEM")
        self.assertEqual(ore.tier_of(18), "VOID")
        self.assertEqual(ore.tier_of(64), "VOID")

    def test_constitutional_shape(self):
        # ORE returns only (hash, bits, tier) — no economic fields, ever.
        result = ore.discover("r", "s")
        self.assertEqual(len(result), 3)
        # and the cultural layer must not import the issuance gate
        self.assertNotIn("eligibility", sys.modules.get("ore").__dict__)


if __name__ == "__main__":
    unittest.main()
