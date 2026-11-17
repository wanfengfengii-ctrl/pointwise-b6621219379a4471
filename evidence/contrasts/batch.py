from dataclasses import dataclass
from fractions import Fraction
from evidence.contrasts.orientation import resolve_direction, orient_arms
from evidence.contrasts.difference import calculate_difference
from evidence.contrasts.variance import difference_variance
from evidence.archive.repository import IntegrityError


@dataclass(frozen=True)
class DirectEvidence:
    position: int
    study_id: str
    revision_id: int
    difference: Fraction
    variance: Fraction

    @property
    def key(self):
        return self.position, self.study_id, self.revision_id


def build_direct_evidence(cohort, direction):
    resolve_direction(cohort.pair, direction.left, direction.right)
    evidence = []
    seen = set()
    for index, member in enumerate(cohort.members):
        if member.position != index or member.revision.study_id in seen:
            raise IntegrityError("invalid frozen member identity")
        seen.add(member.revision.study_id)
        delta = calculate_difference(member, direction)
        left, right = orient_arms(member.revision.arms, direction)
        evidence.append(DirectEvidence(delta.position, delta.study_id, delta.revision_id,
                                       delta.difference, difference_variance(left, right)))
    if not evidence:
        raise IntegrityError("empty frozen evidence")
    return tuple(evidence)
