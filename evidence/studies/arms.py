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


def _parse_arm_records(values):
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError("arms must be a sequence of arm records")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ValueError("invalid arms") from exc
    arms = []
    for item in items:
        if isinstance(item, ArmStatistics):
            arm = ArmStatistics(item.treatment, item.mean, item.variance)
        elif isinstance(item, Mapping) and set(item) == {"treatment", "mean", "variance"}:
            arm = ArmStatistics(item["treatment"], item["mean"], item["variance"])
        else:
            raise ValueError("invalid arm record")
        arms.append(arm)
    return arms


def _canonical_arms(arms):
    treatments = [arm.treatment for arm in arms]
    if len(set(treatments)) != len(treatments):
        raise ValueError("duplicate treatment")
    return tuple(sorted(arms, key=lambda arm: arm.treatment))


def normalize_arms(values):
    items = _parse_arm_records(values)
    if len(items) != 2:
        raise ValueError("V1 requires exactly two arms")
    return _canonical_arms(items)


def normalize_multiarm(values):
    items = _parse_arm_records(values)
    if not 2 <= len(items) <= 6:
        raise ValueError("multi-arm studies require two to six arms")
    return _canonical_arms(items)
