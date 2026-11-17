from dataclasses import dataclass
from evidence.studies.revisions import read_revision
from evidence.studies.identity import canonical_treatment_pair
from evidence.cohorts.membership import validate_membership
from evidence.archive.repository import IntegrityError


@dataclass(frozen=True)
class CohortMember:
    position: int
    revision: object


@dataclass(frozen=True)
class FrozenCohort:
    cohort_id: int
    pair: tuple
    members: tuple


def read_cohort(repository, cohort_id):
    row = repository.load_cohort(cohort_id)
    try:
        pair = (row["treatment_a"], row["treatment_b"])
        if canonical_treatment_pair(pair) != pair:
            raise ValueError("noncanonical pair")
        members = row["members"]
        if len(members) != row["member_count"]:
            raise ValueError("missing cohort member")
        revisions = []
        for index, member in enumerate(members):
            if member["position"] != index or member["cohort_id"] != cohort_id:
                raise ValueError("invalid cohort member position")
            revisions.append(read_revision(repository, member["revision_id"]))
        validate_membership(revisions, pair)
        return FrozenCohort(cohort_id, pair, tuple(
            CohortMember(i, revision) for i, revision in enumerate(revisions)))
    except (ValueError, KeyError, TypeError) as exc:
        raise IntegrityError("broken frozen cohort") from exc
