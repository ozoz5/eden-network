"""Small statistics helpers. One function contains a bug."""


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
    return (s[mid] + s[mid + 1]) / 2
