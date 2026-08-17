#!/usr/bin/env python3
"""Runner A (low intelligence): list.count() per unique word, O(u * n)."""
import json
import sys


def main():
    input_path, k = sys.argv[1], int(sys.argv[2])
    with open(input_path) as f:
        words = f.read().split()
    unique = set(words)
    counts = [(w, words.count(w)) for w in unique]
    ranked = sorted(counts, key=lambda kv: (-kv[1], kv[0]))
    print(json.dumps([[w, c] for w, c in ranked[:k]],
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
