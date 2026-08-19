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
