from dataclasses import dataclass


class ConflictError(ValueError):
    pass


def validate_identity(value, label="identity"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value


@dataclass(frozen=True)
class StudyIdentity:
    study_id: str
    source_version: str

    def __post_init__(self):
        validate_identity(self.study_id, "study_id")
        validate_identity(self.source_version, "source_version")


def canonical_treatment_pair(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("treatment pair must contain two identities")
    try:
        pair = tuple(values)
    except TypeError as exc:
        raise ValueError("invalid treatment pair") from exc
    if len(pair) != 2:
        raise ValueError("exactly two treatments required")
    for value in pair:
        validate_identity(value, "treatment")
    if pair[0] == pair[1]:
        raise ValueError("treatments must differ")
    return tuple(sorted(pair))
