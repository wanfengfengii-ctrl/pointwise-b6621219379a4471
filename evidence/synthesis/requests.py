from dataclasses import dataclass
from evidence.cohorts.reader import read_cohort
from evidence.cohorts.network import read_network_cohort
from evidence.contrasts.orientation import resolve_direction
from evidence.contrasts.batch import build_direct_evidence
from evidence.synthesis.weights import inverse_variance_weights
from evidence.synthesis.pooling import pool_direct
from evidence.synthesis.contributions import build_contributions
from evidence.synthesis.network import (build_network_evidence, validate_network_requests,
                                        solve_network, answer_requests)
from evidence.results.artifact import build_artifact
from evidence.results.network_artifact import build_network_artifact
from evidence.results.publication import ResultPublisher
from evidence.results.network_publication import NetworkResultPublisher


@dataclass(frozen=True)
class DirectRequest:
    cohort_id: int
    left: str
    right: str


def validate_direct_request(cohort, left, right):
    direction = resolve_direction(cohort.pair, left, right)
    return DirectRequest(cohort.cohort_id, left, right), direction


class DirectAnalyzer:
    def __init__(self, repository):
        self.repository = repository

    def analyze_direct(self, cohort_id, left, right):
        with self.repository.transactions.atomic():
            cohort = read_cohort(self.repository, cohort_id)
            request, direction = validate_direct_request(cohort, left, right)
            evidence = build_direct_evidence(cohort, direction)
            weights = inverse_variance_weights(evidence)
            pooled = pool_direct(evidence, weights)
            contributions = build_contributions(evidence, weights, pooled)
            artifact = build_artifact(cohort, request, evidence, weights, pooled, contributions)
            result_id = ResultPublisher(self.repository).publish(artifact)
        return result_id


class NetworkAnalyzer:
    def __init__(self, repository):
        self.repository = repository

    def analyze_network(self, network_id, requests):
        validated = validate_network_requests(requests)
        with self.repository.transactions.atomic():
            network = read_network_cohort(self.repository, network_id)
            evidence = build_network_evidence(network)
            solution = solve_network(evidence)
            answers, covariance = answer_requests(solution, validated)
            artifact = build_network_artifact(network, solution, answers, covariance)
            result_id = NetworkResultPublisher(self.repository).publish(artifact)
        return result_id
