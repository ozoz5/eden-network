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
  verification energy.
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

## Measurement honesty

- Frontier groups are `(runner, meter)` — receipts on different meter
  boundaries never share a σ.
- Protocol-assigned uncertainty (systematic) does **not** shrink with √n;
  only measured σ (n ≥ 3) does. Interval lower bounds clamp at 0.
- Verification energy is measured with the same meter class as the run.
- `frontier` is read-only; issuance requires an explicit `--commit`, repeated
  transitions never re-mint.
- Raw observables (cpu-seconds, mW samples, model constants) are stored in
  every receipt so joules can be re-derived later (Constitution IV).

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
License: TBD (will be chosen before any announcement).
