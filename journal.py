"""Journal rules — how entries hash, and how that rule may itself change.

The chain is append-only, so a rule that changes how entries hash cannot be
applied retroactively: recomputing past entries would invalidate heads
already anchored in public commits (Constitution IV). Instead the rule
carries a version, each seq range is governed by the rule in force at that
point, and the change itself is recorded as an entry.

Isolated from eden.py so the rules that decide what the ledger's history
means can be audited and tested on their own.
"""

import hashlib

LEGACY_RULE = "v1-legacy"
DOMAIN_RULE = "v2-domain"
BOUND_RULE = "v3-bound-id"

# A verifier accepts only the rules it implements. The journal records that a
# rule change happened; it does not have the authority to legitimise any rule
# a writer invents (audit 5).
SUPPORTED_RULES = (LEGACY_RULE, DOMAIN_RULE, BOUND_RULE)
RULE_STRENGTH = {LEGACY_RULE: 1, DOMAIN_RULE: 2, BOUND_RULE: 3}


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def entry_hash(rule: str, entry_type: str, canonical_bytes: str,
               entry_id: str = "") -> str:
    """v1-legacy: 16 hex of SHA-256(body), no domain — the rule the first 147
    entries were written under, defined here so they hash identically.
    v2-domain: full SHA-256 over a type-qualified preimage, so two entries of
    different kinds can never share a hash."""
    if rule == LEGACY_RULE:
        return _sha(canonical_bytes)[:16]
    if rule == DOMAIN_RULE:
        return _sha("EDEN:" + entry_type + ":v1|" + canonical_bytes)
    if rule == BOUND_RULE:
        # The id is part of what is committed to: anything that later points
        # at an entry by id (a revocation, a verification) must not be able to
        # find the same hash under a different id.
        return _sha("EDEN:" + entry_type + ":v3|" + entry_id + "|"
                    + canonical_bytes)
    raise ValueError(f"unsupported hash rule: {rule}")


def rule_at(rule_changes, seq: int) -> str:
    """Derived from the journal's own history, never from what an entry
    claims about itself (audit 2): an entry that named an unknown or weaker
    rule could otherwise choose how it gets verified."""
    rule = LEGACY_RULE
    for change in sorted(rule_changes, key=lambda c: c["from_seq"]):
        if seq >= change["from_seq"]:
            rule = change["new_rule"]
    return rule


def validate_rule_history(changes) -> list:
    """The rule history is itself a state machine, not a list of claims.

    A change is only meaningful if it takes effect immediately after its own
    entry, names the rule that was actually in force, and moves forward:
    otherwise a later entry could reach back and redefine how earlier entries
    are read.

    changes: [{seq, from_seq, old_rule, new_rule}, ...]
    """
    problems = []
    in_force = LEGACY_RULE
    seen_from = set()
    for ch in sorted(changes, key=lambda c: c.get("seq", 0)):
        seq = ch.get("seq")
        frm = ch.get("from_seq")
        new = ch.get("new_rule")
        if frm != (seq or 0) + 1:
            problems.append(
                f"seq {seq}: takes effect at {frm}, must be {(seq or 0) + 1} "
                "(a change may not reach backward or skip ahead)")
        if ch.get("old_rule") != in_force:
            problems.append(
                f"seq {seq}: claims to supersede {ch.get('old_rule')}, "
                f"but {in_force} was in force")
        if frm in seen_from:
            problems.append(f"seq {seq}: another change already starts at {frm}")
        seen_from.add(frm)
        problems += [f"seq {seq}: {r}"
                     for r in validate_rule_change(in_force, new)]
        if new in SUPPORTED_RULES and RULE_STRENGTH[new] > RULE_STRENGTH[in_force]:
            in_force = new
    return problems


def validate_rule_change(old_rule: str, new_rule: str) -> list:
    reasons = []
    if new_rule not in SUPPORTED_RULES:
        reasons.append(f"unknown rule '{new_rule}' — this verifier implements "
                       f"{', '.join(SUPPORTED_RULES)}")
    elif RULE_STRENGTH[new_rule] <= RULE_STRENGTH.get(old_rule, 0):
        reasons.append(f"downgrade refused: {old_rule} -> {new_rule}")
    return reasons


def legacy_type_of(seq: int, boundary: int):
    """Entries written before the migration predate the concept of an entry
    type, so their type is fixed by this migration rule rather than read from
    a column added afterwards — that column is not covered by the anchored
    chain hashes (audit 3)."""
    return "receipt" if seq <= boundary else None
