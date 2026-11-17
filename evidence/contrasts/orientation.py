from dataclasses import dataclass
from evidence.studies.identity import canonical_treatment_pair


@dataclass(frozen=True)
class DirectDirection:
    left: str
    right: str


def resolve_direction(pair, left, right):
    if canonical_treatment_pair((left, right)) != canonical_treatment_pair(pair):
        raise ValueError("request must match the frozen treatment pair")
    return DirectDirection(left, right)


def orient_arms(arms, direction):
    by_treatment = {arm.treatment: arm for arm in arms}
    if len(arms) != 2 or set(by_treatment) != {direction.left, direction.right}:
        raise ValueError("arms do not match direction")
    return by_treatment[direction.left], by_treatment[direction.right]
