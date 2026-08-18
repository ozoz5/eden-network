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

import hashlib

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


def hw_fingerprint(rec) -> str:
    """Weak node identity from the receipt's declared hardware profile.

    Two machines on the same OS build would collide — real node identity
    needs signatures (Phase 2). Good enough to keep different machines from
    sharing a sigma, which is the same class of error as mixing meters."""
    hp = rec.get("hardware_profile") or {}
    material = str(hp.get("platform", "")) + "|" + str(hp.get("machine", ""))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:6]


def group_stats(receipts) -> list:
    """Fold parsed receipts into replication groups with certified intervals."""
    groups = {}
    for rec in receipts:
        key = (rec["runner_id"], rec.get("runner_code_hash", ""),
               rec["meter_id"], hw_fingerprint(rec))
        g = groups.setdefault(key, {"e": [], "v": [], "cv": 0.0})
        g["e"].append(rec["run_energy"]["energy_joules"])
        g["v"].append(rec["verification_energy"]["energy_joules"])
        g["cv"] = max(g["cv"], rec["uncertainty_profile"]["assigned_cv"])
    out = []
    for (runner, code_hash, meter, hw), g in groups.items():
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
            "group": f"{runner}#{code_hash[:6]}@{meter}/hw{hw}",
            "runner": runner, "meter": meter, "code_hash": code_hash,
            "hw": hw, "meter_class": meter_class(meter),
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


MIN_INSTANCES = 5   # distribution certificates need a minimal epoch size
Z_95 = 1.96


