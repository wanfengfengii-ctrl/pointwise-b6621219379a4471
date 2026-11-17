from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class PooledEffect:
    estimate: Fraction
    variance: Fraction
    weight_sum: Fraction


def pool_direct(evidence, weights):
    if not evidence or len({row.key for row in evidence}) != len(evidence):
        raise ValueError("nonempty unique evidence required")
    indexed = {row.key: row for row in weights}
    if len(indexed) != len(weights) or set(indexed) != {row.key for row in evidence}:
        raise ValueError("weight identities do not match evidence")
    total = Fraction()
    weighted = Fraction()
    for row in evidence:
        weight = indexed[row.key]
        if weight.raw != 1 / row.variance or weight.raw <= 0:
            raise ValueError("incorrect inverse variance weight")
        total += weight.raw
        weighted += weight.raw * row.difference
    if any(weight.normalized != weight.raw / total for weight in weights):
        raise ValueError("incorrect normalized weight")
    return PooledEffect(weighted / total, Fraction(1) / total, total)
