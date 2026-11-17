import tempfile
from pathlib import Path
from fractions import Fraction as F
from tests import EvidenceCase, arms, snapshot
from evidence.archive.repository import Repository
from evidence.studies.revisions import StudyService
from evidence.cohorts.freeze import CohortService
from evidence.synthesis.requests import DirectAnalyzer
from evidence.results.reader import ResultReader


def interrupt(name):
    if name == "after_contributions":
        raise RuntimeError("publication interrupted after contributions")


class TestPublication(EvidenceCase):
    def test_failure_then_retry(self):
        with tempfile.TemporaryDirectory(prefix="evidence-publish-") as directory:
            path = Path(directory) / "archive.sqlite"
            with Repository.open(path) as repository:
                revision = StudyService(repository).put_study("s", "v1", arms())
                cohort = CohortService(repository).freeze_cohort([revision], ("A", "B"))
                before = snapshot(repository)
                repository.transactions.callback = interrupt
                with self.assertRaisesRegex(RuntimeError, "after contributions"):
                    DirectAnalyzer(repository).analyze_direct(cohort, "A", "B")
                self.assertEqual(snapshot(repository), before)
            with Repository.open(path) as repository:
                self.assertEqual(snapshot(repository), before)
                result = DirectAnalyzer(repository).analyze_direct(cohort, "A", "B")
                self.assertEqual(ResultReader(repository).read_result(result)["estimate"], F(1))
                for table in ("results", "result_evidence", "result_weights", "result_contributions"):
                    self.assertEqual(repository.connection.execute(
                        f"SELECT count(*) FROM {table}").fetchone()[0], 1)

    def test_fail_after_contributions(self):
        revision = self.study()
        cohort = self.cohorts.freeze_cohort([revision], ("A", "B"))
        existing = self.analyzer.analyze_direct(cohort, "A", "B")
        before = snapshot(self.repo)
        self.repo.transactions.callback = interrupt
        with self.assertRaises(RuntimeError):
            self.analyzer.analyze_direct(cohort, "A", "B")
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(self.reader.read_result(existing)["estimate"], F(1))
        self.repo.transactions.callback = None
        result = self.analyzer.analyze_direct(cohort, "A", "B")
        self.assertEqual(self.reader.read_result(result)["variance"], F(2))
