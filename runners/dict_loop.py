#!/usr/bin/env python3
"""Runner B (medium intelligence): single pass with a plain dict, O(n)."""
import json
import sys


def main():
    input_path, k = sys.argv[1], int(sys.argv[2])
    with open(input_path) as f:
        words = f.read().split()
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    print(json.dumps([[w, c] for w, c in ranked[:k]],
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
