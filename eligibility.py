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

JPS_MARGIN = 0.2   # fallback only: used when a certificate predates
                   # per-observation data and carries no bootstrap interval
BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20260819   # fixed: the same evidence must yield the same
                            # interval on every machine that re-checks it


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


def _cluster(observations):
    """Group observations by the instance they were measured on.

    An observation is (energy, succeeded) or (energy, succeeded, instance).
    Without an instance key each run is its own cluster, which is what the
    older receipts imply and what the resampler used to assume."""
    clusters = {}
    for i, ob in enumerate(observations):
        if len(ob) >= 3:
            e, ok, inst = ob[0], ob[1], ob[2]
        else:
            e, ok, inst = ob[0], ob[1], f"#{i}"
        clusters.setdefault(inst, []).append((float(e), bool(ok)))
    return clusters


def _pct_bounds(sorted_values, rounds):
    """The 95% band as a pair of mirror order statistics.

    int(0.025*(n-1)) and int(0.975*(n-1)) are not mirror indices, so the
    band came out one position off-centre — and off-centre in the direction
    that certifies. A verdict must not depend on which of two runners is
    named first, so the two ends are taken the same distance from each end.
    """
    k = int(0.025 * rounds)
    return sorted_values[k], sorted_values[rounds - 1 - k]


def _jps(runs):
    wins = sum(1 for _, ok in runs if ok)
    return (sum(e for e, _ in runs) / wins) if wins else float("inf")


def bootstrap_jps(observations, rounds: int = BOOTSTRAP_ROUNDS):
    """A confidence interval for joules-per-success, resampled from the runs
    themselves rather than assumed.

    J/success is a ratio of two quantities that both move: the energy spent
    and how many attempts happened to succeed. Resampling keeps those two
    tied together, which a margin on the point estimate cannot do. A
    resample where nothing succeeds has no finite ratio, and is carried as
    infinity rather than dropped — discarding it would quietly flatter a
    runner that only sometimes succeeds.

    The unit of resampling is the INSTANCE, not the run. Instances are what
    the protocol issued and what differ in difficulty; two attempts at the
    same instance are not two independent draws from the epoch, and treating
    them as such narrows the interval on evidence that was never there.
    With one run per instance this is identical to resampling runs.

    observations: [(energy_joules, succeeded_bool[, instance_key]), ...]
    """
    import random
    clusters = _cluster(observations)
    keys = sorted(clusters)
    n = len(keys)
    if n == 0:
        return (0.0, float("inf"))
    rng = random.Random(BOOTSTRAP_SEED)
    ratios = []
    for _ in range(rounds):
        runs = []
        for _ in range(n):
            runs.extend(clusters[keys[rng.randrange(n)]])
        ratios.append(_jps(runs))
    ratios.sort()
    return _pct_bounds(ratios, rounds)


def paired_jps_delta_ci(obs_a, obs_b, rounds: int = BOOTSTRAP_ROUNDS):
    """95% interval for J/success(a) - J/success(b) when both runners faced
    the SAME issued instances.

    Instance difficulty is shared: a hard instance costs both runners. An
    unpaired comparison charges that shared difficulty to each runner
    separately and then asks whether two inflated intervals happen to miss
    each other. Drawing the instance set once and letting both runners face
    the same draw removes the part of the variation that belongs to the
    epoch rather than to either runner.

    A draw where NEITHER runner succeeds is a tie (0.0), not a dropped
    round: dropping it would flatter whichever runner more often has a
    finite ratio. Returns None when the two are not actually paired.
    """
    import random
    A, B = _cluster(obs_a), _cluster(obs_b)
    keys = sorted(set(A) & set(B))
    if not keys or set(A) != set(B):
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(keys)
    deltas = []
    for _ in range(rounds):
        draw = [keys[rng.randrange(n)] for _ in range(n)]
        ja = _jps([r for k in draw for r in A[k]])
        jb = _jps([r for k in draw for r in B[k]])
        if ja == float("inf") and jb == float("inf"):
            deltas.append(0.0)
        else:
            deltas.append(ja - jb)
    deltas.sort()
    return _pct_bounds(deltas, rounds)


def mcnemar_exact(obs_a, obs_b):
    """One-sided exact p for 'a succeeds on more of the issued instances
    than b', counting only the instances where they disagree.

    The instances they both pass and both fail say nothing about which is
    better; only the disagreements carry the comparison. Under the null each
    disagreement is a coin flip, so the p-value is an exact binomial tail —
    no resampling, no seed, no percentile approximation.

    Requires exactly one run per instance for both (a repeated instance has
    no single pass/fail to pair). Returns None when that does not hold.
    """
    A, B = _cluster(obs_a), _cluster(obs_b)
    if set(A) != set(B) or not A:
        return None
    if any(len(A[k]) != 1 or len(B[k]) != 1 for k in A):
        return None
    a_wins = sum(1 for k in A if A[k][0][1] and not B[k][0][1])
    b_wins = sum(1 for k in A if B[k][0][1] and not A[k][0][1])
    n = a_wins + b_wins
    if n == 0:
        return 1.0
    from math import comb
    tail = sum(comb(n, k) for k in range(0, b_wins + 1))
    return tail / (2 ** n)


