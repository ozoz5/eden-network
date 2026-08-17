# EDEN

> EDEN is a network that measures what intelligence makes unnecessary.

Bitcoin proves work by burning energy. EDEN goes the opposite direction:

```text
Bitcoin:  Energy → Computation → Proof → Money
EDEN:     Task → Intelligence → Less Resource → Proof → Value
```

**EDEN mints on observed dominance, not counterfactual savings.**
Receipts record observed facts. The Pareto frontier of verified results is the
reference. New value is issued only when a record is actually broken — doing
ordinary work moves existing CREDIT; pushing the efficiency frontier of
intelligence is the only thing that creates new CREDIT. R&D is mining, and the
difficulty is not tuned by anyone: physics, algorithms, and mathematics harden
the frontier on their own.

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

## v0 — minimal pipeline (this repository)

```text
task → run → measure → verify → receipt → frontier (SELECT) → mint (simulated)
```

Single-file CLI (`eden.py`), Python stdlib only, SQLite ledger. No blockchain,
no token, no wallet — by design (see the spec).

### Quickstart

```bash
python3 eden.py demo                     # top-k word-frequency family
python3 eden.py demo --scenario codefix  # code-fix family (LLM runner needs ollama)
```

Individual commands: `init`, `task create/list`, `run`, `verify`,
`receipt emit/show`, `calibrate`, `frontier`.

### Measured on one machine (MacBook Pro M5 Pro, 2026-08-16/17)

Repeatability first — EDEN's first research result is σ, not a currency:

```text
naive_count × 10:  mean 5.680 J  σ 0.037 J (cv 0.7%)
minimum certifiable single-run improvement at 2σ: 0.074 J
```

Code-fix family, joules per successful task (all runs, including failures):

```text
codefix_rules  (targeted fix)      0.343 J/success   ← frontier
codefix_brute  (mutation search)   1.538 J/success
codefix_llm    (qwen2.5:7b, 3/3)  ≥2.44 J/success   (lower bound, see below)
```

Notable observed behaviors:

- A frontier update was **certified but minted 0 CREDIT** because the gain was
  smaller than the verification energy — Constitution III firing on real data,
  marking the edge of EDEN's mintable domain (ρ = E_verify/E_run ≈ 1.9 at that
  frontier).
- A cheap-but-wrong runner (`bad_topk`) passes nothing and gets **no receipt**
  regardless of how few joules it burned (Constitution II).

### Measurement honesty

v0 measures at Level S (estimated): child-process cpu-seconds × a declared,
assumed watts constant. Raw cpu-seconds are stored in every receipt, so joules
can be re-derived when better meters exist (Constitution IV). Known and
declared blind spot: GPU/ANE inference energy (e.g. ollama on Apple Silicon)
is not captured by cpu-time sampling — those joules are recorded as lower
bounds, with the limitation written into the receipt's measurement profile.

## Specification

The full protocol design — receipt schema, frontier certificates, task-family
lifecycle, mint rules, open problems — lives in
[EDEN設計書.md](EDEN設計書.md) (Japanese).

## Status

Research prototype (v0). License: TBD.
