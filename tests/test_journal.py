"""Tests for journal rules: hashing, rule derivation, and rule changes."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eden
import journal


class TestEntryHash(unittest.TestCase):
    def test_legacy_matches_original_receipt_hash(self):
        body = json.dumps({"a": 1}, sort_keys=True, separators=(",", ":"))
        self.assertEqual(journal.entry_hash("v1-legacy", "receipt", body),
                         eden.sha(body)[:16])

    def test_domain_separates_types(self):
        body = json.dumps({"chain_head": "abc", "node_id": "n1"},
                          sort_keys=True, separators=(",", ":"))
        a = journal.entry_hash("v2-domain", "checkpoint", body)
        b = journal.entry_hash("v2-domain", "revocation", body)
        self.assertNotEqual(a, b)

    def test_domain_hash_is_full_length(self):
        h = journal.entry_hash("v2-domain", "receipt", "{}")
        self.assertEqual(len(h), 64)

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            journal.entry_hash("v3-invented", "receipt", "{}")


class TestRuleDerivation(unittest.TestCase):
    def test_default_is_legacy(self):
        self.assertEqual(journal.rule_at([], 1), "v1-legacy")

    def test_rule_applies_from_its_seq(self):
        changes = [{"from_seq": 149, "new_rule": "v2-domain"}]
        self.assertEqual(journal.rule_at(changes, 148), "v1-legacy")
        self.assertEqual(journal.rule_at(changes, 149), "v2-domain")

    def test_unknown_rule_change_refused(self):
        self.assertTrue(journal.validate_rule_change("v1-legacy", "v3-evil"))

    def test_downgrade_refused(self):
        self.assertTrue(journal.validate_rule_change("v2-domain", "v1-legacy"))

    def test_valid_upgrade_accepted(self):
        self.assertEqual(journal.validate_rule_change("v1-legacy", "v2-domain"),
                         [])


class TestRuleHistory(unittest.TestCase):
    """The rule history must validate as a state machine, not a list of claims."""

    VALID = [{"seq": 1, "from_seq": 2, "old_rule": "v1-legacy",
              "new_rule": "v2-domain"}]

    def _others(self, history):
        """Problems other than the timing rule, so each check is proven alone."""
        return [p for p in journal.validate_rule_history(history)
                if "takes effect" not in p]

    def test_valid_history_accepted(self):
        self.assertEqual(journal.validate_rule_history(self.VALID), [])

    def test_change_must_take_effect_right_after_itself(self):
        for from_seq in (2, 50):          # reaching backward, and skipping ahead
            history = [{"seq": 10, "from_seq": from_seq,
                        "old_rule": "v1-legacy", "new_rule": "v2-domain"}]
            self.assertTrue(any("takes effect" in p for p in
                                journal.validate_rule_history(history)))

    def test_old_rule_must_be_the_one_in_force(self):
        history = self.VALID + [{"seq": 8, "from_seq": 9,
                                 "old_rule": "v1-legacy",
                                 "new_rule": "v2-domain"}]
        self.assertTrue(any("in force" in p for p in self._others(history)))

    def test_downgrade_refused_in_history(self):
        history = self.VALID + [{"seq": 8, "from_seq": 9,
                                 "old_rule": "v2-domain",
                                 "new_rule": "v1-legacy"}]
        self.assertTrue(any("downgrade" in p for p in self._others(history)))

    def test_unknown_rule_refused_in_history(self):
        history = self.VALID + [{"seq": 8, "from_seq": 9,
                                 "old_rule": "v2-domain",
                                 "new_rule": "v9-invented"}]
        self.assertTrue(any("unknown rule" in p for p in self._others(history)))

    def test_two_changes_cannot_start_at_the_same_seq(self):
        history = self.VALID + self.VALID
        self.assertTrue(any("already starts" in p for p in self._others(history)))


class TestJournalMigration(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._old = eden.DB_PATH
        eden.DB_PATH = Path(self._dir.name) / "test.db"
        self.conn = eden.db()
        for i in range(6):
            rj = json.dumps({"n": i}, sort_keys=True, separators=(",", ":"))
            h = eden.sha(rj)[:16]
            self.conn.execute("INSERT INTO receipts(receipt_id, run_id, family_id, "
                     "receipt_json, receipt_hash, created_at) VALUES (?,?,?,?,?,?)",
                              (h, f"run{i}", "fam", rj, h,
                               f"2026-08-19T00:00:{i:02d}+00:00"))
        self.conn.commit()

    def tearDown(self):
        eden.DB_PATH = self._old
        self._dir.cleanup()

    def _run(self, fn, *a):
        with redirect_stdout(io.StringIO()):
            return fn(*a)

    def test_migration_preserves_every_prior_hash(self):
        self._run(eden.cmd_chain_build)
        before = [r["chain_hash"] for r in
                  self.conn.execute("SELECT chain_hash FROM chain ORDER BY seq")]
        self._run(eden.cmd_chain_migrate)
        after = [r["chain_hash"] for r in
                 self.conn.execute("SELECT chain_hash FROM chain ORDER BY seq "
                                   "LIMIT ?", (len(before),))]
        self.assertEqual(before, after)
        self.assertTrue(self._run(eden.cmd_chain_verify))

    def test_transition_is_written_under_the_outgoing_rule(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        row = self.conn.execute(
            "SELECT hash_rule, entry_hash FROM chain WHERE entry_type="
            "'rule_change'").fetchone()
        self.assertEqual(row["hash_rule"], "v1-legacy")
        self.assertEqual(len(row["entry_hash"]), 16)

    def test_entries_after_transition_use_the_new_rule(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        rj = json.dumps({"n": 99}, sort_keys=True, separators=(",", ":"))
        h = eden.sha(rj)[:16]
        self.conn.execute("INSERT INTO receipts(receipt_id, run_id, family_id, "
                     "receipt_json, receipt_hash, created_at) VALUES (?,?,?,?,?,?)",
                          (h, "run99", "fam", rj, h,
                           "2026-08-19T01:00:00+00:00"))
        self.conn.commit()
        self._run(eden.cmd_chain_build)
        row = self.conn.execute(
            "SELECT hash_rule, entry_hash FROM chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["hash_rule"], "v2-domain")
        self.assertEqual(len(row["entry_hash"]), 64)
        self.assertTrue(self._run(eden.cmd_chain_verify))

    def test_migration_advances_one_rule_at_a_time(self):
        """Each call moves to the next rule up, and stops once there is no
        stronger rule left — the journal never skips a version."""
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        self.assertEqual(eden._next_rule(self.conn), journal.DOMAIN_RULE)
        self._run(eden.cmd_chain_migrate)
        self.assertEqual(eden._next_rule(self.conn), journal.BOUND_RULE)
        n = self.conn.execute("SELECT COUNT(*) c FROM chain").fetchone()["c"]
        self._run(eden.cmd_chain_migrate)   # nothing stronger exists
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM chain").fetchone()["c"], n)
        self.assertTrue(self._run(eden.cmd_chain_verify))

    def test_every_rule_change_is_recorded_once(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        self._run(eden.cmd_chain_migrate)
        changes = eden._rule_changes(self.conn)
        targets = [c["new_rule"] for c in changes]
        self.assertEqual(sorted(targets),
                         sorted([journal.DOMAIN_RULE, journal.BOUND_RULE]))
        self.assertEqual(journal.validate_rule_history(changes), [])

    def test_a_claimed_rule_cannot_override_history(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        self.conn.execute("UPDATE chain SET hash_rule='v2-domain' WHERE seq=1")
        self.conn.commit()
        self.assertFalse(self._run(eden.cmd_chain_verify))

    def test_retroactive_rule_change_rejected_in_the_ledger(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        body = eden.canonical({"from_seq": 2, "old_rule": "v1-legacy",
                               "new_rule": "v2-domain",
                               "reason": "retroactive"})
        self._run(eden._chain_append, self.conn, "rule_change",
                  "evil:" + eden.sha(body)[:16], body, "v2-domain")
        self.conn.commit()
        self.assertFalse(self._run(eden.cmd_chain_verify))

    def test_body_tampering_still_detected_after_migration(self):
        self._run(eden.cmd_chain_build)
        self._run(eden.cmd_chain_migrate)
        victim = self.conn.execute(
            "SELECT receipt_id FROM receipts LIMIT 1").fetchone()
        self.conn.execute(
            "UPDATE receipts SET receipt_json=? WHERE receipt_id=?",
            ('{"n":666}', victim["receipt_id"]))
        self.conn.commit()
        self.assertFalse(self._run(eden.cmd_chain_verify))


if __name__ == "__main__":
    unittest.main()
