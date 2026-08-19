#!/usr/bin/env python3
"""EDEN v0 - Minimal Efficiency Receipt pipeline.

Implements the cut line of EDEN設計書.md §7:

    task -> run -> measure -> verify -> receipt -> frontier (SELECT) -> mint (simulated)

Constitution (§1) enforced in code:
  I   Observation Before Prediction: frontier and mint use observed receipts only.
  II  Result Before Efficiency:      receipts are issued only for PASS runs.
  III Net Efficiency Only:           certified gain subtracts verification energy.
  IV  Facts Outlive Rules:           receipts store raw observations (cpu seconds,
      meter model parameters); joules are derived and re-derivable later.

v0.1: two files on purpose — eden.py (pipeline) + eligibility.py (every
issuance condition, isolated so it can be audited and tested alone).
Python stdlib only. SQLite ledger.
"""

import argparse
import hashlib
import inspect
import json
import platform
import random
import re
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import challenge as challenge_mod
import eligibility
import identity as identity_mod
import journal as journal_mod
import ore as ore_mod

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "eden.db"
DATA_DIR = BASE / "data"
RUNNERS_DIR = BASE / "runners"

RECEIPT_VERSION = "eden-receipt/2"
# §2.1: fields that must never appear in a receipt (economic interpretation).
FORBIDDEN_RECEIPT_KEYS = ("baseline", "saved", "mint", "efficiency_ratio")
K_SIGMA = eligibility.K_SIGMA  # issuance rules live in eligibility.py (v0.1)


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(obj) -> str:
    """The signing preimage (TRUST_LAYER_DESIGN.md §2). allow_nan=False keeps
    Infinity/NaN out: Python emits them, RFC 8259 forbids them, and a
    signature no other language can re-verify is not a signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


# ---------------------------------------------------------------- measurement

class MeasurementAdapter:
    """Interface per 設計書 v1 §20 (start/stop/energy/confidence/method)."""

    def start(self): raise NotImplementedError
    def stop(self): raise NotImplementedError
    def energy_joules(self) -> float: raise NotImplementedError
    def cpu_seconds(self) -> float: raise NotImplementedError
    def wall_seconds(self) -> float: raise NotImplementedError
    def confidence(self) -> float: raise NotImplementedError
    def method(self) -> str: raise NotImplementedError
    def profile(self) -> dict: raise NotImplementedError


class EstimatedCpuAdapter(MeasurementAdapter):
    """Level S (estimated): child-process CPU time x assumed watts.

    cpu_seconds is a MEASURED fact (getrusage RUSAGE_CHILDREN delta).
    joules are DERIVED from an assumed constant; the constant is declared in
    the meter profile so receipts can be re-derived later (Constitution IV).
    """

    PROFILE_ID = "estimated-cpu-v1"
    METHOD = "estimated"
    WATTS_PER_CPU_SECOND = 6.0  # assumed active power per busy core; NOT measured
    ASSIGNED_CV = 0.15          # protocol-assigned relative uncertainty (fallback
                                # when a group has too few repeats to estimate sigma)
    CONFIDENCE = 0.4

    def start(self):
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._c0 = ru.ru_utime + ru.ru_stime
        self._t0 = time.monotonic()

    def stop(self):
        self._wall = time.monotonic() - self._t0
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._cpu = (ru.ru_utime + ru.ru_stime) - self._c0

    def cpu_seconds(self): return self._cpu
    def wall_seconds(self): return self._wall
    def energy_joules(self): return self._cpu * self.WATTS_PER_CPU_SECOND
    def confidence(self): return self.CONFIDENCE
    def method(self): return self.METHOD

    def profile(self) -> dict:
        return {
            "meter_profile_id": self.PROFILE_ID,
            "method": self.METHOD,
            "raw_observable": "child_cpu_seconds (getrusage RUSAGE_CHILDREN)",
            "watts_per_cpu_second_assumed": self.WATTS_PER_CPU_SECOND,
            "assigned_cv": self.ASSIGNED_CV,
            "confidence": self.CONFIDENCE,
        }


def _parse_cputime(text: str) -> float:
    """Parse ps cputime: [[DD-]HH:]MM:SS.ss -> seconds."""
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    parts = [float(x) for x in text.split(":")]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return days * 86400 + seconds


class OllamaCpuAdapter(EstimatedCpuAdapter):
    """Level S for local-LLM runners: child cpu + ollama daemon cpu delta.

    Inference happens inside the ollama daemon, not in our child process, so
    the daemon's cpu time is sampled (ps cputime) before and after the run.
    Boundary assumes a warm (already loaded) model and no concurrent daemon
    load; both assumptions are declared, not verified (Level S).
    """

    PROFILE_ID = "estimated-cpu+ollama-v1"
    ASSIGNED_CV = 0.25  # daemon sampling is coarser than child rusage
    BOUNDARY = "child-cpu + ollama-daemon-cpu-delta (warm model, exclusive use)"

    @staticmethod
    def _daemon_cpu() -> float:
        try:
            pids = subprocess.run(["pgrep", "ollama"], capture_output=True,
                                  text=True).stdout.split()
            total = 0.0
            for pid in pids:
                out = subprocess.run(["ps", "-o", "cputime=", "-p", pid],
                                     capture_output=True, text=True).stdout.strip()
                if out:
                    total += _parse_cputime(out)
            return total
        except (OSError, ValueError):
            return 0.0

    def start(self):
        self._d0 = self._daemon_cpu()
        super().start()

    def stop(self):
        super().stop()
        self._cpu += max(0.0, self._daemon_cpu() - self._d0)

    def profile(self) -> dict:
        p = super().profile()
        # Honest declaration: on Apple Silicon, ollama inference runs on the
        # GPU/ANE, whose energy is invisible to cpu-time sampling. These
        # joules are a LOWER BOUND until a Level V/P meter exists.
        p["limitation"] = "GPU/ANE energy not captured (cpu-time only); joules are a lower bound"
        return p


class PowermetricsAdapter(MeasurementAdapter):
    """Level V (OS counter): whole-package power via macOS powermetrics.

    Samples combined CPU+GPU+ANE power during the run, with a pre-roll window
    to estimate the idle baseline. Energy = (mean active power - mean idle
    power) x child wall time. Captures GPU/ANE, closing the LLM blind spot of
    cpu-time meters. Requires passwordless sudo for /usr/bin/powermetrics.

    Termination note: the root-owned powermetrics process cannot be signalled
    from a user process, so it writes to a pipe and exits on SIGPIPE when we
    close the read end. A reader thread drains the pipe during the run.
    """

    PROFILE_ID = "powermetrics-package-v1"
    METHOD = "os-counter"
    ASSIGNED_CV = 0.10
    CONFIDENCE = 0.7
    BOUNDARY = ("system-package power (CPU+GPU+ANE) minus measured idle "
                "baseline; exclusive use assumed")
    INTERVAL_MS = 100
    MIN_IDLE_SAMPLES = 5   # audit fix: 0.5s preroll landed only 2 samples
    PREROLL_MAX_S = 2.0

    def _reader(self):
        try:
            for line in self._proc.stdout:
                if "Combined Power" in line:
                    try:
                        mw = float(line.rsplit(":", 1)[1].strip().split()[0])
                        self._samples.append((time.monotonic(), mw))
                    except (ValueError, IndexError):
                        pass
        except ValueError:
            pass  # pipe closed by stop()

    def start(self):
        self._samples = []
        self._proc = subprocess.Popen(
            ["sudo", "-n", "/usr/bin/powermetrics", "-i",
             str(self.INTERVAL_MS), "--samplers", "cpu_power"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        # Adaptive preroll: wait for a real idle baseline, not a fixed sleep.
        deadline = time.monotonic() + self.PREROLL_MAX_S
        while (len(self._samples) < self.MIN_IDLE_SAMPLES
               and time.monotonic() < deadline
               and self._proc.poll() is None):
            time.sleep(0.05)
        if self._proc.poll() is not None:
            sys.exit("error: powermetrics unavailable. Grant passwordless "
                     "sudo:\n  echo \"$USER ALL=(ALL) NOPASSWD: "
                     "/usr/bin/powermetrics\" | sudo tee "
                     "/etc/sudoers.d/powermetrics")
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._c0 = ru.ru_utime + ru.ru_stime
        self._t0 = time.monotonic()

    def stop(self):
        self._t_end = time.monotonic()
        self._wall = self._t_end - self._t0
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._cpu = (ru.ru_utime + ru.ru_stime) - self._c0
        time.sleep(self.INTERVAL_MS / 1000 * 1.5)  # let the last sample land
        try:
            self._proc.stdout.close()  # next write -> SIGPIPE -> exit
        except OSError:
            pass
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        self._idle = [mw for t, mw in self._samples if t < self._t0]
        self._active = [mw for t, mw in self._samples
                        if self._t0 <= t <= self._t_end + self.INTERVAL_MS / 1000]
        self._mean_idle = sum(self._idle) / len(self._idle) if self._idle else 0.0
        self._mean_active = (sum(self._active) / len(self._active)
                             if self._active else 0.0)
        if self._active:
            watts = max(0.0, self._mean_active - self._mean_idle) / 1000.0
            self._energy = watts * self._wall
            self._fallback = False
        else:
            # run shorter than the sampling interval: fall back to Level S
            self._energy = self._cpu * EstimatedCpuAdapter.WATTS_PER_CPU_SECOND
            self._fallback = True

    def cpu_seconds(self): return self._cpu
    def wall_seconds(self): return self._wall
    def energy_joules(self): return self._energy
    def confidence(self): return 0.4 if self._fallback else self.CONFIDENCE
    def method(self): return "estimated" if self._fallback else self.METHOD

    def profile(self) -> dict:
        # Audit fix: a fallback measurement is an ESTIMATED measurement and
        # must carry a distinct profile id so grouping never mixes it with
        # real package-power receipts.
        return {
            "meter_profile_id": ("estimated-cpu-pmfallback-v1" if self._fallback
                                 else self.PROFILE_ID),
            "method": self.method(),
            "raw_observable": "powermetrics Combined Power (CPU+GPU+ANE) mW "
                              f"@ {self.INTERVAL_MS}ms + child cpu_seconds",
            "interval_ms": self.INTERVAL_MS,
            "mean_active_mw": round(self._mean_active, 1),
            "mean_idle_mw": round(self._mean_idle, 1),
            "n_samples_active": len(self._active),
            "n_samples_idle": len(self._idle),
            "fallback_to_estimated": self._fallback,
            "assigned_cv": (EstimatedCpuAdapter.ASSIGNED_CV if self._fallback
                            else self.ASSIGNED_CV),
            "confidence": self.confidence(),
        }


def powermetrics_available() -> bool:
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/powermetrics", "-i", "100", "-n", "1",
             "--samplers", "cpu_power"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


EstimatedCpuAdapter.BOUNDARY = None
METERS = {
    "estimated": EstimatedCpuAdapter,
    "ollama": OllamaCpuAdapter,
    "powermetrics": PowermetricsAdapter,
}


def run_measured(cmd: list, cwd=None, meter: str = "estimated") -> dict:
    """Run a child process wrapped in a measurement adapter."""
    adapter = METERS[meter]()
    adapter.start()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    adapter.stop()
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cpu_seconds": adapter.cpu_seconds(),
        "wall_seconds": adapter.wall_seconds(),
        "energy_joules": adapter.energy_joules(),
        "adapter": adapter,
    }


# ------------------------------------------------------------------- verifier

def reference_topk(words, k):
    """Reference implementation used by the verifier (exact-match quality).

    Deterministic tie-break: higher count first, then lexicographic word.
    The source code of this function is part of the verifier spec hash.
    """
    counts = Counter(words)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [[w, c] for w, c in ranked[:k]]


VERIFIER_ID = "ref-exact-v1"
VERIFIER_ID_TESTS = "unittest-v1"


def verifier_spec_hash(spec=None) -> str:
    """Verifier identity. code-fix: hash of the test suite. topk: reference source."""
    if spec is not None and spec.get("task_type") == "code-fix":
        test_bytes = (BASE / spec["test_file"]).read_bytes()
        return sha(test_bytes + b"|tests-pass")[:16]
    return sha(inspect.getsource(reference_topk) + "|exact-match")[:16]


# ------------------------------------------------------------------------ db

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  task_instance_id TEXT PRIMARY KEY,
  family_id TEXT NOT NULL,
  task_contract_version TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  input_path TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  verifier_spec_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL,
  runner_id TEXT NOT NULL,
  runner_code_hash TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL,
  output_json TEXT,
  output_hash TEXT
);
CREATE TABLE IF NOT EXISTS measurements(
  run_id TEXT PRIMARY KEY,
  method TEXT NOT NULL,
  meter_profile_json TEXT NOT NULL,
  energy_boundary TEXT NOT NULL,
  cpu_seconds REAL NOT NULL,
  wall_seconds REAL NOT NULL,
  energy_joules REAL NOT NULL,
  confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications(
  run_id TEXT PRIMARY KEY,
  verifier_id TEXT NOT NULL,
  verifier_spec_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  score REAL NOT NULL,
  verify_cpu_seconds REAL NOT NULL,
  verify_energy_joules REAL NOT NULL,
  verified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts(
  receipt_id TEXT PRIMARY KEY,
  run_id TEXT UNIQUE NOT NULL,
  family_id TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  receipt_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frontier_state(
  family_id TEXT PRIMARY KEY,
  group_key TEXT NOT NULL,
  n INTEGER NOT NULL,
  mean_j REAL NOT NULL,
  low_j REAL NOT NULL,
  high_j REAL NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mints(
  mint_id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id TEXT NOT NULL,
  prev_group TEXT NOT NULL,
  new_group TEXT NOT NULL,
  prev_low_j REAL NOT NULL,
  new_high_j REAL NOT NULL,
  verify_energy_j REAL NOT NULL,
  certified_gain_j REAL NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS epochs(
  epoch_id TEXT PRIMARY KEY,
  family_id TEXT NOT NULL,
  epoch_no INTEGER NOT NULL,
  seed TEXT NOT NULL,
  n_instances INTEGER NOT NULL,
  gen_spec_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrollments(
  epoch_id TEXT NOT NULL,
  runner_id TEXT NOT NULL,
  runner_code_hash TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  PRIMARY KEY(epoch_id, runner_id)
);
CREATE TABLE IF NOT EXISTS epoch_instances(
  epoch_id TEXT NOT NULL,
  instance_index INTEGER NOT NULL,
  task_instance_id TEXT NOT NULL,
  bug_desc TEXT NOT NULL,
  PRIMARY KEY(epoch_id, instance_index)
);
CREATE TABLE IF NOT EXISTS epoch_runs(
  epoch_id TEXT NOT NULL,
  run_id TEXT PRIMARY KEY,
  instance_index INTEGER NOT NULL,
  runner_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chain(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT UNIQUE NOT NULL,
  entry_hash TEXT NOT NULL,
  prev_chain TEXT NOT NULL,
  chain_hash TEXT NOT NULL,
  chained_at TEXT NOT NULL,
  entry_type TEXT,
  hash_rule TEXT,
  entry_body TEXT
);
CREATE TABLE IF NOT EXISTS nodes(
  node_id TEXT PRIMARY KEY,
  public_key TEXT NOT NULL,
  label TEXT,
  registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications_independent(
  vr_id TEXT PRIMARY KEY,
  receipt_id TEXT NOT NULL,
  receipt_hash TEXT NOT NULL,
  verifier_spec_hash TEXT NOT NULL,
  verdict TEXT NOT NULL,
  node_id TEXT NOT NULL,
  hw_fingerprint TEXT NOT NULL,
  trust_basis TEXT NOT NULL,
  vr_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints(
  chain_head TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  node_id TEXT NOT NULL,
  signature TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ores(
  ore_hash TEXT PRIMARY KEY,
  receipt_id TEXT NOT NULL,
  epoch_id TEXT NOT NULL,
  zero_bits INTEGER NOT NULL,
  tier TEXT NOT NULL,
  discovered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distribution_certs(
  cert_id TEXT PRIMARY KEY,
  epoch_id TEXT NOT NULL,
  family_id TEXT NOT NULL,
  runner_id TEXT NOT NULL,
  runner_code_hash TEXT NOT NULL,
  meter TEXT NOT NULL,
  n_instances INTEGER NOT NULL,
  attempts INTEGER NOT NULL,
  successes INTEGER NOT NULL,
  success_rate REAL NOT NULL,
  rate_lo REAL NOT NULL,
  rate_hi REAL NOT NULL,
  run_j REAL NOT NULL,
  verify_j REAL NOT NULL,
  total_j REAL NOT NULL,
  j_per_success REAL,
  created_at TEXT NOT NULL
);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Small pages keep a fresh ledger compact (matters inside sandboxes that
    # cap file sizes, e.g. the 128KB RLIMIT_FSIZE of TwinLoop shadow jobs).
    # Only takes effect when the database is newly created.
    conn.execute("PRAGMA page_size=1024")
    conn.executescript(SCHEMA)
    for col in ("randomness_source", "randomness_value", "commitment_hash"):
        try:
            conn.execute(f"ALTER TABLE epochs ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
    # The journal predates non-receipt entries; renaming the columns leaves
    # every stored value and every chain hash untouched.
    for old, new in (("receipt_id", "entry_id"), ("receipt_hash", "entry_hash")):
        try:
            conn.execute(f"ALTER TABLE chain RENAME COLUMN {old} TO {new}")
        except sqlite3.OperationalError:
            pass
    for col in ("trust_state",):
        try:
            conn.execute(f"ALTER TABLE receipts ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    for col in ("entry_type", "hash_rule", "entry_body"):
        try:
            conn.execute(f"ALTER TABLE chain ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    return conn


# ----------------------------------------------------------------------- task

def generate_corpus(gen: dict) -> str:
    rnd = random.Random(gen["seed"])
    vocab = [f"w{i:04d}" for i in range(gen["vocab"])]
    weights = [1.0 / (i + 1) ** gen["zipf"] for i in range(gen["vocab"])]
    words = rnd.choices(vocab, weights=weights, k=gen["tokens"])
    return " ".join(words)


def family_id_of(spec: dict) -> str:
    """§4: family_id is derived mechanically, never self-declared.

    topk: the generator SEED is excluded (it identifies the instance).
    code-fix: the verifier spec (test suite) carries the family identity.
    """
    if spec.get("task_type") == "code-fix":
        material = "|".join([
            spec["task_contract_version"],
            verifier_spec_hash(spec),
            spec["input_schema"],
            "code-fix",
            spec.get("bug_mode", "token"),                      # audit C3
            challenge_mod.generator_fingerprint(),               # audit C3
            sha((BASE / spec["correct_source"]).read_bytes())[:16]
            if "correct_source" in spec else
            sha((BASE / spec["source_file"]).read_bytes())[:16],
            spec["quality"]["type"],
            spec["resource_boundary_profile"],
        ])
    else:
        gen = dict(spec["generator"])
        gen.pop("seed", None)
        material = "|".join([
            spec["task_contract_version"],
            verifier_spec_hash(spec),
            spec["input_schema"],
            canonical(gen),
            sha(inspect.getsource(generate_corpus))[:16],        # audit C3
            spec["quality"]["type"],
            spec["resource_boundary_profile"],
        ])
    return sha(material)[:16]


def cmd_task_create(spec_path: str):
    spec = json.loads(Path(spec_path).read_text())
    fam = family_id_of(spec)

    if spec.get("task_type") == "code-fix":
        src_path = BASE / spec["source_file"]
        input_hash = sha(src_path.read_bytes())[:16]
        task_id = sha(fam + input_hash)[:16]
        input_path = src_path  # the buggy source itself is the input
    else:
        corpus = generate_corpus(spec["generator"])
        input_hash = sha(corpus)[:16]
        task_id = sha(fam + str(spec["generator"]["seed"]) + input_hash)[:16]
        DATA_DIR.mkdir(exist_ok=True)
        input_path = DATA_DIR / f"{task_id}.txt"
        if not input_path.exists():
            input_path.write_text(corpus)

    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?,?)",
        (task_id, fam, spec["task_contract_version"], canonical(spec),
         str(input_path), input_hash, verifier_spec_hash(spec), now_iso()),
    )
    conn.commit()
    print(f"task_instance_id: {task_id}")
    print(f"family_id:        {fam}")
    print(f"input:            {input_path.name}  hash={input_hash}")
    print(f"verifier_spec:    {verifier_spec_hash(spec)}")
    return task_id


def resolve_task(conn, prefix: str):
    rows = conn.execute(
        "SELECT * FROM tasks WHERE task_instance_id LIKE ?", (prefix + "%",)
    ).fetchall()
    if not rows:
        sys.exit(f"error: no task matching '{prefix}' (run: eden task create <spec.json>)")
    if len(rows) > 1:
        sys.exit(f"error: ambiguous task prefix '{prefix}' ({len(rows)} matches)")
    return rows[0]


# ------------------------------------------------------------------------ run

def cmd_run(task_prefix: str, runner: str, repeat: int, chain: bool = True,
            meter: str = None):
    conn = db()
    task = resolve_task(conn, task_prefix)
    runner_path = RUNNERS_DIR / f"{runner}.py"
    if not runner_path.exists():
        available = sorted(p.stem for p in RUNNERS_DIR.glob("*.py"))
        sys.exit(f"error: runner '{runner}' not found. available: {', '.join(available)}")
    runner_hash = sha(runner_path.read_bytes())[:16]
    spec = json.loads(task["spec_json"])
    if spec.get("task_type") == "code-fix":
        extra = [str(BASE / spec["test_file"]), spec["module_name"]]
    else:
        extra = [str(spec["k"])]
    # LLM runners burn energy in the ollama daemon and on the GPU/ANE.
    # Prefer the Level V package meter when available; else daemon-cpu Level S.
    if meter is None:
        if "llm" in runner:
            meter = "powermetrics" if powermetrics_available() else "ollama"
        else:
            meter = "estimated"

    run_ids = []
    for i in range(repeat):
        started = now_iso()
        result = run_measured(
            [sys.executable, str(runner_path), task["input_path"], *extra],
            meter=meter,
        )
        status = "DONE" if result["returncode"] == 0 else "ERROR"
        output_json, output_hash = None, None
        if status == "DONE":
            try:
                output_json = canonical(json.loads(result["stdout"]))
                output_hash = sha(output_json)[:16]
            except json.JSONDecodeError:
                status = "ERROR"
        run_id = sha(task["task_instance_id"] + runner + started + str(i)
                     + str(result["cpu_seconds"])
                     + str(time.monotonic_ns()))[:16]
        conn.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, task["task_instance_id"], runner, runner_hash,
             started, now_iso(), status, output_json, output_hash),
        )
        adapter = result["adapter"]
        conn.execute(
            "INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?)",
            (run_id, adapter.method(), canonical(adapter.profile()),
             adapter.BOUNDARY or spec["resource_boundary_profile"],
             result["cpu_seconds"], result["wall_seconds"],
             result["energy_joules"], adapter.confidence()),
        )
        conn.commit()
        print(f"run {run_id}  runner={runner}  status={status}  "
              f"E={result['energy_joules']:.3f} J  cpu={result['cpu_seconds']:.3f} s")
        if status == "ERROR":
            print(f"  stderr: {result['stderr'].strip()[:200]}")
        run_ids.append(run_id)
        if chain and status == "DONE":
            v = cmd_verify(run_id, conn)
            if v == "PASS":
                cmd_receipt_emit(run_id, conn, quiet=True)
    return run_ids


# --------------------------------------------------------------------- verify

def cmd_verify(run_id_prefix: str, conn=None) -> str:
    conn = conn or db()
    run = conn.execute(
        "SELECT * FROM runs WHERE run_id LIKE ?", (run_id_prefix + "%",)
    ).fetchone()
    if run is None:
        sys.exit(f"error: no run matching '{run_id_prefix}'")
    task = conn.execute(
        "SELECT * FROM tasks WHERE task_instance_id=?", (run["task_instance_id"],)
    ).fetchone()
    spec = json.loads(task["spec_json"])

    # Verification is real work in a measured child process, so verification
    # energy is observed (§III). Audit fix: verify with the SAME meter class
    # as the run, so Constitution III never subtracts across meter scales.
    m = conn.execute(
        "SELECT method FROM measurements WHERE run_id=?", (run["run_id"],)
    ).fetchone()
    v_meter = ("powermetrics" if (m and m["method"] == "os-counter"
                                  and powermetrics_available()) else "estimated")

    if spec.get("task_type") == "code-fix":
        verifier_id = VERIFIER_ID_TESTS
        status, result = "FAIL", None
        if run["status"] == "DONE" and run["output_json"]:
            source = json.loads(run["output_json"]).get("source", "")
            test_path = BASE / spec["test_file"]
            with tempfile.TemporaryDirectory() as td:
                Path(td, spec["module_name"] + ".py").write_text(source)
                shutil.copy(test_path, Path(td) / test_path.name)
                result = run_measured(
                    [sys.executable, "-m", "unittest", test_path.stem, "-v"],
                    cwd=td, meter=v_meter,
                )
            status = "PASS" if result["returncode"] == 0 else "FAIL"
        if result is None:  # runner produced nothing verifiable
            result = {"cpu_seconds": 0.0, "energy_joules": 0.0}
    else:
        verifier_id = VERIFIER_ID
        result = run_measured(
            [sys.executable, str(BASE / "eden.py"), "_refverify",
             task["input_path"], str(spec["k"])],
            meter=v_meter,
        )
        expected = canonical(json.loads(result["stdout"]))
        status = ("PASS" if (run["output_json"] == expected
                             and run["status"] == "DONE") else "FAIL")
    conn.execute(
        "INSERT OR REPLACE INTO verifications VALUES (?,?,?,?,?,?,?,?)",
        (run["run_id"], verifier_id, task["verifier_spec_hash"], status,
         1.0 if status == "PASS" else 0.0,
         result["cpu_seconds"], result["energy_joules"], now_iso()),
    )
    conn.commit()
    print(f"verify {run['run_id']}  {status}  "
          f"E_verify={result['energy_joules']:.3f} J")
    return status


# -------------------------------------------------------------------- receipt

def build_receipt(conn, run_id: str):
    row = conn.execute(
        """SELECT r.*, t.family_id, t.task_contract_version, t.input_hash,
                  t.spec_json,
                  m.meter_profile_json, m.energy_boundary, m.cpu_seconds,
                  m.wall_seconds, m.energy_joules, m.confidence,
                  v.status AS v_status, v.score, v.verifier_id,
                  v.verifier_spec_hash AS v_spec,
                  v.verify_cpu_seconds, v.verify_energy_joules
           FROM runs r
           JOIN tasks t ON t.task_instance_id = r.task_instance_id
           JOIN measurements m ON m.run_id = r.run_id
           JOIN verifications v ON v.run_id = r.run_id
           WHERE r.run_id = ?""",
        (run_id,),
    ).fetchone()
    if row is None:
        sys.exit(f"error: run '{run_id}' lacks measurement or verification")
    if row["v_status"] != "PASS":
        # Constitution II: no receipt without a proven result.
        return None
    meter = json.loads(row["meter_profile_json"])
    spec = json.loads(row["spec_json"])
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "family_id": row["family_id"],
        "task_instance_id": row["task_instance_id"],
        "task_contract_version": row["task_contract_version"],
        "input_hash": row["input_hash"],
        "output_hash": row["output_hash"],
        "result": {
            "quality_metric": spec["quality"]["type"],
            "status": "PASS",
            "score": row["score"],
        },
        "run_energy": {
            "cpu_seconds": row["cpu_seconds"],        # raw observation
            "wall_seconds": row["wall_seconds"],      # raw observation
            "energy_joules": row["energy_joules"],    # derived (see meter profile)
        },
        "verification_energy": {
            "cpu_seconds": row["verify_cpu_seconds"],
            "energy_joules": row["verify_energy_joules"],
        },
        "energy_boundary": row["energy_boundary"],
        "measurement_profile": meter,
        "uncertainty_profile": {
            "assigned_cv": meter["assigned_cv"],
            "assignment": "protocol-assigned per meter profile; group sigma "
                          "replaces it when >=3 replications exist",
        },
        "verifier_spec_hash": row["v_spec"],
        "runner_id": row["runner_id"],
        "runner_code_hash": row["runner_code_hash"],
        "meter_id": meter["meter_profile_id"],
        "verifier_id": row["verifier_id"],
        "hardware_profile": {
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "timestamp": row["completed_at"],
    }
    # Signed over the body WITHOUT this field, so verification can reproduce
    # the preimage by removing it again.
    receipt["signatures"] = _sign_receipt_body(receipt)
    # §2.1 invariant: economic interpretation must never enter a receipt.
    # Audit fix: raise (assert vanishes under -O) and match KEY NAMES exactly
    # (substring matching crashed on legitimate values like runner_id="baseline").
    _check_forbidden(receipt)
    return receipt


def _sign_receipt_body(body: dict) -> list:
    """Sign the receipt minus its own signatures (TRUST_LAYER_DESIGN.md §2).

    A missing key is not an error: measurement exists before trust does, and
    the receipt simply stays UNSIGNED rather than not existing."""
    try:
        pub = identity_mod.public_key()
        sig = identity_mod.sign(canonical(body), identity_mod.NS_RECEIPT)
    except (identity_mod.SigningUnavailable, OSError):
        return []
    return [{
        "role": "runner+meter+verifier",
        "role_collapse": True,   # one node, one key: a collapse, not a merger
        "node_id": identity_mod.node_id_of(pub),
        "alg": "sshsig-ed25519",
        "namespace": identity_mod.NS_RECEIPT,
        "signature": sig,
    }]


def _check_forbidden(obj, path="receipt"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_RECEIPT_KEYS:
                raise ValueError(f"forbidden field '{path}.{k}' in receipt (§2.1)")
            _check_forbidden(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_forbidden(v, f"{path}[{i}]")


def cmd_receipt_emit(run_id_prefix: str, conn=None, quiet=False):
    conn = conn or db()
    run = conn.execute(
        "SELECT run_id FROM runs WHERE run_id LIKE ?", (run_id_prefix + "%",)
    ).fetchone()
    if run is None:
        sys.exit(f"error: no run matching '{run_id_prefix}'")
    receipt = build_receipt(conn, run["run_id"])
    if receipt is None:
        print(f"receipt refused for {run['run_id']}: verification is not PASS "
              "(Constitution II: Result Before Efficiency)")
        return None
    rj = canonical(receipt)
    rhash = sha(rj)[:16]
    conn.execute(
        "INSERT OR IGNORE INTO receipts(receipt_id, run_id, family_id, "
        "receipt_json, receipt_hash, created_at, trust_state) "
        "VALUES (?,?,?,?,?,?,?)",
        (rhash, run["run_id"], receipt["family_id"], rj, rhash, now_iso(),
         "SIGNED" if receipt.get("signatures") else "LOCAL"),
    )
    conn.commit()
    if not quiet:
        print(json.dumps(receipt, indent=2))
        print(f"receipt_hash: {rhash}")
    return rhash


def cmd_import(path: str):
    """Import foreign receipts (e.g. from another node's shadow run).

    v0.4 honesty: imported receipts are UNSIGNED claims — the receipt's
    declared hardware profile separates them into their own replication
    groups, but nothing yet proves the claim (data-integrity: still open).
    """
    conn = db()
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict):
        payload = [payload]
    added = 0
    for rec in payload:
        _check_forbidden(rec)
        rj = canonical(rec)
        rhash = sha(rj)[:16]
        cur = conn.execute(
            "INSERT OR IGNORE INTO receipts(receipt_id, run_id, family_id, "
            "receipt_json, receipt_hash, created_at, trust_state) "
            "VALUES (?,?,?,?,?,?,?)",
            (rhash, "ext-" + rhash, rec["family_id"], rj, rhash, now_iso(),
             "UNSIGNED"),
        )
        added += cur.rowcount
    conn.commit()
    print(f"imported {added} foreign receipts ({len(payload) - added} already known)")
    print("status: QUARANTINED — stored as unsigned claims, excluded from "
          "frontier/certification until signature+attestation exist (audit C2)")


def cmd_receipt_show(run_id_prefix: str):
    conn = db()
    row = conn.execute(
        """SELECT rc.* FROM receipts rc JOIN runs r ON r.run_id = rc.run_id
           WHERE r.run_id LIKE ?""", (run_id_prefix + "%",)
    ).fetchone()
    if row is None:
        sys.exit(f"error: no receipt for run '{run_id_prefix}'")
    print(json.dumps(json.loads(row["receipt_json"]), indent=2))
    print(f"receipt_hash: {row['receipt_hash']}")


# ------------------------------------------------------------------- frontier

def group_stats(conn, family_id: str):
    """Frontier input = receipts only (Constitution I).

    All grouping and interval rules live in eligibility.py (v0.1) — this is
    just the ledger read plus delegation.
    """
    rows = conn.execute(
        "SELECT run_id, receipt_json, trust_state FROM receipts "
        "WHERE family_id=?", (family_id,)).fetchall()
    admitted = []
    for r in rows:
        rec = json.loads(r["receipt_json"])
        state = r["trust_state"] or trust_state_of(conn, rec, r["run_id"])
        if _admits_to_frontier(state, r["run_id"]):
            admitted.append(rec)
    return eligibility.group_stats(admitted)


# What the trust layer is FOR: the economic layer has to consult it, or the
# tiers are decoration (design §12.2).
FRONTIER_ADMISSION = {
    # local receipts: this ledger's own pipeline, honest about being unsigned
    "LOCAL": True,
    "SIGNED": True,
    "VERIFIED": True,
    # a signature that does not verify is a failed claim, not a measurement
    "INVALID": False,
    # imported and unsigned: kept as observation, never priced
    "UNSIGNED": False,
}


def _admits_to_frontier(state: str, run_id: str) -> bool:
    if not FRONTIER_ADMISSION.get(state, False):
        return False
    # A foreign receipt needs a signature to be admitted at all: LOCAL is a
    # claim only this ledger's own pipeline is entitled to make.
    if run_id.startswith("ext-") and state == "LOCAL":
        return False
    return True


def admits_to_record(state: str) -> bool:
    """Holding a record is a stronger claim than appearing on the chart:
    an imported result must have been reproduced elsewhere (VERIFIED)."""
    return state in ("LOCAL", "SIGNED", "VERIFIED")


def _set_state(conn, fam, g):
    conn.execute(
        "INSERT INTO frontier_state VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(family_id) DO UPDATE SET group_key=excluded.group_key, "
        "n=excluded.n, mean_j=excluded.mean_j, low_j=excluded.low_j, "
        "high_j=excluded.high_j, updated_at=excluded.updated_at",
        (fam, g["group"], g["n"], g["mean"], g["low"], g["high"], now_iso()),
    )


def cmd_frontier(task_prefix: str, commit: bool = False):
    """Analysis is read-only by default. --commit mutates frontier_state/mints
    (audit fix: issuance must be an explicit act, not a side effect of asking).
    """
    conn = db()
    task = resolve_task(conn, task_prefix)
    fam = task["family_id"]
    groups = group_stats(conn, fam)
    if not groups:
        print(f"family {fam}: no receipts yet. frontier is empty.")
        return

    print(f"family {fam}  (groups = runner@meter; assigned-cv intervals do not "
          f"shrink with n)")
    for g in groups:
        print(f"  {g['group']:<40} n={g['n']:<3} E={g['mean']:8.3f} J  "
              f"[{g['low']:.3f}, {g['high']:.3f}]  ρ={g['verify_mean']/g['mean']:.2f}")
    if not commit:
        print("\n  (analysis only — use --commit to update frontier state / mint)")

    candidate = groups[0]
    state = conn.execute(
        "SELECT * FROM frontier_state WHERE family_id=?", (fam,)
    ).fetchone()

    if state is None:
        if not commit:
            return
        rec = eligibility.assess_record(candidate)
        if not rec["eligible"]:
            print(f"\n  no record established: {candidate['group']} — "
                  + "; ".join(rec["reasons"]))
            return
        _set_state(conn, fam, candidate)
        conn.commit()
        print()
        print("  " + "=" * 52)
        print(f"  FIRST RECORD   family={fam}")
        print(f"  {candidate['group']}: {candidate['mean']:.3f} J  "
              f"[{candidate['low']:.3f}, {candidate['high']:.3f}]  n={candidate['n']}")
        print("  (unaudited genesis — mint baseline integrity is an open "
              "problem, see 設計書 §6; pending checks: "
              + ", ".join(rec["pending"]) + ")")
        print("  " + "=" * 52)
        return

    holder = next((g for g in groups if g["group"] == state["group_key"]), None)
    if holder is None:
        # Audit fix: the recorded holder group no longer exists in the ledger.
        # Re-establish state explicitly instead of silently corrupting it.
        print(f"\n  frontier holder '{state['group_key']}' has no receipts; "
              f"re-establishing record at {candidate['group']}")
        if commit:
            _set_state(conn, fam, candidate)
            conn.commit()
        return
    if candidate["group"] == holder["group"]:
        if commit:
            _set_state(conn, fam, holder)
            conn.commit()
        print(f"\n  frontier unchanged: {holder['group']} "
              f"[{holder['low']:.3f}, {holder['high']:.3f}] J")
        return

    # All certification and minting conditions live in eligibility.py (v0.1).
    verdict = eligibility.assess_transition(holder, candidate)
    if not verdict["certifiable"]:
        print(f"\n  challenger {candidate['group']} not certified: "
              + "; ".join(verdict["reasons"]))
        return

    gain = verdict["gain"]
    if not commit:
        print(f"\n  would certify: {candidate['group']} dominates "
              f"{holder['group']}"
              + (f" (mint {gain:.3f} J)" if verdict["mintable"]
                 else f" (no mint: {'; '.join(verdict['mint_reasons'])})")
              + " — rerun with --commit")
        return
    already = conn.execute(
        "SELECT 1 FROM mints WHERE family_id=? AND prev_group=? AND new_group=?",
        (fam, holder["group"], candidate["group"]),
    ).fetchone()
    if verdict["mintable"] and already is None:
        conn.execute(
            "INSERT INTO mints(family_id, prev_group, new_group, prev_low_j, "
            "new_high_j, verify_energy_j, certified_gain_j, note, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (fam, holder["group"], candidate["group"], holder["low"],
             candidate["high"], candidate["verify_mean"], gain,
             "SIMULATED", now_iso()),
        )
    _set_state(conn, fam, candidate)
    conn.commit()
    print()
    print("  " + "=" * 52)
    print(f"  NEW FRONTIER   family={fam}")
    print(f"  Previous: {holder['mean']:8.3f} J  [{holder['low']:.3f}, "
          f"{holder['high']:.3f}]  ({holder['group']}, n={holder['n']})")
    print(f"  New:      {candidate['mean']:8.3f} J  [{candidate['low']:.3f}, "
          f"{candidate['high']:.3f}]  ({candidate['group']}, n={candidate['n']})")
    print(f"  ΔE(mean): {holder['mean']-candidate['mean']:.3f} J")
    if verdict["mintable"] and already is None:
        print(f"  Certified net gain (III): {gain:.3f} J"
              f"   [= prev_low − new_high − E_verify]")
        print(f"  MINT (simulated): +{gain:.3f} CREDIT"
              f"  (1 CREDIT ≡ 1 certified J — v0 provisional)")
    elif already is not None:
        print("  transition already minted once — no re-mint (grinding guard)")
    else:
        print("  frontier updated, NO MINT: "
              + "; ".join(verdict["mint_reasons"]))
    print("  " + "=" * 52)


# ------------------------------------------------------------------ calibrate

def cmd_calibrate(task_prefix: str, runner: str):
    """Audit fix: sigma is reported per (runner, meter) stratum — receipts on
    different meter boundaries are different scales and share no sigma."""
    conn = db()
    task = resolve_task(conn, task_prefix)
    rows = conn.execute(
        """SELECT rc.receipt_json FROM receipts rc JOIN runs r ON r.run_id=rc.run_id
           WHERE rc.family_id=? AND r.runner_id=?""",
        (task["family_id"], runner),
    ).fetchall()
    strata = {}
    for r in rows:
        rec = json.loads(r["receipt_json"])
        strata.setdefault(rec["meter_id"], []).append(
            rec["run_energy"]["energy_joules"])
    if not strata:
        print(f"calibrate: no receipts for {runner}")
        return
    print(f"calibration  runner={runner}  family={task['family_id']}")
    for meter, energies in sorted(strata.items()):
        n = len(energies)
        if n < 2:
            print(f"  [{meter}] n={n} — need >=2 receipts for σ")
            continue
        mean = sum(energies) / n
        var = sum((x - mean) ** 2 for x in energies) / (n - 1)
        sigma = var ** 0.5
        print(f"  [{meter}]")
        print("    " + " / ".join(f"{e:.3f}" for e in energies) + "  J")
        print(f"    n={n}  mean={mean:.3f} J  σ={sigma:.3f} J  cv={sigma/mean*100:.1f}%")
        print(f"    min certifiable improvement within this meter "
              f"({K_SIGMA:g}σ/√n, measured-σ groups only): "
              f"{K_SIGMA*sigma/n**0.5:.3f} J")


# ----------------------------------------------------------------------- demo

def summary_jps(task_prefix: str):
    """§8 primary metric: joules per successful task (all runs incl. failures)."""
    conn = db()
    task = resolve_task(conn, task_prefix)
    rows = conn.execute(
        """SELECT r.runner_id, m.method,
                  COUNT(*) AS runs,
                  SUM(CASE WHEN v.status='PASS' THEN 1 ELSE 0 END) AS passes,
                  SUM(m.energy_joules) AS total_j
           FROM runs r
           JOIN measurements m ON m.run_id = r.run_id
           LEFT JOIN verifications v ON v.run_id = r.run_id
           WHERE r.task_instance_id=?
           GROUP BY r.runner_id, m.method ORDER BY total_j""",
        (task["task_instance_id"],),
    ).fetchall()
    for r in rows:
        passes = r["passes"] or 0
        jps = f"{r['total_j']/passes:8.3f}" if passes else "     inf"
        print(f"  {r['runner_id']:<14} [{r['method']:<10}] runs={r['runs']:<3} "
              f"pass={passes:<3} total={r['total_j']:8.3f} J  J/success={jps}")


def demo_codefix():
    import os
    print("EDEN v0 demo — code-fix family (設計書 §8 domain)")
    print("=" * 60)
    print("\n[1/5] task create")
    task_id = cmd_task_create(str(BASE / "tasks" / "codefix.json"))

    print("\n[2/5] brute-force mutation search × 5 (burns joules instead of thinking)")
    cmd_run(task_id, "codefix_brute", repeat=5)
    cmd_calibrate(task_id, "codefix_brute")

    print("\n[3/5] first record")
    cmd_frontier(task_id, commit=True)

    print("\n[4/5] rule-based fix × 5 (knows the bug class)")
    cmd_run(task_id, "codefix_rules", repeat=5)
    cmd_frontier(task_id, commit=True)

    if shutil.which("ollama"):
        model = os.environ.get("EDEN_LLM_MODEL", "qwen2.5:7b")
        print(f"\n[5/5] local LLM runner × 2 (ollama {model}, ~5 GB model is "
              "pulled on first use; warm-up run excluded from measurement)")
        try:
            subprocess.run(["ollama", "run", model, "Reply with exactly: OK"],
                           capture_output=True, text=True, timeout=600)
            cmd_run(task_id, "codefix_llm", repeat=2)
            cmd_frontier(task_id, commit=True)
        except subprocess.TimeoutExpired:
            print("  ollama warm-up timed out — skipping LLM runner")
    else:
        print("\n[5/5] ollama not found — skipping LLM runner")

    print("\nJoules per successful task (§8 primary metric):")
    summary_jps(task_id)


def cmd_demo():
    print("EDEN v0 demo — 設計書 §7 scenario")
    print("=" * 60)
    print("\n[1/6] task create")
    task_id = cmd_task_create(str(BASE / "tasks" / "topk_words.json"))

    print("\n[2/6] repeatability: naive_count × 10 (run→measure→verify→receipt)")
    cmd_run(task_id, "naive_count", repeat=10)

    print("\n[3/6] measurement noise (EDEN's first research result is σ)")
    cmd_calibrate(task_id, "naive_count")

    print("\n[4/6] first record")
    cmd_frontier(task_id, commit=True)

    print("\n[5/6] challenger: dict_loop × 5")
    cmd_run(task_id, "dict_loop", repeat=5)
    cmd_frontier(task_id, commit=True)

    print("\n[6/6] challenger: counter_fast × 5")
    cmd_run(task_id, "counter_fast", repeat=5)
    cmd_frontier(task_id, commit=True)

    print("\n[extra] failing runner: bad_topk × 1 (Constitution II check)")
    cmd_run(task_id, "bad_topk", repeat=1)
    conn = db()
    n_receipts = conn.execute(
        "SELECT COUNT(*) c FROM receipts WHERE family_id="
        "(SELECT family_id FROM tasks WHERE task_instance_id=?)", (task_id,)
    ).fetchone()["c"]
    n_mints = conn.execute("SELECT COUNT(*) c FROM mints").fetchone()["c"]
    print(f"\nledger: {n_receipts} receipts, {n_mints} simulated mints, db={DB_PATH.name}")


# ---------------------------------------------------------------- challenges

def cmd_challenge_open(gen_spec_path: str, runners: list, n: int):
    """Open an epoch: pin runner code hashes FIRST, then derive the seed and
    generate instances. Enrollment strictly precedes revelation (§6.17)."""
    conn = db()
    spec = json.loads(Path(gen_spec_path).read_text())
    fam = family_id_of(spec)

    enrollment = []
    for runner in runners:
        rp = RUNNERS_DIR / f"{runner}.py"
        if not rp.exists():
            sys.exit(f"error: runner '{runner}' not found")
        enrollment.append((runner, sha(rp.read_bytes())[:16]))

    epoch_no = 1 + conn.execute(
        "SELECT COUNT(*) c FROM epochs WHERE family_id=?", (fam,)
    ).fetchone()["c"]
    # AUDIT C1 (3rd pass): commitments must be DURABLE before the randomness
    # exists — otherwise the operator can peek and "never have opened" the
    # epoch. Phase A: persist the stub and enrollments, COMMIT. An epoch
    # abandoned after this point stays visible as a PENDING stub: grinding
    # now leaves ledger traces instead of vanishing.
    commitment = sha(fam + str(epoch_no)
                     + "|".join(h for _, h in sorted(enrollment)))[:32]
    epoch_id = sha(fam + str(epoch_no) + commitment)[:16]
    conn.execute("INSERT INTO epochs(epoch_id, family_id, epoch_no, seed, "
                 "n_instances, gen_spec_json, created_at, commitment_hash) "
                 "VALUES (?,?,?,?,?,?,?,?)",
                 (epoch_id, fam, epoch_no, "PENDING", n, canonical(spec),
                  now_iso(), commitment))
    for runner, code_hash in enrollment:
        conn.execute("INSERT INTO enrollments VALUES (?,?,?,?)",
                     (epoch_id, runner, code_hash, now_iso()))
    conn.commit()

    # Phase B: only now fetch randomness that postdates the durable commit.
    rand_source, rand_value = challenge_mod.fetch_external_randomness()
    seed = challenge_mod.derive_epoch_seed_v2(fam, epoch_no, commitment,
                                              rand_value)
    conn.execute("UPDATE epochs SET seed=?, randomness_source=?, "
                 "randomness_value=? WHERE epoch_id=?",
                 (seed, rand_source, rand_value, epoch_id))
    conn.commit()
    print(f"randomness: {rand_source} (fetched after durable commitment)")

    correct = (BASE / spec["correct_source"]).read_text()
    test_path = BASE / spec["test_file"]
    inst_dir = DATA_DIR / "epochs" / epoch_id
    inst_dir.mkdir(parents=True, exist_ok=True)
    print(f"epoch {epoch_id}  family={fam}  no={epoch_no}  seed={seed[:16]}…")
    print(f"enrolled: " + ", ".join(f"{r}#{h[:6]}" for r, h in enrollment))
    used = set()
    for i in range(n):
        # Deterministic de-duplication: if a seed collapses onto an already
        # issued bug, derive follow-up seeds by a fixed, auditable rule.
        for attempt in range(16):
            inst_seed = sha(seed + str(i) + ":" + str(attempt))
            mutant, bug = challenge_mod.inject(
                spec.get("bug_mode", "token"),
                correct, inst_seed, test_path, spec["module_name"])
            if bug not in used:
                break
        used.add(bug)
        inst_path = inst_dir / f"inst_{i}.py"
        inst_path.write_text(mutant)
        inst_spec = dict(spec)
        inst_spec["source_file"] = str(inst_path.relative_to(BASE))
        input_hash = sha(mutant)[:16]
        task_id = sha(fam + input_hash)[:16]
        conn.execute(
            "INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?,?)",
            (task_id, fam, spec["task_contract_version"], canonical(inst_spec),
             str(inst_path), input_hash, verifier_spec_hash(spec), now_iso()),
        )
        conn.execute("INSERT INTO epoch_instances VALUES (?,?,?,?)",
                     (epoch_id, i, task_id, bug))
        print(f"  instance {i}: task={task_id}  bug={bug}")
    conn.commit()
    return epoch_id


def cmd_challenge_run(epoch_prefix: str):
    conn = db()
    epoch = conn.execute("SELECT * FROM epochs WHERE epoch_id LIKE ?",
                         (epoch_prefix + "%",)).fetchone()
    if epoch is None:
        sys.exit(f"error: no epoch matching '{epoch_prefix}'")
    instances = conn.execute(
        "SELECT * FROM epoch_instances WHERE epoch_id=? ORDER BY instance_index",
        (epoch["epoch_id"],)).fetchall()
    enrolled = conn.execute(
        "SELECT * FROM enrollments WHERE epoch_id=?", (epoch["epoch_id"],)
    ).fetchall()
    for e in enrolled:
        rp = RUNNERS_DIR / f"{e['runner_id']}.py"
        current = sha(rp.read_bytes())[:16] if rp.exists() else ""
        if not challenge_mod.check_enrollment(e["runner_code_hash"], current):
            print(f"  SKIP {e['runner_id']}: code hash changed since "
                  f"enrollment ({e['runner_code_hash'][:6]} -> {current[:6]})")
            continue
        for inst in instances:
            print(f"-- instance {inst['instance_index']} × {e['runner_id']}")
            run_ids = cmd_run(inst["task_instance_id"], e["runner_id"], repeat=1)
            for rid in run_ids:
                conn.execute("INSERT OR IGNORE INTO epoch_runs VALUES (?,?,?,?)",
                             (epoch["epoch_id"], rid,
                              inst["instance_index"], e["runner_id"]))
            # commit per instance: cmd_run opens its own connection, so an
            # open transaction here would deadlock the ledger
            conn.commit()


def cmd_challenge_report(epoch_prefix: str):
    conn = db()
    epoch = conn.execute("SELECT * FROM epochs WHERE epoch_id LIKE ?",
                         (epoch_prefix + "%",)).fetchone()
    if epoch is None:
        sys.exit(f"error: no epoch matching '{epoch_prefix}'")
    eid = epoch["epoch_id"]
    print(f"epoch {eid}  family={epoch['family_id']}  "
          f"instances={epoch['n_instances']}  seed={epoch['seed'][:16]}…")
    print("\nper-instance results (PASS/fail/err):")
    grid = conn.execute(
        """SELECT er.instance_index, er.runner_id, ei.bug_desc,
                  COALESCE(v.status, r.status) AS outcome
           FROM epoch_runs er
           JOIN runs r ON r.run_id = er.run_id
           JOIN epoch_instances ei ON ei.epoch_id = er.epoch_id
                AND ei.instance_index = er.instance_index
           LEFT JOIN verifications v ON v.run_id = er.run_id
           WHERE er.epoch_id=? ORDER BY er.instance_index, er.runner_id""",
        (eid,)).fetchall()
    for row in grid:
        print(f"  #{row['instance_index']} [{row['bug_desc']:<12}] "
              f"{row['runner_id']:<16} {row['outcome']}")
    print("\nexpected J over the issued distribution "
          "(§8/§9 primary metric, ALL runs incl. failures):")
    stats = conn.execute(
        """SELECT er.runner_id, m.method,
                  COUNT(*) AS runs,
                  SUM(CASE WHEN v.status='PASS' THEN 1 ELSE 0 END) AS passes,
                  SUM(m.energy_joules) AS total_j
           FROM epoch_runs er
           JOIN runs r ON r.run_id = er.run_id
           JOIN measurements m ON m.run_id = er.run_id
           LEFT JOIN verifications v ON v.run_id = er.run_id
           WHERE er.epoch_id=?
           GROUP BY er.runner_id, m.method ORDER BY total_j""",
        (eid,)).fetchall()
    for r in stats:
        passes = r["passes"] or 0
        rate = passes / r["runs"] * 100
        jps = f"{r['total_j']/passes:9.3f}" if passes else "      inf"
        print(f"  {r['runner_id']:<16} [{r['method']:<10}] "
              f"success {passes}/{r['runs']} ({rate:3.0f}%)  "
              f"total={r['total_j']:9.3f} J  J/success={jps}")


def _cert_row_to_dict(row) -> dict:
    return {
        "cert_id": row["cert_id"], "epoch_id": row["epoch_id"],
        "family_id": row["family_id"], "runner": row["runner_id"],
        "code_hash": row["runner_code_hash"], "meter": row["meter"],
        "n_instances": row["n_instances"], "attempts": row["attempts"],
        "successes": row["successes"], "success_rate": row["success_rate"],
        "rate_ci95": [row["rate_lo"], row["rate_hi"]],
        "run_j": row["run_j"], "verify_j": row["verify_j"],
        "total_j": row["total_j"],
        "j_per_success": (row["j_per_success"] if row["j_per_success"]
                          is not None else float("inf")),
    }


def cmd_challenge_certify(epoch_prefix: str, commit: bool = False):
    """Fold an epoch's runs into Distribution Certificates (v0.3): the
    frontier's input unit for challenge families. Minting happens here, at
    cert registration, as a pure function of ledger order."""
    conn = db()
    epoch = conn.execute("SELECT * FROM epochs WHERE epoch_id LIKE ?",
                         (epoch_prefix + "%",)).fetchone()
    if epoch is None:
        sys.exit(f"error: no epoch matching '{epoch_prefix}'")
    eid, fam = epoch["epoch_id"], epoch["family_id"]
    aggs = conn.execute(
        """SELECT er.runner_id, r.runner_code_hash,
                  json_extract(m.meter_profile_json, '$.meter_profile_id') AS meter,
                  COUNT(*) AS attempts,
                  SUM(CASE WHEN v.status='PASS' THEN 1 ELSE 0 END) AS successes,
                  SUM(m.energy_joules) AS run_j,
                  SUM(COALESCE(v.verify_energy_joules, 0)) AS verify_j
           FROM epoch_runs er
           JOIN runs r ON r.run_id = er.run_id
           JOIN measurements m ON m.run_id = er.run_id
           LEFT JOIN verifications v ON v.run_id = er.run_id
           WHERE er.epoch_id=?
           GROUP BY er.runner_id, r.runner_code_hash, meter""",
        (eid,)).fetchall()
    if not aggs:
        sys.exit(f"error: epoch {eid} has no runs (run: eden challenge run)")

    # AUDIT H7 (v0 single-node guard): refuse to certify epochs whose
    # receipts span multiple hardware fingerprints — cross-node certs need
    # per-node stratification that v0 does not implement yet.
    hw_rows = conn.execute(
        """SELECT DISTINCT json_extract(rc.receipt_json,
                  '$.hardware_profile.platform') AS hp
           FROM epoch_runs er JOIN receipts rc ON rc.run_id = er.run_id
           WHERE er.epoch_id=?""", (eid,)).fetchall()
    if len(hw_rows) > 1:
        sys.exit(f"error: epoch {eid} spans {len(hw_rows)} hardware profiles "
                 "— multi-node certification is not implemented (audit H7)")

    coverage = {r["runner_id"]: r["covered"] for r in conn.execute(
        """SELECT runner_id, COUNT(DISTINCT instance_index) AS covered
           FROM epoch_runs WHERE epoch_id=? GROUP BY runner_id""", (eid,))}
    enrolled_hashes = {r["runner_id"]: r["runner_code_hash"]
                       for r in conn.execute(
        "SELECT runner_id, runner_code_hash FROM enrollments WHERE epoch_id=?",
        (eid,))}

    existing = [_cert_row_to_dict(r) for r in conn.execute(
        "SELECT * FROM distribution_certs WHERE family_id=? ORDER BY created_at",
        (fam,))]
    print(f"epoch {eid}  family={fam}  certifying {len(aggs)} runner strata")
    for a in aggs:
        cert = eligibility.distribution_cert(
            eid, fam, a["runner_id"], a["runner_code_hash"], a["meter"],
            epoch["n_instances"], a["attempts"], a["successes"] or 0,
            a["run_j"], a["verify_j"])
        verdict = eligibility.assess_cert_insertion(existing, cert)
        # AUDIT H5: a certificate must prove it faced every issued instance
        # with the exact code it committed at enrollment.
        cov = coverage.get(a["runner_id"], 0)
        if cov < epoch["n_instances"]:
            verdict = {"eligible": False, "gain": 0.0, "mintable": False,
                       "mint_reasons": [], "dominated": [],
                       "pending": verdict.get("pending", []),
                       "reasons": [f"instance coverage {cov}/"
                                   f"{epoch['n_instances']} (audit H5)"]}
        elif enrolled_hashes.get(a["runner_id"]) != a["runner_code_hash"]:
            verdict = {"eligible": False, "gain": 0.0, "mintable": False,
                       "mint_reasons": [], "dominated": [],
                       "pending": verdict.get("pending", []),
                       "reasons": ["run code hash differs from enrollment "
                                   "commitment (audit H5)"]}
        jps = ("inf" if cert["j_per_success"] == float("inf")
               else f"{cert['j_per_success']:.3f}")
        print(f"\n  {cert['cert_id']}")
        print(f"    success {cert['successes']}/{cert['attempts']} "
              f"(rate {cert['success_rate']*100:.0f}%, "
              f"ci95 [{cert['rate_ci95'][0]*100:.0f}%, "
              f"{cert['rate_ci95'][1]*100:.0f}%])  "
              f"total {cert['total_j']:.3f} J (verify incl.)  "
              f"J/success {jps}")
        if not verdict["eligible"]:
            print("    NOT ELIGIBLE: " + "; ".join(verdict["reasons"]))
            continue
        if verdict["mintable"]:
            doms = ", ".join(c["cert_id"] for c in verdict["dominated"])
            print(f"    DOMINATES [{doms}]")
            print("    basis: " + "; ".join(verdict.get("basis", [])))
            print(f"    MINT (simulated): +{verdict['gain']:.3f} CREDIT "
                  "(1 CREDIT = 1 J-per-success improvement, v0 provisional)")
        else:
            print("    no mint: " + "; ".join(verdict["mint_reasons"]))
        print("    pending (unenforced): " + ", ".join(verdict["pending"]))
        if commit:
            jps_val = (None if cert["j_per_success"] == float("inf")
                       else cert["j_per_success"])
            conn.execute(
                "INSERT OR IGNORE INTO distribution_certs VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cert["cert_id"], eid, fam, cert["runner"], cert["code_hash"],
                 cert["meter"], cert["n_instances"], cert["attempts"],
                 cert["successes"], cert["success_rate"],
                 cert["rate_ci95"][0], cert["rate_ci95"][1],
                 cert["run_j"], cert["verify_j"], cert["total_j"],
                 jps_val, now_iso()))
            if verdict["mintable"]:
                already = conn.execute(
                    "SELECT 1 FROM mints WHERE family_id=? AND new_group=?",
                    (fam, cert["cert_id"])).fetchone()
                if already is None:
                    worst = max(c["j_per_success"] for c in verdict["dominated"]
                                if c["j_per_success"] != float("inf"))
                    conn.execute(
                        "INSERT INTO mints(family_id, prev_group, new_group, "
                        "prev_low_j, new_high_j, verify_energy_j, "
                        "certified_gain_j, note, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (fam, verdict["dominated"][0]["cert_id"],
                         cert["cert_id"], worst, cert["j_per_success"],
                         cert["verify_j"], verdict["gain"],
                         "SIMULATED-DIST|" + ";".join(verdict.get("basis", [])),
                         now_iso()))
            conn.commit()
            existing.append(cert)
    if not commit:
        print("\n  (analysis only — rerun with --commit to register certs/mints)")


def cmd_challenge_frontier(family_prefix: str):
    """Read-only: the current Pareto frontier of distribution certs."""
    conn = db()
    rows = conn.execute(
        "SELECT * FROM distribution_certs WHERE family_id LIKE ? "
        "ORDER BY created_at", (family_prefix + "%",)).fetchall()
    if not rows:
        sys.exit(f"error: no distribution certs for family '{family_prefix}' "
                 "(run: eden challenge certify <epoch> --commit)")
    certs = [_cert_row_to_dict(r) for r in rows]
    frontier = eligibility.pareto_frontier(certs)
    fam = certs[0]["family_id"]
    print(f"family {fam}  distribution Pareto frontier "
          f"(success rate ↑, J/success ↓, per meter):")
    for c in sorted(certs, key=lambda c: (c["meter"], -c["success_rate"])):
        mark = "★" if c in frontier else " "
        jps = ("inf" if c["j_per_success"] == float("inf")
               else f"{c['j_per_success']:9.3f}")
        print(f"  {mark} {c['cert_id']:<44} rate {c['success_rate']*100:3.0f}% "
              f"[{c['rate_ci95'][0]*100:3.0f},{c['rate_ci95'][1]*100:3.0f}]  "
              f"J/success {jps}")


CHAIN_GENESIS = "EDEN-genesis"


def _rule_changes(conn):
    """Rule history, read from the journal itself."""
    changes = []
    for row in conn.execute(
            "SELECT seq, entry_body FROM chain WHERE entry_type='rule_change' "
            "ORDER BY seq"):
        if row["entry_body"]:
            change = json.loads(row["entry_body"])
            change["seq"] = row["seq"]
            changes.append(change)
    return changes


def _legacy_boundary(conn) -> int:
    """Last seq governed by the original receipt-only rule. Before any rule
    change every entry is a legacy receipt, so the boundary is the whole
    journal."""
    for ch in _rule_changes(conn):
        if "legacy_boundary" in ch:
            return ch["legacy_boundary"]
    return conn.execute("SELECT COALESCE(MAX(seq),0) m FROM chain"
                        ).fetchone()["m"]


def _chain_append(conn, entry_type: str, entry_id: str, body: str, rule: str,
                  store_body: bool = True):
    """store_body=False for receipts: their text lives in the receipts table,
    and a copy inside the journal would be verified instead of the original,
    hiding edits to the source of truth."""
    head_row = conn.execute(
        "SELECT chain_hash FROM chain ORDER BY seq DESC LIMIT 1").fetchone()
    prev = head_row["chain_hash"] if head_row else sha(CHAIN_GENESIS)
    e_hash = journal_mod.entry_hash(rule, entry_type, body)
    head = sha(prev + e_hash)
    conn.execute(
        "INSERT INTO chain(entry_id, entry_hash, prev_chain, chain_hash, "
        "chained_at, entry_type, hash_rule, entry_body) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (entry_id, e_hash, prev, head, now_iso(), entry_type, rule,
         body if store_body else None))
    return head


def _next_rule(conn) -> str:
    """The rule governing the entry that would be appended next."""
    nxt = 1 + (conn.execute("SELECT COALESCE(MAX(seq),0) m FROM chain")
               .fetchone()["m"])
    return journal_mod.rule_at(_rule_changes(conn), nxt)


def cmd_chain_build():
    """Append every unchained receipt to the tamper-evident journal.

    An 'immutable' ledger that a single UPDATE can rewrite is immutable in
    name only. Each entry commits to the previous one, so edits become
    detectable once a head is anchored externally.
    """
    conn = db()
    rows = conn.execute(
        "SELECT receipt_id, receipt_json FROM receipts WHERE receipt_id NOT IN "
        "(SELECT entry_id FROM chain) ORDER BY created_at, receipt_id"
    ).fetchall()
    head = None
    for r in rows:
        rule = _next_rule(conn)
        head = _chain_append(conn, "receipt", r["receipt_id"],
                             r["receipt_json"], rule, store_body=False)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) c FROM chain").fetchone()["c"]
    if head is None:
        head = conn.execute(
            "SELECT chain_hash FROM chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()["chain_hash"]
    print(f"chained {len(rows)} new receipts (journal length {total})")
    print(f"chain head: {head}")


def cmd_chain_migrate():
    """Record the hash-rule change as an entry written under the OLD rule.

    A transition signed under the rule it introduces would authorise itself.
    The outgoing rule certifies the doorway; entries after it use the new one.
    The manifest binds the types and rules assigned to pre-migration entries,
    which the columns added by the migration cannot do on their own.
    """
    conn = db()
    if any(c.get("new_rule") == journal_mod.DOMAIN_RULE
           for c in _rule_changes(conn)):
        print("journal already migrated to " + journal_mod.DOMAIN_RULE)
        return
    boundary = conn.execute("SELECT COALESCE(MAX(seq),0) m FROM chain"
                            ).fetchone()["m"]
    manifest = [{"seq": r["seq"], "entry_type": "receipt",
                 "hash_rule": journal_mod.LEGACY_RULE,
                 "entry_hash": r["entry_hash"]}
                for r in conn.execute(
                    "SELECT seq, entry_hash FROM chain ORDER BY seq")]
    reasons = journal_mod.validate_rule_change(journal_mod.LEGACY_RULE,
                                               journal_mod.DOMAIN_RULE)
    if reasons:
        sys.exit("error: " + "; ".join(reasons))
    body = canonical({
        "from_seq": boundary + 2,          # the transition itself stays legacy
        "old_rule": journal_mod.LEGACY_RULE,
        "new_rule": journal_mod.DOMAIN_RULE,
        "legacy_boundary": boundary,
        "manifest_sha256": sha(canonical(manifest)),
        "manifest_entries": len(manifest),
        "reason": "domain separation of entry hashes",
    })
    head = _chain_append(conn, "rule_change", "rule_change:" + sha(body)[:16],
                         body, journal_mod.LEGACY_RULE)
    conn.execute("UPDATE chain SET entry_type='receipt', hash_rule=? "
                 "WHERE seq<=? AND entry_type IS NULL",
                 (journal_mod.LEGACY_RULE, boundary))
    conn.commit()
    print(f"rule change recorded at seq {boundary + 1} under "
          f"{journal_mod.LEGACY_RULE}")
    print(f"  entries 1..{boundary}: {journal_mod.LEGACY_RULE} "
          f"(manifest {sha(canonical(manifest))[:16]}…)")
    print(f"  entries {boundary + 2}..: {journal_mod.DOMAIN_RULE}")
    print(f"chain head: {head}")
    print("anchor this head publicly before appending signed entries")


def cmd_chain_verify():
    """Recompute every entry hash and link under the rule in force at its seq."""
    conn = db()
    changes = _rule_changes(conn)
    boundary = _legacy_boundary(conn)
    head = sha(CHAIN_GENESIS)
    ok = True
    for problem in journal_mod.validate_rule_history(changes):
        print(f"  rule history: {problem}")
        ok = False
    for row in conn.execute("SELECT * FROM chain ORDER BY seq"):
        seq = row["seq"]
        rule = journal_mod.rule_at(changes, seq)
        declared = row["hash_rule"]
        if declared and declared != rule:
            print(f"  seq {seq}: rule mismatch (claims {declared}, "
                  f"history says {rule})")
            ok = False
        etype = row["entry_type"] or journal_mod.legacy_type_of(seq, boundary)
        if seq <= boundary:
            etype = journal_mod.legacy_type_of(seq, boundary)
        if etype == "receipt":
            rec = conn.execute(
                "SELECT receipt_json FROM receipts WHERE receipt_id=?",
                (row["entry_id"],)).fetchone()
            body = rec["receipt_json"] if rec else None
        else:
            body = row["entry_body"]
        if body is None:
            print(f"  seq {seq}: MISSING body for {row['entry_id']}")
            ok = False
        else:
            recomputed = journal_mod.entry_hash(rule, etype, body)
            if recomputed != row["entry_hash"]:
                print(f"  seq {seq}: TAMPERED body ({row['entry_id']})")
                ok = False
        head = sha(head + row["entry_hash"])
        if head != row["chain_hash"]:
            print(f"  seq {seq}: BROKEN chain link")
            ok = False
            head = row["chain_hash"]
    n = conn.execute("SELECT COUNT(*) c FROM chain").fetchone()["c"]
    unchained = conn.execute(
        "SELECT COUNT(*) c FROM receipts WHERE receipt_id NOT IN "
        "(SELECT entry_id FROM chain)").fetchone()["c"]
    print(f"chain: {n} entries, {unchained} receipts not yet chained")
    print(f"verdict: {'INTACT' if ok else 'TAMPER DETECTED'}")
    print(f"head: {head}")
    return ok


def cmd_chain_status():
    """Entries past the last anchored head are still rewritable locally."""
    conn = db()
    total = conn.execute("SELECT COALESCE(MAX(seq),0) m FROM chain"
                         ).fetchone()["m"]
    anchored = 0
    try:
        log = subprocess.run(["git", "log", "--all", "--format=%B"],
                             capture_output=True, text=True, cwd=BASE).stdout
        heads = set(re.findall(r"\b[0-9a-f]{64}\b", log))
        for row in conn.execute("SELECT seq, chain_hash FROM chain "
                                "ORDER BY seq DESC"):
            if row["chain_hash"] in heads:
                anchored = row["seq"]
                break
    except OSError:
        pass
    print(f"journal length : {total}")
    print(f"anchored to seq: {anchored} (found in this repository's commits)")
    print(f"UNPROTECTED    : {total - anchored} entries")
    print(f"current rule   : {_next_rule(conn)}")
    if total - anchored:
        print("these entries are rewritable by whoever holds the local ledger "
              "— anchor the head to fix them")


def _register_node(conn, pubkey: str, label: str = ""):
    nid = identity_mod.node_id_of(pubkey)
    conn.execute("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?)",
                 (nid, pubkey, label, now_iso()))
    conn.commit()
    return nid


def cmd_identity(action: str):
    if action == "init":
        if identity_mod.have_key():
            print(f"key already exists: {identity_mod.KEY_PATH}")
        else:
            identity_mod.create_key()
            print(f"created: {identity_mod.KEY_PATH} (mode 0600)")
    try:
        pub = identity_mod.public_key()
    except identity_mod.SigningUnavailable as e:
        print(f"no identity: {e}")
        print("receipts will be emitted UNSIGNED (measurement precedes trust)")
        return
    nid = _register_node(db(), pub, "local")
    print(f"node_id : {nid}")
    print(f"display : {nid[:12]}…")
    print(f"pubkey  : {pub[:60]}…")


def trust_state_of(conn, receipt: dict, run_id: str) -> str:
    """What this ledger is entitled to claim about a receipt.

    SIGNED means someone put their name on it — not that it is true. The
    tiers above exist because signatures cannot close that gap."""
    sigs = receipt.get("signatures") or []
    if not sigs:
        return "UNSIGNED" if run_id.startswith("ext-") else "LOCAL"
    # A receipt that carries a signature is making a claim. If the claim does
    # not hold, saying "unsigned" would flatter it: an honest unsigned receipt
    # and a forged one must not read the same.
    body = {k: v for k, v in receipt.items() if k != "signatures"}
    for sig in sigs:
        row = conn.execute("SELECT public_key FROM nodes WHERE node_id=?",
                           (sig.get("node_id"),)).fetchone()
        if row is None:
            continue
        if identity_mod.verify(canonical(body), sig.get("signature", ""),
                               sig.get("namespace", ""), row["public_key"]):
            return _verified_or_signed(conn, receipt)
    return "INVALID"


def _verified_or_signed(conn, receipt: dict) -> str:
    """VERIFIED means another machine re-ran the work and agreed — a claim
    about reproduction, not about the quality of the meter (design §12)."""
    row = conn.execute(
        "SELECT hw_fingerprint FROM verifications_independent "
        "WHERE receipt_hash=? AND verdict='PASS'",
        (sha(canonical({k: v for k, v in receipt.items()
                        if k != "signatures"}))[:16],)).fetchone()
    if row is None:
        # the receipt's stored hash covers the whole body including signatures
        row = conn.execute(
            "SELECT v.hw_fingerprint FROM verifications_independent v "
            "JOIN receipts r ON r.receipt_id = v.receipt_id "
            "WHERE r.receipt_json = ? AND v.verdict='PASS'",
            (canonical(receipt),)).fetchone()
    if row and row["hw_fingerprint"] != _hw_fingerprint_of(receipt):
        return "VERIFIED"
    return "SIGNED"


def _hw_fingerprint_of(receipt: dict) -> str:
    return eligibility.hw_fingerprint(receipt)


def cmd_import_verification(path: str):
    """Take in an independent verification produced on another machine.

    What makes it independent is the hardware it ran on, not the wording of
    the claim: a verification whose fingerprint matches the receipt's own is
    the same machine agreeing with itself."""
    conn = db()
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict):
        payload = [payload]
    added = rejected = 0
    for vr in payload:
        rec_row = conn.execute(
            "SELECT receipt_id, receipt_json FROM receipts WHERE receipt_hash=?",
            (vr.get("receipt_hash", ""),)).fetchone()
        if rec_row is None:
            print(f"  rejected: no receipt with hash {vr.get('receipt_hash')}")
            rejected += 1
            continue
        receipt = json.loads(rec_row["receipt_json"])
        body = {k: v for k, v in vr.items() if k != "signature"}
        pub = vr.get("public_key", "")
        if not identity_mod.verify(canonical(body), vr.get("signature", ""),
                                   identity_mod.NS_RECEIPT, pub):
            print(f"  rejected: signature does not verify")
            rejected += 1
            continue
        if vr.get("hw_fingerprint") == _hw_fingerprint_of(receipt):
            print("  rejected: same hardware as the receipt — a machine "
                  "confirming itself is not independent verification")
            rejected += 1
            continue
        nid = _register_node(conn, pub, "witness-ephemeral")
        vr_id = sha(canonical(vr))[:16]
        conn.execute(
            "INSERT OR IGNORE INTO verifications_independent VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            (vr_id, rec_row["receipt_id"], vr["receipt_hash"],
             vr.get("verifier_spec_hash", ""), vr.get("verdict", ""),
             nid, vr.get("hw_fingerprint", ""),
             vr.get("trust_basis", "unstated"), canonical(vr), now_iso()))
        added += 1
    conn.commit()
    print(f"independent verifications: {added} accepted, {rejected} rejected")
    return rejected == 0


def cmd_verify_signatures():
    """Re-verify every signature in the ledger against the registered keys."""
    conn = db()
    counts = {}
    bad = 0
    for row in conn.execute("SELECT receipt_id, run_id, receipt_json "
                            "FROM receipts ORDER BY created_at"):
        rec = json.loads(row["receipt_json"])
        state = trust_state_of(conn, rec, row["run_id"])
        if state == "INVALID":
            print(f"  {row['receipt_id']}: carries a signature that does not "
                  "verify — this is a failed claim, not an unsigned receipt")
            bad += 1
        counts[state] = counts.get(state, 0) + 1
        conn.execute("UPDATE receipts SET trust_state=? WHERE receipt_id=?",
                     (state, row["receipt_id"]))
    conn.commit()
    for state in ("LOCAL", "UNSIGNED", "INVALID", "SIGNED", "VERIFIED"):
        if counts.get(state):
            print(f"  {state:<9}: {counts[state]}")
    print(f"invalid signatures: {bad}")
    return bad == 0


def cmd_chain_checkpoint():
    """Sign the current head, so the anchor says who vouched for it."""
    conn = db()
    row = conn.execute(
        "SELECT seq, chain_hash FROM chain ORDER BY seq DESC LIMIT 1").fetchone()
    if row is None:
        sys.exit("error: journal is empty")
    try:
        pub = identity_mod.public_key()
        body = canonical({"chain_head": row["chain_hash"], "seq": row["seq"]})
        sig = identity_mod.sign(body, identity_mod.NS_CHECKPOINT)
    except identity_mod.SigningUnavailable as e:
        sys.exit(f"error: cannot sign checkpoint ({e}) — run: eden identity init")
    nid = _register_node(conn, pub, "local")
    conn.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)",
                 (row["chain_hash"], row["seq"], nid, sig, now_iso()))
    conn.commit()
    print(f"checkpoint signed by {nid[:12]}… at seq {row['seq']}")
    print(f"head: {row['chain_hash']}")
    print("anchor it now: put this head in the next commit message")


def cmd_ore_scan():
    """Seal receipts with the first epoch opened after them; keep the rare.

    Deterministic and replayable from the ledger. ORE never touches CREDIT
    (spec 6.7): this function reads receipts and epochs, writes ores, and
    nothing else.
    """
    conn = db()
    epochs = conn.execute(
        "SELECT epoch_id, seed, created_at FROM epochs ORDER BY created_at"
    ).fetchall()
    receipts = conn.execute(
        "SELECT receipt_id, receipt_hash, created_at FROM receipts "
        "ORDER BY created_at").fetchall()
    scanned = found = pending = 0
    for r in receipts:
        sealer = next((e for e in epochs if e["created_at"] > r["created_at"]),
                      None)
        if sealer is None:
            pending += 1
            continue
        scanned += 1
        h, z, tier = ore_mod.discover(r["receipt_hash"], sealer["seed"])
        if tier is None:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO ores VALUES (?,?,?,?,?,?)",
            (h, r["receipt_id"], sealer["epoch_id"], z, tier, now_iso()))
        found += cur.rowcount
    conn.commit()
    print(f"scanned {scanned} sealed receipts ({pending} await a sealing epoch)")
    total = conn.execute("SELECT COUNT(*) c FROM ores").fetchone()["c"]
    print(f"new ores: {found}  (ledger total: {total})")


def cmd_ore_list():
    conn = db()
    rows = conn.execute(
        "SELECT o.*, r.receipt_json FROM ores o "
        "JOIN receipts r ON r.receipt_id = o.receipt_id "
        "ORDER BY o.zero_bits DESC, o.discovered_at").fetchall()
    if not rows:
        print("no ores discovered yet")
        return
    for o in rows:
        rec = json.loads(o["receipt_json"])
        odds = 2 ** o["zero_bits"]
        print(f"  ORE: {o['tier']:<6} rarity ~1/{odds:<8} "
              f"hash {o['ore_hash'][:16]}…")
        print(f"       origin: {rec['runner_id']} on family "
              f"{rec['family_id']}  ({rec['run_energy']['energy_joules']:.3f} J)"
              f"  sealed by epoch {o['epoch_id'][:8]}")


# ------------------------------------------------------------------------ cli

def main():
    p = argparse.ArgumentParser(prog="eden", description="EDEN v0 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the SQLite ledger")

    pt = sub.add_parser("task", help="task operations")
    tsub = pt.add_subparsers(dest="task_cmd", required=True)
    tc = tsub.add_parser("create", help="create task from spec json")
    tc.add_argument("spec")
    tsub.add_parser("list", help="list tasks")

    pr = sub.add_parser("run", help="run a task with a runner (chains verify+receipt)")
    pr.add_argument("--task", required=True)
    pr.add_argument("--runner", required=True)
    pr.add_argument("--repeat", type=int, default=1)
    pr.add_argument("--meter", choices=sorted(METERS),
                    help="measurement adapter (default: auto per runner)")
    pr.add_argument("--no-chain", action="store_true",
                    help="store run+measurement only (use verify/receipt manually)")

    pv = sub.add_parser("verify", help="verify a stored run")
    pv.add_argument("run_id")

    prc = sub.add_parser("receipt", help="emit or show a receipt")
    prc.add_argument("action", choices=["emit", "show"])
    prc.add_argument("run_id")

    pim = sub.add_parser("import", help="import foreign receipts (unsigned claims)")
    pim.add_argument("path")

    pchn = sub.add_parser("chain", help="tamper-evident journal")
    pchn.add_argument("action",
                      choices=["build", "verify", "migrate", "status",
                               "checkpoint"])

    pid = sub.add_parser("identity", help="node key and id")
    pid.add_argument("action", choices=["init", "show"])

    sub.add_parser("verify-signatures", help="re-verify all ledger signatures")

    piv = sub.add_parser("import-verification",
                         help="ingest an independent verification")
    piv.add_argument("path")

    por = sub.add_parser("ore", help="the cultural layer (v1 spec 13)")
    por.add_argument("action", choices=["scan", "list"])

    ph = sub.add_parser("html", help="render the ledger as a single page")
    ph.add_argument("--output", default="eden_ledger.html")

    pc = sub.add_parser("calibrate", help="σ report for runner×task receipts")
    pc.add_argument("--task", required=True)
    pc.add_argument("--runner", required=True)

    pf = sub.add_parser("frontier", help="analyze frontier (read-only; --commit mints)")
    pf.add_argument("--task", required=True)
    pf.add_argument("--commit", action="store_true",
                    help="update frontier state and mint (default: analysis only)")

    pd = sub.add_parser("demo", help="full demo scenario on this machine")
    pd.add_argument("--scenario", choices=["topk", "codefix"], default="topk")

    pch = sub.add_parser("challenge", help="protocol-issued task epochs (§6.17)")
    csub = pch.add_subparsers(dest="ch_cmd", required=True)
    co = csub.add_parser("open", help="enroll runners, then generate instances")
    co.add_argument("--spec", default=str(BASE / "tasks" / "codefix_gen.json"))
    co.add_argument("--runners", required=True,
                    help="comma-separated runner names to enroll")
    co.add_argument("-n", type=int, default=6)
    cr = csub.add_parser("run", help="run all enrolled runners on all instances")
    cr.add_argument("epoch")
    cp = csub.add_parser("report", help="expected-J report over the epoch")
    cp.add_argument("epoch")
    cc = csub.add_parser("certify",
                         help="fold an epoch into distribution certs (mints)")
    cc.add_argument("epoch")
    cc.add_argument("--commit", action="store_true",
                    help="register certs and mint (default: analysis only)")
    cf = csub.add_parser("frontier",
                         help="Pareto frontier of distribution certs")
    cf.add_argument("family")

    prv = sub.add_parser("_refverify", help=argparse.SUPPRESS)
    prv.add_argument("input_path")
    prv.add_argument("k", type=int)

    a = p.parse_args()
    if a.cmd == "init":
        db()
        print(f"ledger ready: {DB_PATH}")
    elif a.cmd == "task" and a.task_cmd == "create":
        cmd_task_create(a.spec)
    elif a.cmd == "task" and a.task_cmd == "list":
        for r in db().execute("SELECT * FROM tasks"):
            print(f"{r['task_instance_id']}  family={r['family_id']}  "
                  f"{r['task_contract_version']}")
    elif a.cmd == "run":
        cmd_run(a.task, a.runner, a.repeat, chain=not a.no_chain, meter=a.meter)
    elif a.cmd == "verify":
        cmd_verify(a.run_id)
    elif a.cmd == "receipt" and a.action == "emit":
        cmd_receipt_emit(a.run_id)
    elif a.cmd == "receipt" and a.action == "show":
        cmd_receipt_show(a.run_id)
    elif a.cmd == "import":
        cmd_import(a.path)
    elif a.cmd == "chain" and a.action == "build":
        cmd_chain_build()
    elif a.cmd == "chain" and a.action == "verify":
        sys.exit(0 if cmd_chain_verify() else 1)
    elif a.cmd == "chain" and a.action == "migrate":
        cmd_chain_migrate()
    elif a.cmd == "chain" and a.action == "status":
        cmd_chain_status()
    elif a.cmd == "identity":
        cmd_identity(a.action)
    elif a.cmd == "import-verification":
        sys.exit(0 if cmd_import_verification(a.path) else 1)
    elif a.cmd == "verify-signatures":
        sys.exit(0 if cmd_verify_signatures() else 1)
    elif a.cmd == "chain" and a.action == "checkpoint":
        cmd_chain_checkpoint()
    elif a.cmd == "ore" and a.action == "scan":
        cmd_ore_scan()
    elif a.cmd == "ore" and a.action == "list":
        cmd_ore_list()
    elif a.cmd == "html":
        import ledger_html
        out = Path(a.output)
        out.write_text(ledger_html.build_html(db()))
        print(f"ledger page: {out.resolve()}")
    elif a.cmd == "calibrate":
        cmd_calibrate(a.task, a.runner)
    elif a.cmd == "frontier":
        cmd_frontier(a.task, commit=a.commit)
    elif a.cmd == "demo":
        demo_codefix() if a.scenario == "codefix" else cmd_demo()
    elif a.cmd == "challenge" and a.ch_cmd == "open":
        cmd_challenge_open(a.spec, a.runners.split(","), a.n)
    elif a.cmd == "challenge" and a.ch_cmd == "run":
        cmd_challenge_run(a.epoch)
    elif a.cmd == "challenge" and a.ch_cmd == "report":
        cmd_challenge_report(a.epoch)
    elif a.cmd == "challenge" and a.ch_cmd == "certify":
        cmd_challenge_certify(a.epoch, commit=a.commit)
    elif a.cmd == "challenge" and a.ch_cmd == "frontier":
        cmd_challenge_frontier(a.family)
    elif a.cmd == "_refverify":
        words = Path(a.input_path).read_text().split()
        print(canonical(reference_topk(words, a.k)))


if __name__ == "__main__":
    main()
