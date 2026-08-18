"""ORE — the cultural layer (v1 spec §13, implemented at last).

EDEN's very first idea: randomness born at the moment of intelligent work.
An ORE is discovered when

    H(receipt_hash + ":" + sealing_epoch_seed)

happens to be rare. The sealing epoch is the FIRST epoch opened after the
receipt was created: its seed is derived from the ledger's later contents,
so no receipt can know or choose the randomness that will seal it. The
operator could grind epochs, but grinding leaves receipt traces — the same
auditable-not-trustless honesty as challenge seeds.

Constitutional separation (§6.7): ORE carries NO economic fields, converts
to no CREDIT, grants no priority, stakes nothing. Economy for the machines,
play for the humans. This module must never import eligibility.

Rarity by leading zero bits of the discovery hash:
    SPARK >= 6   (~1/64)
    VEIN  >= 10  (~1/1024)
    GEM   >= 14  (~1/16384)
    VOID  >= 18  (~1/262144)
"""

import hashlib

TIERS = (("VOID", 18), ("GEM", 14), ("VEIN", 10), ("SPARK", 6))


def discovery_hash(receipt_hash: str, epoch_seed: str) -> str:
    return hashlib.sha256(
        (receipt_hash + ":" + epoch_seed).encode("utf-8")).hexdigest()


def leading_zero_bits(hex_digest: str) -> int:
    bits = 0
    for ch in hex_digest:
        v = int(ch, 16)
        if v == 0:
            bits += 4
            continue
        bits += 4 - v.bit_length()
        break
    return bits


def tier_of(zero_bits: int):
    for name, threshold in TIERS:
        if zero_bits >= threshold:
            return name
    return None


def discover(receipt_hash: str, epoch_seed: str):
    """Returns (ore_hash, zero_bits, tier) — tier is None for common dust."""
    h = discovery_hash(receipt_hash, epoch_seed)
    z = leading_zero_bits(h)
    return h, z, tier_of(z)
