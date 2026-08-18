#!/usr/bin/env python3
"""Code-fix runner: large local LLM (phi4 14b). Does success rate justify watts?

The model receives the buggy source and the test suite, and must return the
corrected full module source in a single code block. The runner extracts the
code, self-checks once against the tests, and only then emits it.

Inference cpu burns inside the ollama daemon, not in this process — EDEN
measures it with the estimated-cpu+ollama meter (daemon cpu delta).

argv: <buggy_source_path> <test_file_path> <module_name>
env:  EDEN_LLM_MODEL (default qwen2.5:7b)
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

MODEL = os.environ.get("EDEN_LLM_MODEL_PHI4", "phi4")

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


def main():
    src_path, test_path, module_name = sys.argv[1], sys.argv[2], sys.argv[3]
    src = Path(src_path).read_text()
    tests = Path(test_path).read_text()
    prompt = PROMPT.format(module=module_name, source=src, tests=tests)

    r = subprocess.run(["ollama", "run", MODEL, prompt],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        sys.exit(1)
    blocks = re.findall(r"```(?:python)?\n(.*?)```", r.stdout, re.DOTALL)
    if not blocks:
        sys.exit(1)
    candidate = blocks[-1].strip() + "\n"
    if not tests_pass(candidate, test_path, module_name):
        sys.exit(1)
    print(json.dumps({"source": candidate}))


if __name__ == "__main__":
    main()
