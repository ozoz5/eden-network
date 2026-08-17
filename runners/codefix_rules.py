#!/usr/bin/env python3
"""Code-fix runner (rule-based): targeted pattern fix, one self-check.

Knows one bug class: even-length median averaging s[mid] and s[mid + 1]
instead of s[mid - 1] and s[mid]. Applies the fix directly, then runs the
test suite once to confirm. Intelligence instead of joules.

argv: <buggy_source_path> <test_file_path> <module_name>
stdout: {"source": <fixed module source>} on success; exit 1 on failure.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PATTERN = "(s[mid] + s[mid + 1])"
FIX = "(s[mid - 1] + s[mid])"


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
    fixed = src.replace(PATTERN, FIX)
    if fixed == src:
        sys.exit(1)  # bug class not recognized; refuse instead of guessing
    if not tests_pass(fixed, test_path, module_name):
        sys.exit(1)
    print(json.dumps({"source": fixed}))


if __name__ == "__main__":
    main()
