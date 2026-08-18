"""Tests for challenge sampling: determinism, auditability, enrollment."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import challenge

CORRECT = textwrap.dedent('''\
    def double(x):
        return x + x

    def is_small(x):
        return x < 10
''')

TESTS = textwrap.dedent('''\
    import unittest
    from mod import double, is_small

    class T(unittest.TestCase):
        def test_double(self):
            self.assertEqual(double(3), 6)

        def test_small(self):
            self.assertTrue(is_small(9))
            self.assertFalse(is_small(10))

    if __name__ == "__main__":
        unittest.main()
''')


class TestEpochSeed(unittest.TestCase):
    def test_recomputable(self):
        a = challenge.derive_epoch_seed("fam", 1, ["r1", "r2"])
        b = challenge.derive_epoch_seed("fam", 1, ["r1", "r2"])
        self.assertEqual(a, b)

    def test_ledger_dependence(self):
        a = challenge.derive_epoch_seed("fam", 1, ["r1"])
        b = challenge.derive_epoch_seed("fam", 1, ["r1", "r2"])
        self.assertNotEqual(a, b)


class TestInjectBug(unittest.TestCase):
    def _test_path(self, td):
        p = Path(td, "test_mod.py")
        p.write_text(TESTS)
        return p

    def test_deterministic_and_breaking(self):
        with tempfile.TemporaryDirectory() as td:
            tp = self._test_path(td)
            m1, d1 = challenge.inject_bug(CORRECT, "ab" * 32, tp, "mod")
            m2, d2 = challenge.inject_bug(CORRECT, "ab" * 32, tp, "mod")
            self.assertEqual((m1, d1), (m2, d2))       # same seed, same bug
            self.assertNotEqual(m1, CORRECT)            # a bug was injected
            self.assertTrue(challenge._tests_fail(m1, tp, "mod"))
            compile(m1, "<m>", "exec")                  # still valid python

    def test_seeds_spread_over_bug_classes(self):
        # On the real substrate (many mutation sites), a handful of seeds
        # must not all collapse onto a single bug.
        base = Path(__file__).resolve().parent.parent
        correct = (base / "tasks" / "codefix" / "correct_stats.py").read_text()
        tp = base / "tasks" / "codefix" / "test_stats2.py"
        descs = {challenge.inject_bug(correct, f"{i:02x}" * 32, tp, "stats")[1]
                 for i in range(4)}
        self.assertGreaterEqual(len(descs), 2)


class TestEnrollment(unittest.TestCase):
    def test_exact_hash_required(self):
        self.assertTrue(challenge.check_enrollment("abc123", "abc123"))
        self.assertFalse(challenge.check_enrollment("abc123", "abc124"))

    def test_empty_commitment_rejected(self):
        self.assertFalse(challenge.check_enrollment("", ""))


if __name__ == "__main__":
    unittest.main()
