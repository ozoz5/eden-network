# EDEN

> EDEN measures what intelligence makes unnecessary.
> This repository is a **single-node research prototype** of a protocol that
> is intended to become a network. Today it is one Mac and a SQLite file —
> the claims below are scoped accordingly.

Bitcoin proves work by burning energy. EDEN goes the opposite direction:

```text
Bitcoin:  Energy → Computation → Proof → Money
EDEN:     Task → Intelligence → Less Resource → Proof → Value
```

**EDEN mints on observed dominance, not counterfactual savings.**
Receipts record observed facts. The Pareto frontier of verified results is the
reference. New value is issued only when a record is actually broken — doing
ordinary work moves existing CREDIT; pushing the efficiency frontier is the
only thing that creates new CREDIT (1 CREDIT ≡ 1 certified joule is a v0
placeholder; cross-family valuation is an open problem in the spec).

## Constitution

1. **Observation Before Prediction** — predictions never justify issuance;
   minting is based on observations only.
2. **Result Before Efficiency** — no efficiency has value until the result is
   proven correct.
3. **Net Efficiency Only** — an improvement smaller than its own measurement,
   verification, and audit cost is not an improvement.
4. **Facts Outlive Rules** — receipts are immutable observations; frontier and
   minting rules are versioned interpretations that may change, but must never
   break recomputability from past facts.

## v0 pipeline

```text
task → run → measure → verify → receipt → frontier (read-only SELECT) → mint (--commit, simulated)
```

Single-file CLI (`eden.py`), Python stdlib only, SQLite ledger. Self-tests:

```bash
python3 -m unittest discover tests
```

### Requirements

