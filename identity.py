"""Node identity and signatures — delegated to OpenSSH, never home-made.

EDEN signs with ssh-keygen -Y (sshsig, Ed25519): the only public-key
signing available without leaving the standard library behind, and an
implementation that has been attacked for twenty years by people better at
it than this project.

What a signature settles: who said this. What it does not settle: whether
what they said is true. The trust states above SIGNED exist precisely
because that gap does not close (TRUST_LAYER_DESIGN.md §0).
"""

import base64
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

KEY_DIR = Path(os.environ.get("EDEN_HOME", Path.home() / ".eden"))
KEY_PATH = KEY_DIR / "node_ed25519"

NS_RECEIPT = "eden-receipt"
NS_CHECKPOINT = "eden-checkpoint"
NS_EPOCH = "eden-epoch"
NS_REVOCATION = "eden-revocation"


class SigningUnavailable(Exception):
    """No key: measurement may still happen, it is simply UNSIGNED."""


def node_id_of(pubkey_line: str) -> str:
    """Full SHA-256 of the public key. Never truncated in storage — an id
    baked into receipts cannot be widened later (Constitution IV)."""
    return hashlib.sha256(pubkey_line.strip().encode("utf-8")).hexdigest()


def have_key() -> bool:
    return KEY_PATH.exists() and KEY_PATH.with_suffix(".pub").exists()


def create_key(comment: str = "eden-node") -> str:
    KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if have_key():
        raise FileExistsError(f"key already exists: {KEY_PATH}")
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(KEY_PATH),
                    "-N", "", "-C", comment, "-q"], check=True)
    KEY_PATH.chmod(0o600)
    return public_key()


def public_key() -> str:
    pub = KEY_PATH.with_suffix(".pub")
    if not pub.exists():
        raise SigningUnavailable(f"no public key at {pub}")
    return pub.read_text().strip()


def sign(payload: str, namespace: str) -> str:
    """Sign bytes over stdin — no temporary file holds the payload, so there
    is no window in which another process can read or swap it."""
    if not have_key():
        raise SigningUnavailable(f"no signing key at {KEY_PATH}")
    proc = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(KEY_PATH), "-n", namespace, "-"],
        input=payload.encode("utf-8"), capture_output=True)
    if proc.returncode != 0:
        raise SigningUnavailable(proc.stderr.decode()[:200])
    return base64.b64encode(proc.stdout).decode("ascii")


def verify(payload: str, sig_b64: str, namespace: str, pubkey_line: str) -> bool:
    """Verify against the public key carried by the ledger, not against
    whatever the local machine happens to trust."""
    principal = node_id_of(pubkey_line)[:16]
    key_fields = " ".join(pubkey_line.split()[:2])
    with tempfile.TemporaryDirectory() as td:
        signers = Path(td, "allowed_signers")
        signers.write_text(f"{principal} {key_fields}\n")
        sig_path = Path(td, "sig")
        try:
            sig_path.write_bytes(base64.b64decode(sig_b64))
        except Exception:
            return False
        proc = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(signers),
             "-I", principal, "-n", namespace, "-s", str(sig_path)],
            input=payload.encode("utf-8"), capture_output=True)
    return proc.returncode == 0
