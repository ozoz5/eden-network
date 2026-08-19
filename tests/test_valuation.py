"""Cross-family valuation: comparing the schemes, not choosing one yet."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import valuation


def _mint(mid, fam, gain, prev, new):
    return {"mint_id": mid, "family_id": fam, "gain_j": gain,
            "prev_j": prev, "new_j": new, "winner": "w"}


class TestSchemes(unittest.TestCase):
    """Two families: one frugal with a huge proportional win, one wasteful
    with a modest one. This is the whole problem in four rows."""

    MINTS = [
        _mint(1, "frugal", 5.2, 5.68, 0.148),     # 38x cheaper, tiny joules
        _mint(2, "wasteful", 310.0, 391.0, 81.0),  # 4.8x cheaper, big joules
    ]
    CONTEXT = {"family_receipts": {"frugal": 20, "wasteful": 60}}

    def test_every_scheme_normalises_to_one(self):
        for scheme, values in valuation.evaluate(self.MINTS,
                                                 self.CONTEXT).items():
            with self.subTest(scheme):
                self.assertAlmostEqual(sum(values.values()), 1.0, places=9)

    def test_physical_pays_the_smaller_improvement_more(self):
        """The finding that makes this an open problem: joules saved and
        intelligence shown can point in opposite directions."""
        share = valuation.evaluate(self.MINTS, self.CONTEXT)["physical"]
        self.assertGreater(share[2], share[1])   # 4.8x paid more than 38x

    def test_ratio_follows_the_improvement_instead(self):
        share = valuation.evaluate(self.MINTS, self.CONTEXT)["ratio"]
        self.assertGreater(share[1], share[2])   # 38x paid more than 4.8x

    def test_budget_splits_families_evenly(self):
        shares = valuation.family_shares(
            valuation.evaluate(self.MINTS, self.CONTEXT), self.MINTS)
        self.assertAlmostEqual(shares["budget"]["frugal"],
                               shares["budget"]["wasteful"], places=9)

    def test_demand_amplifies_the_busier_family(self):
        physical = valuation.evaluate(self.MINTS, self.CONTEXT)["physical"]
        demand = valuation.evaluate(self.MINTS, self.CONTEXT)["demand"]
        self.assertGreater(demand[2], physical[2])

    def test_no_gain_mints_nothing_under_ratio(self):
        flat = [_mint(1, "f", 0.0, 10.0, 10.0)]
        self.assertEqual(
            valuation.ratio(flat, {"family_receipts": {}})[1], 0.0)

    def test_salt_the_mine_is_priced_by_two_schemes_and_not_the_others(self):
        """Staging the same improvement in a 100x more wasteful arena pays
        100x under joules-saved, and nothing extra under the scale-free
        schemes. This is the spec's §6.11 incentive, as arithmetic."""
        adv = valuation.salt_the_mine_advantage(5.0, 100.0)
        self.assertAlmostEqual(adv["physical"], 100.0)
        self.assertAlmostEqual(adv["demand"], 100.0)
        self.assertAlmostEqual(adv["budget"], 1.0)
        self.assertAlmostEqual(adv["ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
