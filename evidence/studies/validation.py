from dataclasses import dataclass
from collections.abc import Mapping
from evidence.studies.identity import StudyIdentity, ConflictError
from evidence.studies.arms import normalize_arms


@dataclass(frozen=True)
class ValidatedStudy:
    identity: StudyIdentity
    arms: tuple


def validate_study(study_id, source_version, arms):
    return ValidatedStudy(StudyIdentity(study_id, source_version), normalize_arms(arms))


def validate_batch(entries):
    try:
        entries = tuple(entries)
    except TypeError as exc:
        raise ValueError("invalid batch") from exc
    validated = []
    seen = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"study_id", "source_version", "arms"}:
            raise ValueError("invalid study entry")
        item = validate_study(entry["study_id"], entry["source_version"], entry["arms"])
        if item.identity in seen and seen[item.identity] != item.arms:
            raise ConflictError("conflicting version within batch")
        seen[item.identity] = item.arms
        validated.append(item)
    return tuple(validated)
