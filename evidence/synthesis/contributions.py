from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Contribution:
    position: int
    study_id: str
    revision_id: int
    value: Fraction

    @property
    def key(self):
        return self.position, self.study_id, self.revision_id


def build_contributions(evidence, weights, pooled):
    indexed = {weight.key: weight for weight in weights}
    if len(indexed) != len(weights) or set(indexed) != {row.key for row in evidence}:
        raise ValueError("contribution weight identity mismatch")
    rows = tuple(Contribution(row.position, row.study_id, row.revision_id,
                              indexed[row.key].normalized * row.difference) for row in evidence)
    verify_contributions(evidence, weights, pooled, rows)
    return rows


def verify_contributions(evidence, weights, pooled, contributions):
    keys = [row.key for row in evidence]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("duplicate or empty contribution input")
    if [row.key for row in contributions] != keys or [row.key for row in weights] != keys:
        raise ValueError("contribution ordering or identity mismatch")
    if sum((row.normalized for row in weights), Fraction()) != 1:
        raise ValueError("normalized weights do not sum to one")
    for delta, weight, contribution in zip(evidence, weights, contributions):
        if contribution.value != weight.normalized * delta.difference:
            raise ValueError("incorrect contribution for study")
    if sum((row.value for row in contributions), Fraction()) != pooled.estimate:
        raise ValueError("contributions do not reconcile with estimate")
