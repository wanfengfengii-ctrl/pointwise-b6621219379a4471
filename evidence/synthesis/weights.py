from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class StudyWeight:
    position: int
    study_id: str
    revision_id: int
    raw: Fraction
    normalized: Fraction

    @property
    def key(self):
        return self.position, self.study_id, self.revision_id


def inverse_variance_weights(evidence):
    if not evidence or len({row.key for row in evidence}) != len(evidence):
        raise ValueError("nonempty unique evidence required")
    if any(not isinstance(row.variance, Fraction) or row.variance <= 0 for row in evidence):
        raise ValueError("positive exact variance required")
    raw = tuple(Fraction(1) / row.variance for row in evidence)
    total = sum(raw, Fraction())
    return tuple(StudyWeight(row.position, row.study_id, row.revision_id, weight, weight / total)
                 for row, weight in zip(evidence, raw))
