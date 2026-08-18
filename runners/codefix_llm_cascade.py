#!/usr/bin/env python3
"""Code-fix runner: escalating cascade — the 'intelligent frugality' strategy.

Try the cheapest thing first and escalate only on failure:
  1. targeted rule (knows one bug class)
  2. brute-force single-token mutation search
  3. qwen2.5:1.5b, one shot
  4. qwen2.5:7b, one shot
Every stage's energy stays inside the measurement window, so the cascade
pays honestly for its failed cheap attempts.

argv: <buggy_source_path> <test_file_path> <module_name>
stdout: {"source": <fixed module source>} on success; exit 1 on failure.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SMALL = os.environ.get("EDEN_LLM_MODEL_1P5B", "qwen2.5:1.5b")
LARGE = os.environ.get("EDEN_LLM_MODEL", "qwen2.5:7b")

PATTERN = "(s[mid] + s[mid + 1])"
FIX = "(s[mid - 1] + s[mid])"

OPS = [
    ("-", "+"), ("<=", "<"), ("<", "<="), (">=", ">"), (">", ">="),
    ("==", "!="), ("!=", "=="), ("// 2", "// 2 + 1"), ("// 2", "// 2 - 1"),
    ("+", "-"),
]

PROMPT = """You are given a Python module that contains exactly one bug, and \
the unittest suite it must pass.

Buggy module (file name: {module}.py):
```python
{source}
```

Test suite:
```python
{tests}
```

Return the corrected FULL module source. Reply with ONLY one ```python code \
block containing the complete fixed module, no explanations."""


def tests_pass(source, test_path, module_name):
    with tempfile.TemporaryDirectory() as td:
        Path(td, module_name + ".py").write_text(source)
        shutil.copy(test_path, Path(td, Path(test_path).name))
        r = subprocess.run(
            [sys.executable, "-m", "unittest", Path(test_path).stem],
            cwd=td, capture_output=True,
        )
        return r.returncode == 0


def stage_rule(src, test_path, module_name):
    fixed = src.replace(PATTERN, FIX)
    if fixed != src and tests_pass(fixed, test_path, module_name):
        return fixed
    return None


def stage_brute(src, test_path, module_name):
    seen = {src}
    for a, b in OPS:
        start = 0
        while True:
            i = src.find(a, start)
            if i < 0:
                break
            cand = src[:i] + b + src[i + len(a):]
            start = i + 1
            if cand in seen:
                continue
            seen.add(cand)
            if tests_pass(cand, test_path, module_name):
                return cand
    return None


def stage_llm(model, src, tests, test_path, module_name):
    prompt = PROMPT.format(module=module_name, source=src, tests=tests)
    r = subprocess.run(["ollama", "run", model, prompt],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return None
    blocks = re.findall(r"```(?:python)?\n(.*?)```", r.stdout, re.DOTALL)
    if not blocks:
        return None
    candidate = blocks[-1].strip() + "\n"
    if tests_pass(candidate, test_path, module_name):
        return candidate
    return None


def main():
    src_path, test_path, module_name = sys.argv[1], sys.argv[2], sys.argv[3]
    src = Path(src_path).read_text()
    tests = Path(test_path).read_text()

    fixed = (stage_rule(src, test_path, module_name)
             or stage_brute(src, test_path, module_name)
             or stage_llm(SMALL, src, tests, test_path, module_name)
             or stage_llm(LARGE, src, tests, test_path, module_name))
    if fixed is None:
        sys.exit(1)
    print(json.dumps({"source": fixed}))


if __name__ == "__main__":
    main()
