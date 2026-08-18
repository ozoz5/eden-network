"""Frontier eligibility — the single gate between observations and issuance.

v0.1 (per EDEN設計書 追補4): every condition that decides whether a receipt
group may form a replication set, hold a record, or trigger a mint lives in
this module, so the issuance rules can be audited and tested in isolation.

Enforced in v0.1:
  - replication key: (runner_id, runner_code_hash, meter_id) — a renamed or
    rewritten runner never inherits another implementation's sigma, and
    meters never share a scale
  - sigma rules: measured sigma (n >= 3) shrinks with sqrt(n); the
    protocol-assigned cv is systematic and does not; interval lower bounds
    clamp at 0
  - same-meter certification: dominance across meter boundaries is undefined
  - minimum replication to hold or take a record (MIN_REPLICATIONS)
  - rho gate: no mint where verification costs more than the run (RHO_MAX)
  - net-gain rule: mint requires gain > 0 after verification energy

Declared by the spec (§2.2 / §6) but NOT yet enforced — always reported as
pending so callers cannot pretend they were checked:
  - challenge sampling (instance cherry-picking, §6.17)
  - independent replication (distinct hardware/identity, §6.2)
  - challenge audit / hidden holdout (§6.13)
"""

K_SIGMA = 2.0          # interval half-width multiplier
MIN_REPLICATIONS = 3   # receipts required to hold or take a record
RHO_MAX = 1.0          # verification-to-run energy ratio ceiling for minting

METER_CLASSES = {
    "powermetrics-package-v1": "V",   # everything else defaults to "S"
}
PENDING_CHECKS = ("challenge-sampling", "independent-replication",
                  "challenge-audit")


def meter_class(meter_id: str) -> str:
    return METER_CLASSES.get(meter_id, "S")


def group_stats(receipts) -> list:
    """Fold parsed receipts into replication groups with certified intervals."""
    groups = {}
    for rec in receipts:
        key = (rec["runner_id"], rec.get("runner_code_hash", ""),
               rec["meter_id"])
        g = groups.setdefault(key, {"e": [], "v": [], "cv": 0.0})
        g["e"].append(rec["run_energy"]["energy_joules"])
        g["v"].append(rec["verification_energy"]["energy_joules"])
        g["cv"] = max(g["cv"], rec["uncertainty_profile"]["assigned_cv"])
    out = []
    for (runner, code_hash, meter), g in groups.items():
        n = len(g["e"])
        mean = sum(g["e"]) / n
        if n >= 3:
            var = sum((x - mean) ** 2 for x in g["e"]) / (n - 1)
            sigma = var ** 0.5
            half = K_SIGMA * sigma / (n ** 0.5)
        else:
            sigma = g["cv"] * mean  # systematic: no sqrt(n) reduction
            half = K_SIGMA * sigma
        out.append({
            "group": f"{runner}#{code_hash[:6]}@{meter}",
            "runner": runner, "meter": meter, "code_hash": code_hash,
            "meter_class": meter_class(meter),
            "n": n, "mean": mean, "sigma": sigma,
            "low": max(0.0, mean - half), "high": mean + half,
            "verify_mean": sum(g["v"]) / n,
        })
    out.sort(key=lambda g: g["high"])
    return out


def rho(group) -> float:
    return (group["verify_mean"] / group["mean"]) if group["mean"] else float("inf")


def assess_record(group) -> dict:
    """May this group hold a record (become frontier state)?"""
    reasons = []
    if group["n"] < MIN_REPLICATIONS:
        reasons.append(f"replications n={group['n']} < {MIN_REPLICATIONS}")
    return {"eligible": not reasons, "reasons": reasons,
            "pending": list(PENDING_CHECKS)}


def assess_transition(holder, candidate) -> dict:
    """May candidate take the frontier from holder — and does it mint?

    Certification (record changes hands) and minting (CREDIT is issued) are
    separate questions: a certified record with rho > RHO_MAX or zero net
    gain updates history but issues nothing (Constitution III).
    """
    reasons = []
    if candidate["meter"] != holder["meter"]:
        reasons.append(f"cross-meter ({candidate['meter']} vs "
                       f"{holder['meter']}) — dominance undefined")
    reasons += assess_record(candidate)["reasons"]
    if not reasons and not candidate["high"] < holder["low"]:
        reasons.append("interval overlap — dominance not certified")
    certifiable = not reasons

    gain = 0.0
    mint_reasons = []
    if certifiable:
        gain = max(0.0, holder["low"] - candidate["high"]
                   - candidate["verify_mean"])
        r = rho(candidate)
        if r > RHO_MAX:
            mint_reasons.append(
                f"rho={r:.2f} > {RHO_MAX:g} — verification costs more than "
                "the run (spec §5: outside the mintable domain)")
        if gain <= 0:
            mint_reasons.append(
                "net gain 0 after verification energy (Constitution III)")
    return {"certifiable": certifiable, "reasons": reasons, "gain": gain,
            "mintable": certifiable and not mint_reasons,
            "mint_reasons": mint_reasons, "pending": list(PENDING_CHECKS)}
