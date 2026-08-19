"""Self-verification for EDEN's core statistics and accounting logic.

A protocol that certifies other people's results must certify its own code
(Constitution II applied to ourselves). Run: python3 -m unittest discover tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eden


def _receipt(runner, meter, energy, verify=0.2, cv=0.15, code="cafe01"):
    return json.dumps({
        "runner_id": runner, "meter_id": meter, "runner_code_hash": code,
        "run_energy": {"energy_joules": energy},
        "verification_energy": {"energy_joules": verify},
        "uncertainty_profile": {"assigned_cv": cv},
    })


class TempLedger:
    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._old = eden.DB_PATH
        eden.DB_PATH = Path(self._dir.name) / "test.db"
        self.conn = eden.db()
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        eden.DB_PATH = self._old
        self._dir.cleanup()


def _insert(conn, fam, rows):
    for i, r in enumerate(rows):
        conn.execute("INSERT INTO receipts(receipt_id, run_id, family_id, "
                     "receipt_json, receipt_hash, created_at) VALUES (?,?,?,?,?,?)",
                     (f"r{fam}{i}", f"run{fam}{i}", fam, r, f"r{fam}{i}", "t"))
    conn.commit()


class TestParseCputime(unittest.TestCase):
    def test_mm_ss(self):
        self.assertAlmostEqual(eden._parse_cputime("01:30.50"), 90.5)

    def test_hh_mm_ss(self):
        self.assertAlmostEqual(eden._parse_cputime("2:03:04"), 7384.0)

    def test_days(self):
        self.assertAlmostEqual(eden._parse_cputime("1-00:00:10"), 86410.0)


class TestForbiddenKeys(unittest.TestCase):
    def test_clean_receipt_passes(self):
        eden._check_forbidden({"run_energy": {"energy_joules": 1.0}})

    def test_forbidden_key_raises(self):
        with self.assertRaises(ValueError):
            eden._check_forbidden({"run_energy": {"baseline": 1.0}})

    def test_forbidden_key_nested_in_list_raises(self):
        with self.assertRaises(ValueError):
            eden._check_forbidden({"a": [{"saved": 1}]})

    def test_forbidden_word_as_value_is_legal(self):
        # Audit fix regression: substring matching used to crash on this.
        eden._check_forbidden({"runner_id": "baseline", "note": "mint condition"})


class TestGroupStats(unittest.TestCase):
    def test_meters_never_share_a_group(self):
        with TempLedger() as conn:
            _insert(conn, "fam", [
                _receipt("r1", "estimated-cpu-v1", 5.0),
                _receipt("r1", "powermetrics-package-v1", 9.0),
            ])
            groups = eden.group_stats(conn, "fam")
            self.assertEqual(len(groups), 2)

    def test_hardware_never_shares_a_group(self):
        # Same runner, same meter, different machine: separate sigma.
        import json as _json
        r1 = _json.loads(_receipt("r1", "m", 5.0))
        r2 = _json.loads(_receipt("r1", "m", 9.0))
        r1["hardware_profile"] = {"platform": "macOS-26.5.1-arm64", "machine": "arm64"}
        r2["hardware_profile"] = {"platform": "macOS-26.5.2-arm64", "machine": "arm64"}
        with TempLedger() as conn:
            _insert(conn, "fam", [_json.dumps(r1), _json.dumps(r2)])
            self.assertEqual(len(eden.group_stats(conn, "fam")), 2)

    def test_code_versions_never_share_a_group(self):
        # Same runner name, different implementation: no sigma inheritance.
        with TempLedger() as conn:
            _insert(conn, "fam", [
                _receipt("r1", "m", 5.0, code="aaaaaa"),
                _receipt("r1", "m", 4.9, code="bbbbbb"),
            ])
            groups = eden.group_stats(conn, "fam")
            self.assertEqual(len(groups), 2)

    def test_assigned_cv_does_not_shrink_with_n(self):
        with TempLedger() as conn:
            _insert(conn, "fam", [_receipt("r1", "m", 10.0, cv=0.10)] * 2)
            g = eden.group_stats(conn, "fam")[0]
            # n=2 -> systematic cv: half-width = K_SIGMA * cv * mean, no sqrt(n)
            self.assertAlmostEqual(g["high"] - g["mean"],
                                   eden.K_SIGMA * 0.10 * 10.0, places=6)

    def test_measured_sigma_shrinks_with_sqrt_n(self):
        with TempLedger() as conn:
            _insert(conn, "fam", [
                _receipt("r1", "m", 10.0), _receipt("r1", "m", 10.2),
                _receipt("r1", "m", 9.8), _receipt("r1", "m", 10.0),
            ])
            g = eden.group_stats(conn, "fam")[0]
            self.assertLess(g["high"] - g["mean"],
                            eden.K_SIGMA * g["sigma"])  # sqrt(4)=2 reduction

    def test_interval_lower_bound_clamped_at_zero(self):
        with TempLedger() as conn:
            _insert(conn, "fam", [_receipt("r1", "m", 1.0, cv=2.0)])
            g = eden.group_stats(conn, "fam")[0]
            self.assertGreaterEqual(g["low"], 0.0)

    def test_dominance_requires_interval_separation(self):
        with TempLedger() as conn:
            _insert(conn, "fam", [
                _receipt("slow", "m", 10.0), _receipt("slow", "m", 10.1),
                _receipt("slow", "m", 9.9),
                _receipt("fast", "m", 9.5), _receipt("fast", "m", 9.6),
                _receipt("fast", "m", 9.4),
            ])
            groups = eden.group_stats(conn, "fam")
            fast = next(g for g in groups if g["runner"] == "fast")
            slow = next(g for g in groups if g["runner"] == "slow")
            self.assertLess(fast["high"], slow["low"])  # certified
            _insert(conn, "fam2", [
                _receipt("a", "m", 10.0, cv=0.15), _receipt("b", "m", 9.9, cv=0.15),
            ])
            g2 = eden.group_stats(conn, "fam2")
            self.assertFalse(g2[0]["high"] < g2[1]["low"])  # overlap -> no cert


class TestFamilyId(unittest.TestCase):
    SPEC = {
        "task_contract_version": "topk-words/1",
        "generator": {"type": "synthetic-words", "seed": 42, "vocab": 8,
                      "tokens": 10, "zipf": 1.1},
        "k": 3, "quality": {"type": "exact-match"},
        "input_schema": "text/plain",
        "resource_boundary_profile": "b",
    }

    def test_seed_is_instance_not_family(self):
        a = eden.family_id_of(self.SPEC)
        other = json.loads(json.dumps(self.SPEC))
        other["generator"]["seed"] = 99
        self.assertEqual(a, eden.family_id_of(other))

    def test_quality_change_changes_family(self):
        other = json.loads(json.dumps(self.SPEC))
        other["quality"] = {"type": "tests-pass"}
        self.assertNotEqual(eden.family_id_of(self.SPEC),
                            eden.family_id_of(other))


if __name__ == "__main__":
    unittest.main()
