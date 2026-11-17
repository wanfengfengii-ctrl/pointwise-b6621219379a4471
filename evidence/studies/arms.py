from dataclasses import dataclass
from fractions import Fraction
from collections.abc import Mapping
from evidence.studies.identity import validate_identity


def parse_rational(value):
    if isinstance(value, bool) or not isinstance(value, (int, Fraction, str)):
        raise ValueError("use int, Fraction or a finite rational string")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid finite rational") from exc


@dataclass(frozen=True)
class ArmStatistics:
    treatment: str
    mean: Fraction
    variance: Fraction

    def __post_init__(self):
        validate_identity(self.treatment, "treatment")
        object.__setattr__(self, "mean", parse_rational(self.mean))
        object.__setattr__(self, "variance", parse_rational(self.variance))
        if self.variance <= 0:
            raise ValueError("known mean variance must be positive")


def normalize_arms(values):
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError("arms must be a sequence of arm records")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ValueError("invalid arms") from exc
    if len(items) != 2:
        raise ValueError("V1 requires exactly two arms")
    arms = []
    for item in items:
        if isinstance(item, ArmStatistics):
            arm = ArmStatistics(item.treatment, item.mean, item.variance)
        elif isinstance(item, Mapping) and set(item) == {"treatment", "mean", "variance"}:
            arm = ArmStatistics(item["treatment"], item["mean"], item["variance"])
        else:
            raise ValueError("invalid arm record")
        arms.append(arm)
    if arms[0].treatment == arms[1].treatment:
        raise ValueError("duplicate treatment")
    return tuple(sorted(arms, key=lambda arm: arm.treatment))