def wilson_interval(successes: int, attempts: int, z: float = Z_95):
    """95% interval for a success rate; honest about small n."""
    if attempts == 0:
        return (0.0, 1.0)
    p = successes / attempts
    denom = 1 + z * z / attempts
    center = (p + z * z / (2 * attempts)) / denom
    half = z * ((p * (1 - p) / attempts
                 + z * z / (4 * attempts * attempts)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def distribution_cert(epoch_id, family_id, runner, code_hash, meter,
                      n_instances, attempts, successes, run_j, verify_j):
    """The frontier's input unit for challenge families (v0.3):
    not "solved one instance cheaply" but "processed the issued distribution
    at success rate q for X J per success". Verification energy is inside
    the cost (Constitution III is structural, not a deduction step)."""
    total = run_j + verify_j
    rate = successes / attempts if attempts else 0.0
    jps = (total / successes) if successes else float("inf")
    lo, hi = wilson_interval(successes, attempts)
    return {
        "cert_id": f"{epoch_id[:8]}:{runner}#{code_hash[:6]}@{meter}",
        "epoch_id": epoch_id, "family_id": family_id,
        "runner": runner, "code_hash": code_hash, "meter": meter,
        "n_instances": n_instances, "attempts": attempts,
        "successes": successes, "success_rate": rate,
        "rate_ci95": [lo, hi],
        "run_j": run_j, "verify_j": verify_j, "total_j": total,
        "j_per_success": jps,
    }


def cert_eligible(cert) -> dict:
    reasons = []
    if cert["n_instances"] < MIN_INSTANCES:
        reasons.append(f"epoch too small: {cert['n_instances']} < {MIN_INSTANCES}")
    if cert["attempts"] < cert["n_instances"]:
        reasons.append("incomplete: fewer attempts than issued instances")
    return {"eligible": not reasons, "reasons": reasons,
            "pending": list(PENDING_CHECKS)}


def dominates(a, b) -> bool:
    """Pareto dominance on (success_rate up, J/success down), same meter only."""
    if a["meter"] != b["meter"]:
        return False
    ge = (a["success_rate"] >= b["success_rate"]
          and a["j_per_success"] <= b["j_per_success"])
    strict = (a["success_rate"] > b["success_rate"]
              or a["j_per_success"] < b["j_per_success"])
    return ge and strict


JPS_MARGIN = 0.2   # provisional J/success margin until per-cert energy
                   # intervals exist (audit H4: energy has meter noise too)


def certified_dominates(a, b) -> bool:
    """Uncertainty-aware dominance (audit H4). Point-estimate Pareto is the
    OBSERVED frontier; minting demands more: no-worse on both axes AND
    clearly-better beyond uncertainty on at least one — Wilson-interval
    separation on success rate, or a declared margin on J/success."""
    if a["meter"] != b["meter"] or b["successes"] == 0:
        return False
    rate_ge = a["success_rate"] >= b["success_rate"]
    jps_le = a["j_per_success"] <= b["j_per_success"]
    if not (rate_ge and jps_le):
        return False
    rate_sep = a["rate_ci95"][0] >= b["rate_ci95"][1]
    jps_sep = a["j_per_success"] <= b["j_per_success"] * (1 - JPS_MARGIN)
    return rate_sep or jps_sep


def certification_basis(a, b) -> list:
    """Which axis certifies the dominance — named honestly: the J/success
    margin is a protocol parameter, NOT a confidence interval (audit)."""
    bases = []
    if a["rate_ci95"][0] >= b["rate_ci95"][1]:
        bases.append("success-rate-certified (Wilson CI separation)")
    if a["j_per_success"] <= b["j_per_success"] * (1 - JPS_MARGIN):
        bases.append("energy-margin-certified (protocol margin, not a CI)")
    return bases


def pareto_frontier(certs) -> list:
    """Non-dominated certs. A cert with zero successes has no J/success and
    can hold no record — it is excluded from membership (audit cosmetic fix:
    an empty meter stratum must not exhibit an 'infinite' frontier)."""
    live = [c for c in certs if c["successes"] > 0]
    return [c for c in live
            if not any(dominates(o, c) for o in live if o is not c)]


def assess_cert_insertion(existing_certs, new_cert) -> dict:
    """Issuance rule for distribution certs: minting happens at cert
    registration, as a pure function of ledger order (replayable).

    Mint iff the new cert Pareto-dominates a previously non-dominated cert
    with a finite J/success, and the family's verification cost does not
    exceed its run cost (rho gate). Gain = J/success improvement over the
    best dominated frontier cert (1 CREDIT = 1 J-per-success improvement,
    v0 provisional)."""
    rep = cert_eligible(new_cert)
    if not rep["eligible"]:
        return {"eligible": False, "reasons": rep["reasons"], "gain": 0.0,
                "mintable": False, "mint_reasons": [],
                "dominated": [], "pending": rep["pending"]}
    prior_frontier = pareto_frontier(existing_certs)
    dominated = [c for c in prior_frontier if dominates(new_cert, c)]
    certified = [c for c in dominated if certified_dominates(new_cert, c)]
    mint_reasons = []
    finite = [c for c in certified
              if c["j_per_success"] != float("inf")]
    if not dominated:
        mint_reasons.append("no prior frontier cert dominated (genesis or "
                            "non-dominating entry)")
    elif not certified:
        mint_reasons.append("observed domination only — not certified "
                            "(CI overlap / within J-margin, audit H4)")
    elif not finite:
        mint_reasons.append("dominated certs have no finite J/success — "
                            "no measurable improvement to price")
    if new_cert["run_j"] > 0 and new_cert["verify_j"] / new_cert["run_j"] > RHO_MAX:
        mint_reasons.append(
            f"rho={new_cert['verify_j']/new_cert['run_j']:.2f} > {RHO_MAX:g} "
            "— verification costs more than the runs (spec §5)")
    gain = 0.0
    if not mint_reasons:
        gain = max(c["j_per_success"] for c in finite) - new_cert["j_per_success"]
        if gain <= 0:
            mint_reasons.append("no positive J/success improvement")
            gain = 0.0
    basis = sorted({b for c in certified for b in certification_basis(new_cert, c)})
    return {"eligible": True, "reasons": [], "gain": gain,
            "mintable": not mint_reasons, "mint_reasons": mint_reasons,
            "dominated": dominated, "certified": certified, "basis": basis,
            "pending": rep["pending"]}


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
