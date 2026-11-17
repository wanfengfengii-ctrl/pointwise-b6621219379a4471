from evidence.archive.repository import IntegrityError
from evidence.cohorts.reader import read_cohort
from evidence.results.artifact import restore_artifact, result_copy


class ResultReader:
    def __init__(self, repository):
        self.repository = repository

    def read_result(self, result_id):
        stored = self.repository.load_result(result_id)
        try:
            cohort = read_cohort(self.repository, stored["cohort_id"])
        except (KeyError, ValueError) as exc:
            raise IntegrityError("result has broken parent cohort") from exc
        artifact = restore_artifact(stored, cohort)
        return result_copy(artifact, cohort, result_id)
