"""Challenge sampling — protocol-issued task instances (v0.2, spec §6.17).

The frontier must be "expected J over a distribution the protocol hands you",
not "minimum J over instances you chose yourself". This module provides:

  - epoch seed derivation that is recomputable from the ledger (auditable;
    an operator who grinds it leaves receipt traces)
  - deterministic bug injection: a seeded single mutation of a correct
    module, validated to (a) compile and (b) fail the family's test suite
  - the enrollment rule: runner code hashes are pinned BEFORE instances are
    generated, so implementations cannot be tailored to revealed instances

Honest limitations (recorded, not hidden):
  - single-operator ledger: the seed source is auditable but not trustless
    (spec pending: public randomness / ORE beacon, §13 v1)
  - generation energy is spent outside any receipt (measurement-window
    boundary, spec §6.13)
"""

import hashlib
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Single-token bug classes. Every pair has an inverse reachable by search,
# so the injected bugs are honest targets for all runner strategies.
BUG_OPS = [
    ("+", "-"), ("-", "+"), ("<", "<="), ("<=", "<"),
    (">", ">="), (">=", ">"), ("==", "!="), ("// 2", "// 2 - 1"),
]

# Semantic bug classes (code-fix/3): (correct_fragment, buggy_fragment).
# Each is chosen so that NO single-token substitution from BUG_OPS can undo
# it — the search-defeating distribution. Restoring these requires knowing
# what the code means (sample vs population variance, sorting before median,
# accumulating vs overwriting), not just flipping operators.
SEMANTIC_BUGS = [
    ("acc / (len(values) - 1)", "acc / len(values)"),       # population var
    ("s = sorted(values)", "s = list(values)"),             # median w/o sort
    ("return total / len(values)", "return len(values) / total"),  # inverted
    ("return s[mid]", "return s[mid - 1]"),                 # odd-median index
    ("d = v - m", "d = v"),                                 # uncentered var
    ("total = total + v", "total = v"),                     # last-value mean
]


def derive_epoch_seed(family_id: str, epoch_no: int, receipt_hashes) -> str:
    """Seed = H(family | epoch | recent ledger receipts). Recomputable."""
    material = family_id + "|" + str(epoch_no) + "|" + "|".join(receipt_hashes)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _tests_fail(source: str, test_path, module_name: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        Path(td, module_name + ".py").write_text(source)
        shutil.copy(test_path, Path(td, Path(test_path).name))
        r = subprocess.run(
            [sys.executable, "-m", "unittest", Path(test_path).stem],
            cwd=td, capture_output=True,
        )
        return r.returncode != 0


def _mutation_sites(source: str):
    sites = []
    for a, b in BUG_OPS:
        start = 0
        while True:
            i = source.find(a, start)
            if i < 0:
                break
            sites.append((i, a, b))
            start = i + 1
    return sites


def inject_bug(correct_source: str, seed_hex: str, test_path,
               module_name: str):
    """Deterministically pick one mutation that compiles and breaks tests."""
    rng = random.Random(int(seed_hex[:16], 16))
    sites = _mutation_sites(correct_source)
    rng.shuffle(sites)
    for i, a, b in sites:
        mutant = correct_source[:i] + b + correct_source[i + len(a):]
        try:
            compile(mutant, "<mutant>", "exec")
        except SyntaxError:
            continue
        if _tests_fail(mutant, test_path, module_name):
            return mutant, f"{a}->{b}@{i}"
    raise RuntimeError(f"no valid bug injection for seed {seed_hex[:16]}")


def inject_semantic_bug(correct_source: str, seed_hex: str, test_path,
                        module_name: str):
    """Seeded choice among semantic mutations that compile and break tests."""
    rng = random.Random(int(seed_hex[:16], 16))
    candidates = [p for p in SEMANTIC_BUGS if p[0] in correct_source]
    rng.shuffle(candidates)
    for correct_frag, buggy_frag in candidates:
        mutant = correct_source.replace(correct_frag, buggy_frag, 1)
        if mutant == correct_source:
            continue
        try:
            compile(mutant, "<mutant>", "exec")
        except SyntaxError:
            continue
        if _tests_fail(mutant, test_path, module_name):
            return mutant, f"sem:{correct_frag[:20]}=>{buggy_frag[:20]}"
    raise RuntimeError(f"no valid semantic injection for seed {seed_hex[:16]}")


def inject(mode: str, correct_source: str, seed_hex: str, test_path,
           module_name: str):
    if mode == "semantic":
        return inject_semantic_bug(correct_source, seed_hex, test_path,
                                   module_name)
    return inject_bug(correct_source, seed_hex, test_path, module_name)


def check_enrollment(committed_hash: str, current_hash: str) -> bool:
    """A runner may only score in an epoch with the exact code it committed."""
    return bool(committed_hash) and committed_hash == current_hash
