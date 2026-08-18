"""Tests for the issuance gate. Every rule that mints CREDIT is tested here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eligibility


def _group(runner="r", meter="m", n=5, mean=10.0, sigma=0.05,
           verify_mean=0.2):
    half = eligibility.K_SIGMA * sigma / (n ** 0.5) if n >= 3 \
        else eligibility.K_SIGMA * sigma
    return {
        "group": f"{runner}@{meter}", "runner": runner, "meter": meter,
        "code_hash": "cafe01", "meter_class": eligibility.meter_class(meter),
        "n": n, "mean": mean, "sigma": sigma,
        "low": max(0.0, mean - half), "high": mean + half,
        "verify_mean": verify_mean,
    }


class TestMeterClass(unittest.TestCase):
    def test_powermetrics_is_level_v(self):
        self.assertEqual(eligibility.meter_class("powermetrics-package-v1"), "V")

    def test_unknown_meters_default_to_s(self):
        self.assertEqual(eligibility.meter_class("estimated-cpu-v1"), "S")
        self.assertEqual(eligibility.meter_class("estimated-cpu-pmfallback-v1"), "S")


class TestRecordEligibility(unittest.TestCase):
    def test_min_replications_required(self):
        self.assertFalse(eligibility.assess_record(_group(n=2))["eligible"])
        self.assertTrue(eligibility.assess_record(_group(n=3))["eligible"])

    def test_pending_checks_always_reported(self):
        rep = eligibility.assess_record(_group())
        self.assertIn("challenge-sampling", rep["pending"])
        self.assertIn("independent-replication", rep["pending"])
        self.assertIn("challenge-audit", rep["pending"])


class TestTransition(unittest.TestCase):
    def test_cross_meter_never_certifiable(self):
        v = eligibility.assess_transition(
            _group(meter="powermetrics-package-v1", mean=100.0),
            _group(meter="estimated-cpu-v1", mean=2.0))
        self.assertFalse(v["certifiable"])

    def test_interval_overlap_not_certified(self):
        v = eligibility.assess_transition(
            _group(mean=10.0, sigma=0.5), _group(mean=9.8, sigma=0.5))
        self.assertFalse(v["certifiable"])

    def test_clean_dominance_mints_net_of_verification(self):
        holder = _group(mean=10.0)
        cand = _group(mean=5.0, verify_mean=0.2)
        v = eligibility.assess_transition(holder, cand)
        self.assertTrue(v["certifiable"])
        self.assertTrue(v["mintable"])
        self.assertAlmostEqual(
            v["gain"], holder["low"] - cand["high"] - 0.2, places=6)

    def test_rho_gate_blocks_mint_but_not_record(self):
        holder = _group(mean=10.0)
        cand = _group(mean=1.0, verify_mean=1.9)  # rho = 1.9 > 1.0
        v = eligibility.assess_transition(holder, cand)
        self.assertTrue(v["certifiable"])   # record still changes hands
        self.assertFalse(v["mintable"])     # but nothing is issued
        self.assertTrue(any("rho" in r for r in v["mint_reasons"]))

    def test_zero_net_gain_blocks_mint(self):
        holder = _group(mean=10.0)
        cand = _group(mean=9.0, sigma=0.01, verify_mean=5.0)
        v = eligibility.assess_transition(holder, cand)
        self.assertTrue(v["certifiable"])
        self.assertFalse(v["mintable"])

    def test_under_replicated_challenger_rejected(self):
        v = eligibility.assess_transition(_group(mean=10.0), _group(mean=5.0, n=2))
        self.assertFalse(v["certifiable"])


if __name__ == "__main__":
    unittest.main()