- macOS or Linux (uses the Unix-only `resource` module; Windows is unsupported)
- Python ≥ 3.9, stdlib only
- Level V meter: macOS only (`powermetrics`; sudoers grant below)
- LLM runner: [ollama](https://ollama.com); default model `qwen2.5:7b`
  (~4.7 GB, pulled automatically on first use)

### Quickstart

```bash
python3 eden.py demo                     # top-k word-frequency family
python3 eden.py demo --scenario codefix  # code-fix family
```

## Measured on one machine (MacBook Pro M5 Pro, 2026-08-16 → 08-18 JST)

Sample sizes and meters are stated everywhere, because they change the story.
Real receipts from this ledger are committed under [`examples/`](examples/).

**Level S — `estimated-cpu-v1`** (child cpu-seconds × an *assumed* 6.0 W;
highly repeatable, systematically biased, blind to GPU/ANE):

```text
naive_count    n=10   5.680 J   σ 0.037 J (cv 0.7%)   # cpu-time repeatability, NOT energy accuracy
dict_loop      n=5    0.148 J
counter_fast   n=6    0.141 J
codefix_rules  n=5    0.343 J   ← code-fix frontier holder
codefix_brute  n=5    1.538 J
codefix_llm    n=3    2.439 J   # labeled lower bound in receipts (GPU invisible)
```

**Level V — `powermetrics-package-v1`** (CPU+GPU+ANE package power minus a
measured idle baseline):

```text
naive_count    n=10   mean 8.96 J    σ 3.52 J (cv 39%)
codefix_llm    n=5    mean 93.7 J    σ 53.0 J (cv 57%)   # + LLM output-length nondeterminism
```

What we can honestly claim from this ledger:

- **Same meter, same verified result**: the targeted rule-based fix
  (0.343 J) beats brute-force mutation search (1.538 J) by ~4.5× — tight
  intervals, certified dominance, one simulated mint of +0.998 CREDIT net of
  verification energy. This is not "rules beat LLMs": the rule runner carries
  the bug class as prior knowledge. What the ledger prices is **the joule
  value of knowing something** — here, knowing the fix pattern is worth
  ~1.2 J per task against blind search.
- **The LLM's real cost lives on the package meter**: ~51–159 J per verified
  fix (n=5, cv 57%), against a cpu-time-only apparent cost of ~2.4 J. Cpu-time
  metering misses roughly **20–60× of the energy** (GPU/ANE inference) — a
  range, not a constant. All 8 LLM attempts passed the 12-test suite.
- **Cross-meter ratios are not publishable.** Earlier revisions of this README
  claimed "200–450×" (LLM vs rules) and a "~9.3 W" calibration constant; an
  adversarial audit showed the former divided numbers from different meters
  and the latter was the minimum of n=3. Extending calibration to n=10 on a
  busy machine exploded cv to 39% — the "exclusive use" boundary condition is
  not decoration; without it, package-level measurement is noise.
  **σ really is EDEN's first research result.**
- A certified frontier update once minted **0 CREDIT** because the gain was
  smaller than verification energy (Constitution III), and a cheap-but-wrong
  runner got **no receipt** (Constitution II). Both under Level S.

## First challenge-sampled results (v0.2)

Frontiers must be "expected J over a distribution the protocol issues", not
"minimum J over instances you chose". `eden challenge open` pins enrolled
runner code hashes **before** generating instances (seeded bug injection into
a correct module; the epoch seed is recomputable from the ledger). First
epoch — 6 protocol-issued single-token bugs × 3 strategies:

```text
codefix_brute  6/6 (100%)   8.4 J total   →  1.41 J/success   [estimated]
codefix_rules  0/6 (  0%)   0.9 J total   →  ∞                [estimated]
codefix_llm    1/6 ( 17%)  893.9 J total  →  894 J/success    [Level V]
```

Three things this measured:

- **Cherry-picking was real.** On the hand-picked bug earlier in this README
  the LLM fixed 8/8; on the issued distribution it fixed 1/6. Self-chosen
  results do not predict distribution results — visible only after challenge
  sampling existed.
- **Failures are billed** (the §8 metric works): five failed LLM attempts
  burned 130–165 J each, so the true cost per verified success is ~894 J.
- **Specialist knowledge dies off-distribution**: the rule-based runner went
  0/6 (giving up honestly at 0.15 J per attempt).

Declared bias: the injected-bug vocabulary is a subset of the brute-force
searcher's mutation vocabulary, so this distribution structurally favors
search. The honest claim is "search dominates single-token bug
distributions", not "search beats LLMs". Harness validated: one failed
instance passed on manual replay (stochastic), two failed again (real).

**v0.3 — the frontier's input unit is now the distribution.** An epoch folds
into a Distribution Certificate (success rate with a Wilson 95% interval,
total joules with verification *inside* the cost, J/success), and the record
is a **Pareto frontier over (success rate ↑, J/success ↓)** per meter — a
100%/20J runner, a 95%/10J runner and a 60%/2J runner can all hold the record
at once; a 96%/8J newcomer dominates only the middle one. Minting happens at
certificate registration as a pure function of ledger order — a runner that
solves one instance miraculously cheaply cannot escape the cost of its other
five failures:

```text
★ brute  rate 100% [61,100]   1.59 J/success   ← frontier (estimated meter)
  rules  rate   0% [ 0, 39]   ∞                (dominated)
★ llm    rate  17% [ 3, 56]   894 J/success    ← frontier (Level V meter, genesis)
```

## The §9 experiment: intelligent frugality exists (v0.3, epoch cc846674)

Seven strategies, one protocol-issued distribution (12 instances, 8 distinct
single-token bugs), all failures billed, verification energy inside the cost,
every LLM measured on the package meter (Level V):

```text
strategy                     success   J/success (verify incl.)
cascade (rule→search→1.5b→7b) 12/12      1.37   ← sole Level V frontier holder
brute search                  12/12      1.53   (estimated meter)
phi4 14b                      11/12    287
qwen2.5:1.5b                   6/12     81
qwen2.5:7b                     5/12    391
qwen2.5:7b × 3 retries         5/12    404
targeted rule                  0/12      ∞
```

What this measured: **escalating-cheapest-first wins outright** on this
distribution (100% success at 1/210th of phi4's cost per success — the
original spec's "intelligent frugality" hypothesis, answered); **the small
model is 3.5–4.8× cheaper per verified success** than its bigger siblings
and Pareto-dominates the 7b outright; and **retries buy nothing against
systematic failures** — the 7b fails the same way every time, so three
attempts cost 3× for the same 5/12.

Declared bias, as always: the bug vocabulary is a subset of the searcher's
mutation vocabulary, so the cascade resolved everything in its cheap stages
(its LLM stages never fired). On a distribution that defeats search, these
numbers will look different — so we built that distribution next.

### The frontier inverted (epoch f7f0863a, semantic bugs)

Six semantic bug classes — population-vs-sample variance, unsorted median,
inverted mean, and friends — each **proven by test to be irreversible by any
single-token substitution**. Same seven strategies, same rules:

```text
strategy        success   J/success     (previous, token bugs)
phi4 14b         11/12    221   ← took the crown        (11/12, 287)
cascade           6/12    299   ← dominated by phi4     (12/12, 1.37 — was champion)
qwen2.5:1.5b      4/12    111   ← still cheapest/success (6/12, 81)
qwen2.5:7b        3/12    617                            (5/12, 391)
7b × 3 retries    3/12    742                            (5/12, 404)
brute search      0/12    ∞     ← extinct, as proven    (12/12, 1.53)
```

**The frontier is a property of the distribution, not of the strategy.**
Yesterday's champion is today's dominated entry; search went extinct on
schedule; the 1.5b kept the price-per-success crown on both distributions
and Pareto-dominated its own 7b sibling twice in a row; retries bought
nothing either time (systematic failures stay systematic). "Which
intelligence is efficient" has no distribution-free answer — and EDEN can
now measure that inversion in joules, with receipts, both ways.

## First independent replication (two nodes)

On 2026-08-18 a second machine (M1 MacBook Air, Python 3.9) ran the same
pipeline inside a signed, sandboxed relay job and its receipts were imported
into this ledger as explicitly unsigned claims. The family id derived
independently on both machines and matched exactly; so did every runner code
hash. Hardware-fingerprint stratification kept the two machines in separate
replication groups:

```text
counter_fast @M5 Pro  n=2  0.094 J        counter_fast @M1  n=2  0.128 J
dict_loop    @M5 Pro  n=2  0.097 J        dict_loop    @M1  n=2  0.139 J
naive_count  @M5 Pro  n=2  0.408 J        naive_count  @M1  n=2  0.595 J
```

Same code, ~1.4× the cpu-time on the older chip — the first measured data
point for the hardware-wave open problem in the spec.

## Measurement honesty

Every condition that decides whether a receipt group may hold a record or
trigger a mint lives in one auditable module, [`eligibility.py`](eligibility.py):

- Replication groups are `(runner, runner_code_hash, meter)` — a renamed or
  rewritten runner never inherits another implementation's σ, and receipts on
  different meter boundaries never share a scale.
- Protocol-assigned uncertainty (systematic) does **not** shrink with √n;
  only measured σ (n ≥ 3) does. Interval lower bounds clamp at 0.
- Dominance across meter boundaries is undefined; records need n ≥ 3.
- **ρ gate**: a group whose verification costs more than its run
  (ρ = E_verify/E_run > 1) can still take the record, but mints nothing —
  certification is history, minting is economics.
- Verification energy is measured with the same meter class as the run.
- `frontier` is read-only; issuance requires an explicit `--commit`, repeated
  transitions never re-mint.
- Checks the spec requires but v0.1 does not yet enforce (challenge sampling,
  independent replication, challenge audit) are reported as `pending` on
  every assessment — the gate cannot pretend they were checked.
- Raw observables (cpu-seconds, mW samples, model constants) are stored in
  every receipt so joules can be re-derived later (Constitution IV).
- **Tamper-evidence**: `eden chain build` maintains an append-only journal
  where every entry commits to the previous one; `eden chain verify`
  re-hashes every receipt body and every link. Edits are not impossible on
  a single node — they are *detectable*, and the chain head is anchored in
  this repository's public commit history.
- **Scope of the claim** (audit M8): EDEN measures *marginal in-window
  execution cost*. Challenge generation, model loads, warm-ups, downloads,
  idle power and the meter itself live outside the window — declared, not
  hidden. "Total physical resources" would be an overclaim.
- The cultural layer: `eden ore scan` — receipts are sealed by the seed of
  the first epoch opened after them (unchoosable randomness); rare hashes
  are OREs. No economic linkage, by constitution and by test. If OREs ever
  acquire market value, the protocol does not guarantee their fairness.
- `eden html` renders the ledger — frontiers, mints, ores — as one page.

### Level V setup (macOS, optional)

```bash
printf '%s\n' "$USER ALL=(ALL) NOPASSWD: /usr/bin/powermetrics -i 100 --samplers cpu_power, /usr/bin/powermetrics -i 100 -n 1 --samplers cpu_power" | sudo tee /etc/sudoers.d/powermetrics
sudo visudo -c -f /etc/sudoers.d/powermetrics   # must print "parsed OK"
```

This grants passwordless root for **exactly those two telemetry command
lines** and nothing else. Do not grant unrestricted
`NOPASSWD: /usr/bin/powermetrics` — its `-o/--output-file` flag would then
allow arbitrary root-owned file writes without a password. Remove the grant
with `sudo rm /etc/sudoers.d/powermetrics`.

## Related work (an honest map)

Measuring and rating AI efficiency is an occupied space: ML.ENERGY, the
AI Energy Score (Salesforce/Hugging Face), MLPerf Power. Paying for verified
efficiency improvements also exists: white-certificate energy markets,
efficiency-challenge prizes (NeurIPS LLM Efficiency Challenge). EDEN's
specific bet is narrower than "the position is empty": a **baseline-free
issuance rule** — immutable receipts of observed results, minting only on
certified Pareto-frontier updates, net of verification cost. Whether that is
novel enough is an open question tracked in the spec, not settled in this
tagline.

## Adversarial audit

On 2026-08-18 this repository was audited by four adversarial reviewers
(implementation, measurement statistics, protocol economics, publication).
Surviving findings, the fixes, and the retracted claims are recorded in
[EDEN設計書.md](EDEN設計書.md) (追補3), including open problems the protocol
has not solved: sandbagged genesis records, measurement-window gaming,
verifier-coevolution re-issuance, σ-assignment governance, and the honest
limitation that EDEN measures *marginal in-window resources*, not
"intelligence" as such.

## Specification

- [EDEN設計書.md](EDEN設計書.md) — current protocol spec (v2, Japanese)
- [EDEN設計書_v1_原本.md](EDEN設計書_v1_原本.md) — archived v1 (Constitution IV)
- English summary: TODO

## Status

Research prototype, single node, unsigned receipts, simulated mint.
Licensed under [Apache-2.0](LICENSE) — the explicit patent grant matters for a
measurement protocol with a hardware roadmap; the trademark exclusion (§6)
keeps the EDEN name and future certification marks separate from the code.
