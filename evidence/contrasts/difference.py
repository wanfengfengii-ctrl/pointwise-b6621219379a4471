from dataclasses import dataclass
from fractions import Fraction
from evidence.contrasts.orientation import orient_arms


@dataclass(frozen=True)
class DirectedDifference:
    position: int
    study_id: str
    revision_id: int
    difference: Fraction


def calculate_difference(member, direction):
    left, right = orient_arms(member.revision.arms, direction)
    return DirectedDifference(member.position, member.revision.study_id,
                              member.revision.revision_id, left.mean - right.mean)
