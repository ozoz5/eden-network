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


class TestSemanticBugs(unittest.TestCase):
    def test_semantic_injection_breaks_tests_and_is_deterministic(self):
        base = Path(__file__).resolve().parent.parent
        correct = (base / "tasks" / "codefix" / "correct_stats.py").read_text()
        tp = base / "tasks" / "codefix" / "test_stats2.py"
        m1, d1 = challenge.inject_semantic_bug(correct, "ab" * 32, tp, "stats")
        m2, d2 = challenge.inject_semantic_bug(correct, "ab" * 32, tp, "stats")
        self.assertEqual((m1, d1), (m2, d2))
        self.assertTrue(d1.startswith("sem:"))
        self.assertTrue(challenge._tests_fail(m1, tp, "stats"))

    def test_semantic_bugs_are_outside_token_space(self):
        # No single BUG_OPS substitution may turn the buggy fragment back
        # into the correct one — the definition of search-defeating.
        for correct_frag, buggy_frag in challenge.SEMANTIC_BUGS:
            for a, b in challenge.BUG_OPS:
                start = 0
                while True:
                    i = buggy_frag.find(a, start)
                    if i < 0:
                        break
                    mutated = buggy_frag[:i] + b + buggy_frag[i + len(a):]
                    start = i + 1
                    self.assertNotEqual(
                        mutated, correct_frag,
                        f"{buggy_frag!r} is single-token reversible via "
                        f"({a!r}->{b!r})")

    def test_all_semantic_fragments_exist_in_substrate(self):
        base = Path(__file__).resolve().parent.parent
        correct = (base / "tasks" / "codefix" / "correct_stats.py").read_text()
        for correct_frag, _ in challenge.SEMANTIC_BUGS:
            self.assertIn(correct_frag, correct)


class TestEnrollment(unittest.TestCase):
    def test_exact_hash_required(self):
        self.assertTrue(challenge.check_enrollment("abc123", "abc123"))
        self.assertFalse(challenge.check_enrollment("abc123", "abc124"))

    def test_empty_commitment_rejected(self):
        self.assertFalse(challenge.check_enrollment("", ""))


if __name__ == "__main__":
    unittest.main()


class TestPromisedRandomness(unittest.TestCase):
    """Naming a round before it exists is what removes the operator's choice.

    These tests reach the public beacon; when it is unreachable they skip
    rather than pretend to have verified something.
    """

    def _promise(self):
        p = challenge.promise_future_round()
        if p is None:
            self.skipTest("drand unreachable")
        return p

    def test_promised_round_is_in_the_future(self):
        import time
        target, when, chain_hash = self._promise()
        self.assertGreater(when, time.time())
        self.assertTrue(chain_hash)

    def test_a_promised_round_cannot_be_opened_early(self):
        """The whole point: there is nothing to peek at."""
        target, _, _ = self._promise()
        self.assertIsNone(challenge.open_promised_round(target, attempts=1))

    def test_a_past_round_opens_and_is_the_same_for_everyone(self):
        target, _, _ = self._promise()
        past = target - 20
        first = challenge.open_promised_round(past, attempts=2)
        if first is None:
            self.skipTest("drand unreachable")
        self.assertEqual(first, challenge.open_promised_round(past, attempts=2))
        self.assertTrue(first.startswith(f"round:{past}:"))

    def test_seed_is_reproducible_from_public_inputs(self):
        """Anyone holding the ledger's commitment can re-derive the seed from
        the beacon — the epoch's fairness is checkable without trusting us."""
        target, _, _ = self._promise()
        value = challenge.open_promised_round(target - 20, attempts=2)
        if value is None:
            self.skipTest("drand unreachable")
        a = challenge.derive_epoch_seed_v2("fam", 3, "commit", value)
        b = challenge.derive_epoch_seed_v2("fam", 3, "commit", value)
        self.assertEqual(a, b)
        self.assertNotEqual(
            a, challenge.derive_epoch_seed_v2("fam", 3, "other", value))
