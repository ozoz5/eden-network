#!/usr/bin/env python3
"""Failing runner (Constitution II demo): wrong sort order, cheap but incorrect.

Fast and energy-efficient, but the result is wrong: ascending count order.
EDEN must refuse a receipt no matter how few joules were spent.
"""
import json
import sys
from collections import Counter


def main():
    input_path, k = sys.argv[1], int(sys.argv[2])
    with open(input_path) as f:
        counts = Counter(f.read().split())
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))  # wrong order
    print(json.dumps([[w, c] for w, c in ranked[:k]],
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
