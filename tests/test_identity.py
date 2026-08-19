"""Signature tests: what a signature settles, and what it must refuse."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        os.environ["EDEN_HOME"] = self._dir.name
        for mod in ("identity",):
            sys.modules.pop(mod, None)
        import identity
        self.identity = identity
        identity.KEY_DIR = Path(self._dir.name)
        identity.KEY_PATH = identity.KEY_DIR / "node_ed25519"
        self.pub = identity.create_key("test")
        self.payload = json.dumps({"a": 1}, sort_keys=True, separators=(",", ":"))
        self.sig = identity.sign(self.payload, identity.NS_RECEIPT)

    def tearDown(self):
        self._dir.cleanup()

    def test_node_id_is_full_length(self):
        self.assertEqual(len(self.identity.node_id_of(self.pub)), 64)

    def test_valid_signature_verifies(self):
        self.assertTrue(self.identity.verify(
            self.payload, self.sig, self.identity.NS_RECEIPT, self.pub))

    def test_altered_payload_refused(self):
        self.assertFalse(self.identity.verify(
            self.payload + " ", self.sig, self.identity.NS_RECEIPT, self.pub))

    def test_namespace_reuse_refused(self):
        """A receipt signature must not pass as a checkpoint signature."""
        self.assertFalse(self.identity.verify(
            self.payload, self.sig, self.identity.NS_CHECKPOINT, self.pub))

    def test_other_key_cannot_claim_it(self):
        other_dir = tempfile.mkdtemp()
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-f",
                        other_dir + "/k", "-N", "", "-q"], check=True)
        other_pub = Path(other_dir + "/k.pub").read_text().strip()
        self.assertFalse(self.identity.verify(
            self.payload, self.sig, self.identity.NS_RECEIPT, other_pub))

    def test_garbage_signature_refused(self):
        self.assertFalse(self.identity.verify(
            self.payload, "not-base64!!", self.identity.NS_RECEIPT, self.pub))

    def test_missing_key_is_not_an_error_but_no_signature(self):
        """Measurement precedes trust: a keyless node still measures."""
        self.identity.KEY_PATH = Path(self._dir.name) / "absent"
        with self.assertRaises(self.identity.SigningUnavailable):
            self.identity.sign(self.payload, self.identity.NS_RECEIPT)


if __name__ == "__main__":
    unittest.main()


class TestTrustStateThroughLedger(unittest.TestCase):
    """The ledger path, not just the crypto helper: a broken claim must not
    be indistinguishable from an honest unsigned receipt."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        os.environ["EDEN_HOME"] = self._dir.name
        for mod in ("identity", "eden"):
            sys.modules.pop(mod, None)
        import identity, eden
        identity.KEY_DIR = Path(self._dir.name)
        identity.KEY_PATH = identity.KEY_DIR / "node_ed25519"
        self.identity, self.eden = identity, eden
        self.pub = identity.create_key("test")
        eden.DB_PATH = Path(self._dir.name) / "t.db"
        self.conn = eden.db()
        eden._register_node(self.conn, self.pub, "local")
        body = {"run_energy": {"energy_joules": 1.0}}
        self.receipt = dict(body)
        self.receipt["signatures"] = eden._sign_receipt_body(body)

    def tearDown(self):
        self._dir.cleanup()

    def test_valid_receipt_is_signed(self):
        self.assertEqual(
            self.eden.trust_state_of(self.conn, self.receipt, "run1"), "SIGNED")

    def test_tampered_body_is_invalid_not_unsigned(self):
        evil = json.loads(json.dumps(self.receipt))
        evil["run_energy"]["energy_joules"] = 0.0001
        self.assertEqual(
            self.eden.trust_state_of(self.conn, evil, "run1"), "INVALID")

    def test_unregistered_node_is_invalid(self):
        evil = json.loads(json.dumps(self.receipt))
        evil["signatures"][0]["node_id"] = "f" * 64
        self.assertEqual(
            self.eden.trust_state_of(self.conn, evil, "run1"), "INVALID")

    def test_namespace_rewrite_is_invalid(self):
        evil = json.loads(json.dumps(self.receipt))
        evil["signatures"][0]["namespace"] = self.identity.NS_CHECKPOINT
        self.assertEqual(
            self.eden.trust_state_of(self.conn, evil, "run1"), "INVALID")

    def test_honest_unsigned_receipt_stays_local(self):
        self.assertEqual(
            self.eden.trust_state_of(self.conn, {"signatures": []}, "run1"),
            "LOCAL")


