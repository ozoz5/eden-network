#!/usr/bin/env python3
"""Runner C (high intelligence): collections.Counter (C-implemented), O(n)."""
import json
import sys
from collections import Counter


def main():
    input_path, k = sys.argv[1], int(sys.argv[2])
    with open(input_path) as f:
        counts = Counter(f.read().split())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print(json.dumps([[w, c] for w, c in ranked[:k]],
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