PAIRED_ALPHA = 0.05


def distribution_cert(epoch_id, family_id, runner, code_hash, meter,
                      n_instances, attempts, successes, run_j, verify_j,
                      observations=None):
    """The frontier's input unit for challenge families (v0.3):
    not "solved one instance cheaply" but "processed the issued distribution
    at success rate q for X J per success". Verification energy is inside
    the cost (Constitution III is structural, not a deduction step)."""
    total = run_j + verify_j
    rate = successes / attempts if attempts else 0.0
    jps = (total / successes) if successes else float("inf")
    lo, hi = wilson_interval(successes, attempts)
    jps_lo, jps_hi = (bootstrap_jps(observations) if observations
                      else (None, None))
    return {
        "cert_id": f"{epoch_id[:8]}:{runner}#{code_hash[:6]}@{meter}",
        "epoch_id": epoch_id, "family_id": family_id,
        "runner": runner, "code_hash": code_hash, "meter": meter,
        "n_instances": n_instances, "attempts": attempts,
        "successes": successes, "success_rate": rate,
        "rate_ci95": [lo, hi],
        "run_j": run_j, "verify_j": verify_j, "total_j": total,
        "j_per_success": jps,
        "jps_ci95": [jps_lo, jps_hi],
        # Kept on the certificate so a later comparison can pair against it
        # instead of asking two separately-inflated intervals to miss.
        "observations": list(observations) if observations else None,
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




def certified_dominates(a, b) -> bool:
    """Uncertainty-aware dominance (audit H4). Point-estimate Pareto is the
    OBSERVED frontier; minting demands more: no-worse on both axes AND
    clearly-better beyond uncertainty on at least one."""
    if a["meter"] != b["meter"] or b["successes"] == 0:
        return False
    rate_ge = a["success_rate"] >= b["success_rate"]
    jps_le = a["j_per_success"] <= b["j_per_success"]
    if not (rate_ge and jps_le):
        return False
    return bool(certification_basis(a, b))


def _keyed(observations) -> bool:
    """True only when every observation names the instance it was measured
    on. Position in a list is not an identity: pairing by array index would
    invent the very structure the paired test is supposed to exploit, and
    would tighten an interval on a fiction."""
    return bool(observations) and all(len(ob) >= 3 for ob in observations)


def _paired(a, b):
    """The two certificates' per-instance observations, if and only if they
    are genuinely comparable pair-wise: same epoch, every observation keyed
    by its instance, and the same set of issued instances faced by both.
    Anything less is not a pairing and must fall back to the unpaired
    test."""
    if a.get("epoch_id") != b.get("epoch_id"):
        return None
    oa, ob = a.get("observations"), b.get("observations")
    if not _keyed(oa) or not _keyed(ob):
        return None
    if set(_cluster(oa)) != set(_cluster(ob)):
        return None
    return oa, ob


def _rate_separated(a, b) -> str:
    """Which instrument, if any, certifies that a's success rate beats b's."""
    pair = _paired(a, b)
    if pair is not None:
        p = mcnemar_exact(*pair)
        if p is not None and p < PAIRED_ALPHA:
            return (f"success-rate-certified (paired, McNemar exact "
                    f"p={p:.4f} over shared instances)")
    if a["rate_ci95"][0] >= b["rate_ci95"][1]:
        return "success-rate-certified (Wilson CI separation, unpaired)"
    return ""


def _jps_separated(a, b) -> str:
    """Which instrument, if any, certifies that a costs less per success.

    Paired first: when both certificates come from the same epoch and faced
    the same instances, the difference is measured on a shared draw and the
    epoch's own difficulty cancels. Only when that is unavailable does the
    unpaired interval separation apply, and only when THAT is unavailable
    does the flat protocol margin — which is not a confidence interval and
    is named as such."""
    pair = _paired(a, b)
    if pair is not None:
        ci = paired_jps_delta_ci(*pair)
        if ci is not None and ci[1] < 0:
            return (f"energy-certified (paired bootstrap, "
                    f"delta ci95 upper {ci[1]:.2f} < 0)")
    a_ci, b_ci = a.get("jps_ci95"), b.get("jps_ci95")
    if a_ci and b_ci and a_ci[1] is not None and b_ci[0] is not None:
        if a_ci[1] < b_ci[0]:
            return "energy-certified (bootstrap CI separation, unpaired)"
        return ""
    if a["j_per_success"] <= b["j_per_success"] * (1 - JPS_MARGIN):
        return "energy-margin-certified (protocol margin, not a CI)"
    return ""


def certification_basis(a, b) -> list:
    """Which axis certifies the dominance, and by which instrument — named
    honestly, because a paired test, an unpaired interval and a flat margin
    are three different claims about the same two numbers."""
    return [basis for basis in (_rate_separated(a, b), _jps_separated(a, b))
            if basis]


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
