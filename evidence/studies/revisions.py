from dataclasses import dataclass
from evidence.studies.identity import StudyIdentity, ConflictError, validate_identity
from evidence.studies.arms import ArmStatistics
from evidence.studies.validation import validate_batch
from evidence.archive.encoding import encode_fraction, decode_fraction
from evidence.archive.repository import IntegrityError


@dataclass(frozen=True)
class StudyRevision:
    revision_id: int
    study_id: str
    source_version: str
    withdrawn: bool
    arms: tuple


def read_revision(repository, revision_id):
    row = repository.load_revision(revision_id)
    try:
        StudyIdentity(row["study_id"], row["source_version"])
        if row["withdrawn"] not in (0, 1):
            raise ValueError("invalid withdrawal marker")
        arms = tuple(ArmStatistics(arm["treatment"], decode_fraction(arm["mean"]),
                                   decode_fraction(arm["variance"])) for arm in row["arms"])
        if row["withdrawn"]:
            if arms:
                raise ValueError("withdrawal has arms")
        elif len(arms) != 2 or len({arm.treatment for arm in arms}) != 2:
            raise ValueError("incomplete two-arm revision")
        repository.load_study(row["study_id"])
        return StudyRevision(row["revision_id"], row["study_id"], row["source_version"],
                             bool(row["withdrawn"]), arms)
    except (ValueError, TypeError, KeyError) as exc:
        raise IntegrityError("invalid study revision") from exc


def read_current_revision(repository, study_id):
    validate_identity(study_id, "study_id")
    current = repository.load_study(study_id)["current_revision"]
    try:
        revision = read_revision(repository, current)
        if revision.study_id != study_id:
            raise IntegrityError("current revision belongs to another study")
        return revision
    except (KeyError, ValueError) as exc:
        raise IntegrityError("broken current revision") from exc


class StudyService:
    def __init__(self, repository):
        self.repository = repository

    def _accept(self, identity, arms, withdrawn=False):
        existing = self.repository.find_version(identity.study_id, identity.source_version)
        if existing is not None:
            revision = read_revision(self.repository, existing)
            if revision.withdrawn != withdrawn or revision.arms != arms:
                raise ConflictError("source version has different content")
            return existing
        encoded = [{"treatment": arm.treatment, "mean": encode_fraction(arm.mean),
                    "variance": encode_fraction(arm.variance)} for arm in arms]
        return self.repository.append_revision(identity.study_id, identity.source_version,
                                               withdrawn, encoded)

    def put_study(self, id, source_version, arms):
        return self.put_studies([{"study_id": id, "source_version": source_version,
                                  "arms": arms}])[0]

    def put_studies(self, entries):
        validated = validate_batch(entries)
        with self.repository.transactions.atomic():
            return tuple(self._accept(item.identity, item.arms) for item in validated)

    def withdraw_study(self, id, source_version):
        identity = StudyIdentity(id, source_version)
        with self.repository.transactions.atomic():
            read_current_revision(self.repository, id)
            return self._accept(identity, (), True)
