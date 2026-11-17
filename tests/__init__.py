import unittest
from evidence.archive.repository import Repository
from evidence.studies.revisions import StudyService
from evidence.cohorts.freeze import CohortService
from evidence.synthesis.requests import DirectAnalyzer
from evidence.results.reader import ResultReader
from evidence.results.export import ResultExporter


def arms(difference=1, variances=(1, 1), pair=("A", "B")):
    return [{"treatment": pair[0], "mean": difference, "variance": variances[0]},
            {"treatment": pair[1], "mean": 0, "variance": variances[1]}]


def snapshot(repository):
    tables = ("studies", "revisions", "arms", "cohorts", "cohort_members", "results",
              "result_evidence", "result_weights", "result_contributions")
    return tuple((name, tuple(tuple(row) for row in repository.connection.execute(
        f"SELECT * FROM {name} ORDER BY rowid"))) for name in tables)


class EvidenceCase(unittest.TestCase):
    def setUp(self):
        self.repo = Repository.open()
        self.studies = StudyService(self.repo)
        self.cohorts = CohortService(self.repo)
        self.analyzer = DirectAnalyzer(self.repo)
        self.reader = ResultReader(self.repo)
        self.exporter = ResultExporter(self.repo)

    def tearDown(self):
        self.repo.close()

    def study(self, id="s", version="v1", difference=1, variances=(1, 1), pair=("A", "B")):
        return self.studies.put_study(id, version, arms(difference, variances, pair))

    def result(self, revisions, left="A", right="B"):
        cohort = self.cohorts.freeze_cohort(revisions, (left, right))
        result = self.analyzer.analyze_direct(cohort, left, right)
        return self.reader.read_result(result)
