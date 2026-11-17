from evidence.archive.repository import IntegrityError
from evidence.cohorts.reader import read_cohort
from evidence.cohorts.network import read_network_cohort
from evidence.results.artifact import restore_artifact, result_copy
from evidence.results.network_artifact import restore_network_artifact, network_result_copy


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

    def read_network(self, result_id):
        stored = self.repository.load_network_result(result_id)
        try:
            network = read_network_cohort(self.repository, stored["network_id"])
        except (KeyError, ValueError) as exc:
            raise IntegrityError("result has broken parent network") from exc
        artifact = restore_network_artifact(stored, network)
        return network_result_copy(artifact, result_id)
