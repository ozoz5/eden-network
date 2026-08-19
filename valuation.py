"""Cross-family valuation — the open problem, made measurable.

A frontier update in a family that burns 400 J per success and one in a
family that burns 0.1 J are both "intelligence removing resource", but they
are not the same number of joules. Deciding what they are worth relative to
each other is economics, not physics, and the spec (§6.1) refuses to settle
it by argument: the schemes are to be run against real data and compared.

This module does not change what EDEN mints. It computes what each scheme
WOULD issue for the mints already in the ledger, so the choice can be made
against evidence.
"""

import math

SCHEMES = ("physical", "demand", "budget", "ratio")


def physical(mints, context):
    """Mint proportional to joules saved. What EDEN does today.

    Its flaw is visible in its own arithmetic: a family whose runs cost more
    pays more for the same proportional improvement, which rewards choosing
    a wasteful arena over a frugal one (spec §6.11, salt-the-mine)."""
    return {m["mint_id"]: m["gain_j"] for m in mints}


def demand(mints, context):
    """Weight the joules by how much verified work the family actually
    carries. Rewards improvements people use — and invites manufactured
    demand, which the spec already flags as self-dealing."""
    return {m["mint_id"]: m["gain_j"] * context["family_receipts"].get(
        m["family_id"], 0) for m in mints}


def budget(mints, context, per_family=100.0):
    """Give every family the same issuance budget, split by each mint's
    share within it. Scale-independent, but it needs someone to decide what
    counts as a family and how large the budget is — governance re-enters."""
    totals = {}
    for m in mints:
        totals[m["family_id"]] = totals.get(m["family_id"], 0.0) + m["gain_j"]
    out = {}
    for m in mints:
        total = totals[m["family_id"]]
        share = (m["gain_j"] / total) if total else 0.0
        out[m["mint_id"]] = per_family * share
    return out


def ratio(mints, context, scale=100.0):
    """Mint on how many times cheaper the result became, not how many joules
    were removed. A tenfold improvement pays the same whether it happened at
    400 J or at 0.4 J, so building a wasteful arena buys nothing."""
    out = {}
    for m in mints:
        before, after = m["prev_j"], m["new_j"]
        if not before or not after or after <= 0 or before <= after:
            out[m["mint_id"]] = 0.0
        else:
            out[m["mint_id"]] = scale * math.log2(before / after)
    return out


def evaluate(mints, context):
    """Every scheme's issuance for the same ledger, normalised so the totals
    match — otherwise the comparison only reflects each scheme's units."""
    raw = {name: globals()[name](mints, context) for name in SCHEMES}
    out = {}
    for name, values in raw.items():
        total = sum(values.values())
        out[name] = ({k: v / total for k, v in values.items()} if total
                     else {k: 0.0 for k in values})
    return out


def family_shares(normalised, mints):
    """Where each scheme sends the issuance, by family."""
    fam_of = {m["mint_id"]: m["family_id"] for m in mints}
    out = {}
    for scheme, values in normalised.items():
        shares = {}
        for mint_id, v in values.items():
            fam = fam_of[mint_id]
            shares[fam] = shares.get(fam, 0.0) + v
        out[scheme] = shares
    return out


def salt_the_mine_advantage(improvement_factor: float, scale_multiplier: float,
                            base_before_j: float = 1.0):
    """What an operator gains by staging the same improvement in a wasteful
    arena instead of a frugal one.

    Identical intelligence — the same factor of improvement — is applied to
    a family whose runs cost `scale_multiplier` times more. Returns the ratio
    of issuance between the wasteful staging and the frugal one, per scheme.
    """
    out = {}
    for name in SCHEMES:
        if name == "physical":
            # joules saved scale with the arena
            out[name] = scale_multiplier
        elif name == "demand":
            out[name] = scale_multiplier      # weighting does not undo scale
        elif name in ("budget", "ratio"):
            out[name] = 1.0                   # scale-independent by design
    return out
