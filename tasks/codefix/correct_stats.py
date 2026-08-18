"""Statistics helpers. Reference implementation; all functions are correct.

This is the challenge generator's substrate: epochs inject one seeded bug
into this module and runners must restore all tests to green.
"""


def mean(values):
    total = 0.0
    for v in values:
        total = total + v
    return total / len(values)


def median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def variance(values):
    m = mean(values)
    acc = 0.0
    for v in values:
        d = v - m
        acc = acc + d * d
    return acc / (len(values) - 1)
