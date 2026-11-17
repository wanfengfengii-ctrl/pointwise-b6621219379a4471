from evidence.results.artifact import validate_artifact, archived_parts
from evidence.cohorts.reader import read_cohort


class ResultPublisher:
    def __init__(self, repository):
        self.repository = repository

    def publish(self, artifact):
        with self.repository.transactions.atomic():
            cohort = read_cohort(self.repository, artifact.cohort_id)
            validate_artifact(artifact, cohort)
            parts = archived_parts(artifact)
            result_id = self.repository.store_result(artifact.cohort_id, *parts)
            self.repository.transactions.checkpoint("after_contributions")
        return result_id
