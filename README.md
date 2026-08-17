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
codefix_rules  (targeted fix)       0.343 J/success   ← frontier
codefix_brute  (mutation search)    1.538 J/success
codefix_llm    (qwen2.5:7b, 5/5)   57–159 J per fix   (Level V, GPU included)
```

The LLM fixes the bug reliably — at roughly 200–450× the energy of the
rule-based fix for the same verified result. Intelligence hierarchies are
visible in joules.

Notable observed behaviors:

- A frontier update was **certified but minted 0 CREDIT** because the gain was
  smaller than the verification energy — Constitution III firing on real data,
  marking the edge of EDEN's mintable domain (ρ = E_verify/E_run ≈ 1.9 at that
  frontier).
- A cheap-but-wrong runner (`bad_topk`) passes nothing and gets **no receipt**
  regardless of how few joules it burned (Constitution II).

### Measurement honesty

Two meter levels are implemented, and every receipt stores its raw
observables so joules can be re-derived later (Constitution IV):

- **Level S (estimated)**: child-process cpu-seconds × a declared, assumed
  watts constant. Blind to GPU/ANE — LLM joules recorded under this meter are
  labeled lower bounds inside the receipt.
- **Level V (os-counter)**: macOS `powermetrics` package power (CPU+GPU+ANE)
  sampled during the run, minus a measured idle baseline. Requires one-time
  passwordless sudo for `/usr/bin/powermetrics`:

  ```bash
  echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/powermetrics
  ```

Calibration findings on this machine: the assumed 6.0 W/cpu-s under-reports
package power (~9.3 W/cpu-s measured for a cpu-bound task), and cpu-time
metering under-reported LLM inference energy by **25–65×** (2.4 J apparent →
57–159 J measured). Upgrading the meter changed the story by two orders of
magnitude — which is exactly why receipts carry measurement profiles and
confidence instead of bare numbers.

## Specification

The full protocol design — receipt schema, frontier certificates, task-family
lifecycle, mint rules, open problems — lives in
[EDEN設計書.md](EDEN設計書.md) (Japanese).

## Status

Research prototype (v0). License: TBD.
