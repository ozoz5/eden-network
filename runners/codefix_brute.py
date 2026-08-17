#!/usr/bin/env python3
"""Code-fix runner (brute force): single-substitution mutation search.

Dumb but honest: enumerates deterministic single-token mutants of the source
and runs the full test suite (subprocess) on each candidate until one passes.
Burns joules instead of thinking.

argv: <buggy_source_path> <test_file_path> <module_name>
stdout: {"source": <fixed module source>} on success; exit 1 on failure.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The mutation that happens to fix the bundled bug ("+" -> "-") is tried LAST,
# so the search honestly pays for its lack of insight.
OPS = [
    ("-", "+"), ("<=", "<"), ("<", "<="), (">=", ">"), (">", ">="),
    ("==", "!="), ("!=", "=="), ("// 2", "// 2 + 1"), ("// 2", "// 2 - 1"),
    ("+", "-"),
]


def candidates(src):
    seen = {src}
    for a, b in OPS:
        start = 0
        while True:
            i = src.find(a, start)
            if i < 0:
                break
            cand = src[:i] + b + src[i + len(a):]
            start = i + 1
            if cand not in seen:
                seen.add(cand)
                yield cand


def tests_pass(source, test_path, module_name):
    with tempfile.TemporaryDirectory() as td:
        Path(td, module_name + ".py").write_text(source)
        shutil.copy(test_path, Path(td, Path(test_path).name))
        r = subprocess.run(
            [sys.executable, "-m", "unittest", Path(test_path).stem],
            cwd=td, capture_output=True,
        )
        return r.returncode == 0


def main():
    src_path, test_path, module_name = sys.argv[1], sys.argv[2], sys.argv[3]
    src = Path(src_path).read_text()
    if tests_pass(src, test_path, module_name):
        print(json.dumps({"source": src}))
        return
    for cand in candidates(src):
        if tests_pass(cand, test_path, module_name):
            print(json.dumps({"source": cand}))
            return
    sys.exit(1)


if __name__ == "__main__":
    main()
