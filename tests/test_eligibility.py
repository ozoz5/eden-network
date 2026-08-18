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


def _cert(runner="r", meter="m", rate_k=5, n=6, jps=10.0, verify=0.5):
    successes = rate_k
    run_j = jps * successes - verify if successes else 1.0
    return eligibility.distribution_cert(
        "e" * 16, "fam", runner, "cafe01", meter, n, n, successes,
        max(run_j, 0.0), verify)


class TestDistributionCerts(unittest.TestCase):
    def test_jps_includes_verification(self):
        c = eligibility.distribution_cert("e" * 16, "f", "r", "c", "m",
                                          6, 6, 3, run_j=27.0, verify_j=3.0)
        self.assertAlmostEqual(c["j_per_success"], 10.0)

    def test_zero_successes_is_infinite(self):
        c = eligibility.distribution_cert("e" * 16, "f", "r", "c", "m",
                                          6, 6, 0, 1.0, 0.1)
        self.assertEqual(c["j_per_success"], float("inf"))

    def test_wilson_bounds(self):
        lo, hi = eligibility.wilson_interval(6, 6)
        self.assertLess(lo, 1.0)      # 6/6 is not certainty
        self.assertAlmostEqual(hi, 1.0)
        lo0, hi0 = eligibility.wilson_interval(0, 6)
        self.assertEqual(lo0, 0.0)
        self.assertGreater(hi0, 0.0)  # 0/6 does not prove impossibility

    def test_pareto_three_survivors_and_domination(self):
        # GPT's example: A(100%,20) B(95%,10) C(60%,2) all survive;
        # D(96%,8) then dominates exactly B.
        def mk(runner, successes, jps):
            c = _cert(runner=runner, rate_k=successes, n=100, jps=jps)
            return c
        a = eligibility.distribution_cert("e"*16, "f", "A", "h", "m", 100, 100, 100, 2000.0, 0.0)
        b = eligibility.distribution_cert("e"*16, "f", "B", "h", "m", 100, 100, 95, 950.0, 0.0)
        c = eligibility.distribution_cert("e"*16, "f", "C", "h", "m", 100, 100, 60, 120.0, 0.0)
        self.assertEqual(len(eligibility.pareto_frontier([a, b, c])), 3)
        d = eligibility.distribution_cert("e"*16, "f", "D", "h", "m", 100, 100, 96, 768.0, 0.0)
        self.assertTrue(eligibility.dominates(d, b))
        self.assertFalse(eligibility.dominates(d, a))
        self.assertFalse(eligibility.dominates(d, c))
        front = eligibility.pareto_frontier([a, b, c, d])
        self.assertEqual({x["runner"] for x in front}, {"A", "C", "D"})

    def test_cross_meter_certs_never_dominate(self):
        a = eligibility.distribution_cert("e"*16, "f", "A", "h", "m1", 6, 6, 6, 6.0, 0.0)
        b = eligibility.distribution_cert("e"*16, "f", "B", "h", "m2", 6, 6, 1, 600.0, 0.0)
        self.assertFalse(eligibility.dominates(a, b))

    def test_insertion_mints_only_on_finite_domination(self):
        a = eligibility.distribution_cert("e"*16, "f", "A", "h", "m", 6, 6, 6, 60.0, 0.0)
        v_genesis = eligibility.assess_cert_insertion([], a)
        self.assertFalse(v_genesis["mintable"])  # genesis mints nothing
        better = eligibility.distribution_cert("e"*16, "f", "B", "h", "m", 6, 6, 6, 30.0, 0.0)
        v = eligibility.assess_cert_insertion([a], better)
        self.assertTrue(v["mintable"])
        self.assertAlmostEqual(v["gain"], 5.0)  # 10 J/s -> 5 J/s
        zero = eligibility.distribution_cert("e"*16, "f", "Z", "h", "m", 6, 6, 0, 0.5, 0.0)
        v2 = eligibility.assess_cert_insertion([zero], a)
        self.assertFalse(v2["mintable"])  # dominating an inf cert prices nothing

    def test_small_epoch_not_eligible(self):
        small = eligibility.distribution_cert("e"*16, "f", "A", "h", "m", 3, 3, 3, 3.0, 0.0)
        self.assertFalse(eligibility.assess_cert_insertion([], small)["eligible"])


if __name__ == "__main__":
    unittest.main()
