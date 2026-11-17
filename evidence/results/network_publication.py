from evidence.results.network_artifact import validate_network_artifact, archived_network_parts
from evidence.cohorts.network import read_network_cohort


class NetworkResultPublisher:
    def __init__(self, repository):
        self.repository = repository

    def publish(self, artifact):
        with self.repository.transactions.atomic():
            network = read_network_cohort(self.repository, artifact.network_id)
            validate_network_artifact(artifact, network)
            header, members = archived_network_parts(artifact)
            result_id = self.repository.store_network_result(artifact.network_id,
                                                             header, members)
            self.repository.transactions.checkpoint("after_contributions")
        return result_id
