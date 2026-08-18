"""EDEN independent replication on WITNESS (shadow_verify_v1 payload).

Runs the topk family (3 runners x 5 repeats, estimated meter) on this
machine and emits every receipt into the bounded unittest log between
markers, so the origin node can import them. The task spec is embedded
because the shadow bundle only ships allow-listed source suffixes.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eden

SPEC = {
    "task_contract_version": "topk-words/1",
    "title": "Top-k word frequency (deterministic synthetic corpus)",
    "generator": {
        "type": "synthetic-words",
        "seed": 42,
        "vocab": 800,
        "tokens": 200000,
        "zipf": 1.1,
    },
    "k": 10,
    "quality": {
        "type": "exact-match",
        "tie_break": "higher count first, then lexicographic word",
    },
    "input_schema": "text/plain whitespace-separated words",
    "resource_boundary_profile": "single-process/child-cpu/incl-interpreter-startup",
}

RUNNERS = ["naive_count", "dict_loop", "counter_fast"]
REPEAT = 5


class TestWitnessReplication(unittest.TestCase):
    def test_replicate_topk_family(self):
        spec_path = eden.BASE / "witness_topk.json"
        spec_path.write_text(json.dumps(SPEC, indent=2))
        task_id = eden.cmd_task_create(str(spec_path))
        for runner in RUNNERS:
            eden.cmd_run(task_id, runner, repeat=REPEAT, meter="estimated")

        conn = eden.db()
        rows = conn.execute(
            "SELECT receipt_json FROM receipts ORDER BY created_at"
        ).fetchall()
        # Constitution II: a receipt exists only for a verified PASS, so the
        # count doubles as the success assertion.
        self.assertEqual(len(rows), len(RUNNERS) * REPEAT)

        out = sys.stderr  # unittest log captures stderr
        out.write("\nEDEN_WITNESS_RECEIPTS_BEGIN\n")
        for row in rows:
            out.write(row["receipt_json"] + "\n")
        out.write("EDEN_WITNESS_RECEIPTS_END\n")
        out.flush()


if __name__ == "__main__":
    unittest.main()
