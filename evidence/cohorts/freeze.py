from evidence.cohorts.selection import select_revisions
from evidence.cohorts.membership import validate_membership, validate_network_membership
from evidence.studies.identity import canonical_treatment_pair


class CohortService:
    def __init__(self, repository):
        self.repository = repository

    def freeze_cohort(self, revision_ids, treatment_pair):
        pair = canonical_treatment_pair(treatment_pair)
        with self.repository.transactions.atomic():
            revisions = select_revisions(self.repository, revision_ids)
            validate_membership(revisions, pair)
            return self.repository.store_cohort(pair, tuple(r.revision_id for r in revisions))

    def freeze_network(self, revision_ids):
        if not isinstance(revision_ids, (list, tuple)):
            raise ValueError("network revisions must be a list or tuple")
        with self.repository.transactions.atomic():
            revisions = select_revisions(self.repository, revision_ids)
            validate_network_membership(revisions)
            return self.repository.store_network(tuple(r.revision_id for r in revisions))