class TestIndependentVerification(unittest.TestCase):
    """VERIFIED means another machine re-ran the work and agreed."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        os.environ["EDEN_HOME"] = self._dir.name
        for mod in ("identity", "eden"):
            sys.modules.pop(mod, None)
        import identity, eden
        identity.KEY_DIR = Path(self._dir.name)
        identity.KEY_PATH = identity.KEY_DIR / "node_ed25519"
        self.identity, self.eden = identity, eden
        self.pub = identity.create_key("forge")
        eden.DB_PATH = Path(self._dir.name) / "t.db"
        self.conn = eden.db()
        eden._register_node(self.conn, self.pub, "local")

        body = {"run_energy": {"energy_joules": 1.0},
                "hardware_profile": {"platform": "forge-os", "machine": "arm64"}}
        self.receipt = dict(body)
        self.receipt["signatures"] = eden._sign_receipt_body(body)
        self.rhash = eden.sha(eden.canonical(self.receipt))[:16]
        self.conn.execute(
            "INSERT INTO receipts(receipt_id, run_id, family_id, receipt_json, "
            "receipt_hash, created_at) VALUES (?,?,?,?,?,?)",
            (self.rhash, "run1", "fam", eden.canonical(self.receipt),
             self.rhash, "t"))
        self.conn.commit()

    def tearDown(self):
        self._dir.cleanup()

    def _foreign_verification(self, **overrides):
        """A verification signed by a different key, as another node would."""
        other = Path(tempfile.mkdtemp()) / "k"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(other),
                        "-N", "", "-q"], check=True)
        pub = Path(str(other) + ".pub").read_text().strip()
        body = {"receipt_hash": self.rhash, "verdict": "PASS",
                "verifier_spec_hash": "spec", "hw_fingerprint": "witness",
                "public_key": pub, "trust_basis": "test"}
        body.update(overrides)
        saved = self.identity.KEY_PATH
        self.identity.KEY_PATH = other
        body["signature"] = self.identity.sign(
            self.eden.canonical(body), self.identity.NS_RECEIPT)
        self.identity.KEY_PATH = saved
        path = Path(self._dir.name) / "vr.json"
        path.write_text(json.dumps(body))
        return str(path)

    def _import(self, path):
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()) as f:
            ok = self.eden.cmd_import_verification(path)
        return ok, f.getvalue()

    def test_independent_verification_promotes_to_verified(self):
        ok, _ = self._import(self._foreign_verification())
        self.assertTrue(ok)
        self.assertEqual(
            self.eden.trust_state_of(self.conn, self.receipt, "run1"), "VERIFIED")

    def test_same_hardware_is_not_independent(self):
        """A machine confirming itself must not reach VERIFIED, even with a
        perfectly valid signature."""
        own = self.eden._hw_fingerprint_of(self.receipt)
        ok, out = self._import(self._foreign_verification(hw_fingerprint=own))
        self.assertFalse(ok)
        self.assertIn("same hardware", out)
        self.assertEqual(
            self.eden.trust_state_of(self.conn, self.receipt, "run1"), "SIGNED")

    def test_tampered_verdict_refused(self):
        path = self._foreign_verification()
        body = json.loads(Path(path).read_text())
        body["verdict"] = "PASS"
        body["output_hash_observed"] = "forged"
        Path(path).write_text(json.dumps(body))
        ok, out = self._import(path)
        self.assertFalse(ok)
        self.assertIn("signature", out)

    def test_verification_for_unknown_receipt_refused(self):
        ok, out = self._import(self._foreign_verification(receipt_hash="f" * 16))
        self.assertFalse(ok)
        self.assertIn("no receipt", out)
