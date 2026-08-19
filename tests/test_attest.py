"""Meter coherence: what a receipt can prove about itself, and what it cannot."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eden

OS_COUNTER = {
    "run_energy": {"cpu_seconds": 0.96, "wall_seconds": 1.0,
                   "energy_joules": 9.2548},
    "measurement_profile": {"method": "os-counter",
                            "mean_active_mw": 12456.8,
                            "mean_idle_mw": 3202.0},
}
ESTIMATED = {
    "run_energy": {"cpu_seconds": 0.5, "wall_seconds": 0.5,
                   "energy_joules": 3.0},
    "measurement_profile": {"method": "estimated",
                            "watts_per_cpu_second_assumed": 6.0},
}


def _mutate(base, fn):
    r = json.loads(json.dumps(base))
    fn(r)
    return r


class TestMeterCoherence(unittest.TestCase):
    def test_honest_receipts_are_coherent(self):
        for name, rec in (("os-counter", OS_COUNTER), ("estimated", ESTIMATED)):
            with self.subTest(name):
                self.assertEqual(eden.meter_coherence(rec)[0], "coherent")

    def test_energy_understated_is_caught(self):
        bad = _mutate(OS_COUNTER, lambda r: r["run_energy"].update(
            energy_joules=r["run_energy"]["energy_joules"] / 100))
        self.assertEqual(eden.meter_coherence(bad)[0], "incoherent")

    def test_stretched_wall_time_is_caught(self):
        bad = _mutate(OS_COUNTER, lambda r: r["run_energy"].update(
            wall_seconds=r["run_energy"]["wall_seconds"] * 10))
        self.assertEqual(eden.meter_coherence(bad)[0], "incoherent")

    def test_idle_above_active_is_caught(self):
        bad = _mutate(OS_COUNTER, lambda r: r["measurement_profile"].update(
            mean_idle_mw=99999.0))
        self.assertEqual(eden.meter_coherence(bad)[0], "incoherent")

    def test_negative_energy_is_caught(self):
        bad = _mutate(ESTIMATED,
                      lambda r: r["run_energy"].update(energy_joules=-1.0))
        self.assertEqual(eden.meter_coherence(bad)[0], "incoherent")

    def test_assumed_watts_must_match_exactly(self):
        bad = _mutate(ESTIMATED, lambda r: r["run_energy"].update(
            energy_joules=2.9))
        self.assertEqual(eden.meter_coherence(bad)[0], "incoherent")

    def test_unknown_method_is_not_claimed_as_proof(self):
        odd = _mutate(ESTIMATED,
                      lambda r: r["measurement_profile"].update(method="oracle"))
        self.assertEqual(eden.meter_coherence(odd)[0], "unknown")

    def test_a_lie_kept_consistent_passes(self):
        """The honest limit of this check, pinned so nobody mistakes it for
        attestation: halve the power and the energy together and the receipt
        still agrees with itself. Catching that needs a meter EDEN does not
        own."""
        liar = _mutate(OS_COUNTER, lambda r: (
            r["measurement_profile"].update(
                mean_active_mw=(r["measurement_profile"]["mean_idle_mw"]
                                + (r["measurement_profile"]["mean_active_mw"]
                                   - r["measurement_profile"]["mean_idle_mw"]) / 2)),
            r["run_energy"].update(
                energy_joules=r["run_energy"]["energy_joules"] / 2)))
        self.assertEqual(eden.meter_coherence(liar)[0], "coherent")

    def test_rounding_in_older_profiles_is_tolerated(self):
        """Older receipts stored mean power to one decimal; the derivation
        must allow exactly that much drift and no more."""
        rounded = _mutate(OS_COUNTER, lambda r: r["run_energy"].update(
            energy_joules=9.25476))     # within the rounding band
        self.assertEqual(eden.meter_coherence(rounded)[0], "coherent")
        beyond = _mutate(OS_COUNTER, lambda r: r["run_energy"].update(
            energy_joules=9.2548 + 0.01))
        self.assertEqual(eden.meter_coherence(beyond)[0], "incoherent")

    def test_incoherent_receipts_cannot_be_priced(self):
        self.assertFalse(eden._admits_to_frontier("SIGNED", "run1",
                                                  "incoherent"))
        self.assertTrue(eden._admits_to_frontier("SIGNED", "run1", "coherent"))


if __name__ == "__main__":
    unittest.main()
