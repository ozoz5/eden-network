"""Tests for the tamper-evident journal: edits must become DETECTABLE."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eden


def _receipt(i):
    return json.dumps({"runner_id": f"r{i}", "meter_id": "m",
                       "run_energy": {"energy_joules": 1.0 + i},
                       "verification_energy": {"energy_joules": 0.1},
                       "uncertainty_profile": {"assigned_cv": 0.15}})


class TempLedger:
    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._old = eden.DB_PATH
        eden.DB_PATH = Path(self._dir.name) / "test.db"
        return eden.db()

    def __exit__(self, *exc):
        eden.DB_PATH = self._old
        self._dir.cleanup()


def _insert_receipts(conn, n):
    for i in range(n):
        rj = _receipt(i)
        rhash = eden.sha(rj)[:16]
        conn.execute("INSERT INTO receipts(receipt_id, run_id, family_id, "
                     "receipt_json, receipt_hash, created_at) VALUES (?,?,?,?,?,?)",
                     (rhash, f"run{i}", "fam", rj, rhash,
                      f"2026-08-18T00:00:{i:02d}+00:00"))
    conn.commit()


class TestChain(unittest.TestCase):
    def test_build_and_verify_intact(self):
        with TempLedger() as conn:
            _insert_receipts(conn, 5)
            with redirect_stdout(io.StringIO()):
                eden.cmd_chain_build()
                self.assertTrue(eden.cmd_chain_verify())

    def test_build_is_idempotent(self):
        with TempLedger() as conn:
            _insert_receipts(conn, 3)
            with redirect_stdout(io.StringIO()):
                eden.cmd_chain_build()
                eden.cmd_chain_build()
            n = conn.execute("SELECT COUNT(*) c FROM chain").fetchone()["c"]
            self.assertEqual(n, 3)

    def test_receipt_body_tampering_is_detected(self):
        with TempLedger() as conn:
            _insert_receipts(conn, 4)
            with redirect_stdout(io.StringIO()):
                eden.cmd_chain_build()
            # the audit-10 attack: UPDATE the "immutable" observation
            victim = conn.execute(
                "SELECT receipt_id FROM receipts LIMIT 1").fetchone()
            conn.execute(
                "UPDATE receipts SET receipt_json=? WHERE receipt_id=?",
                (_receipt(99), victim["receipt_id"]))
            conn.commit()
            with redirect_stdout(io.StringIO()):
                self.assertFalse(eden.cmd_chain_verify())

    def test_chain_link_tampering_is_detected(self):
        with TempLedger() as conn:
            _insert_receipts(conn, 4)
            with redirect_stdout(io.StringIO()):
                eden.cmd_chain_build()
            conn.execute("UPDATE chain SET chain_hash='deadbeef' WHERE seq=2")
            conn.commit()
            with redirect_stdout(io.StringIO()):
                self.assertFalse(eden.cmd_chain_verify())


if __name__ == "__main__":
    unittest.main()
