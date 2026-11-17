import tempfile
import unittest
from pathlib import Path
from fractions import Fraction as F
from tests import arms, snapshot
from evidence.archive.repository import Repository, IntegrityError
from evidence.studies.revisions import StudyService, read_current_revision
from evidence.cohorts.freeze import CohortService
from evidence.synthesis.requests import DirectAnalyzer
from evidence.results.reader import ResultReader
from evidence.results.export import ResultExporter


class TestHistoricalResults(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="evidence-history-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "archive.sqlite"
        self.repo = Repository.open(self.path)

    def tearDown(self):
        self.repo.close()

    def reopen(self):
        self.repo.close()
        self.repo = Repository.open(self.path)

    def seed(self):
        revision = StudyService(self.repo).put_study("s", "v1", arms())
        cohort = CohortService(self.repo).freeze_cohort([revision], ("A", "B"))
        return revision, cohort

    def test_correction_withdrawal_and_reopen(self):
        revision, cohort = self.seed()
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        exported = ResultExporter(self.repo).export_result(result)
        corrected = StudyService(self.repo).put_study("s", "v2", arms(9))
        fresh = CohortService(self.repo).freeze_cohort([corrected], ("A", "B"))
        fresh_result = DirectAnalyzer(self.repo).analyze_direct(fresh, "A", "B")
        self.assertEqual(ResultReader(self.repo).read_result(fresh_result)["estimate"], F(9))
        StudyService(self.repo).withdraw_study("s", "w")
        self.reopen()
        self.assertEqual(ResultExporter(self.repo).export_result(result), exported)
        old = ResultReader(self.repo).read_result(result)
        self.assertEqual(old["members"][0]["revision_id"], revision)
        self.assertEqual(old["estimate"], F(1))
        before = snapshot(self.repo)
        with self.assertRaises(ValueError):
            CohortService(self.repo).freeze_cohort([revision], ("A", "B"))
        self.assertEqual(snapshot(self.repo), before)

    def test_withdrawn_selection(self):
        revision, cohort = self.seed()
        withdrawn = StudyService(self.repo).withdraw_study("s", "w")
        before = snapshot(self.repo)
        for selected in ([revision], [withdrawn]):
            with self.assertRaises(ValueError):
                CohortService(self.repo).freeze_cohort(selected, ("A", "B"))
            self.assertEqual(snapshot(self.repo), before)
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        self.assertEqual(ResultReader(self.repo).read_result(result)["estimate"], F(1))

    def test_correction_before_analysis(self):
        revision, cohort = self.seed()
        StudyService(self.repo).put_study("s", "v2", arms(99))
        self.reopen()
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        read = ResultReader(self.repo).read_result(result)
        self.assertEqual(read["estimate"], F(1))
        self.assertEqual(read["members"][0]["revision_id"], revision)

    def test_copy_isolation(self):
        _, cohort = self.seed()
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        original = ResultReader(self.repo).read_result(result)
        changed = ResultReader(self.repo).read_result(result)
        changed["members"][0]["arms"][0]["mean"] = F(999)
        changed["members"].clear()
        changed["pair"].append("alien")
        changed["estimate"] = F(-7)
        self.assertEqual(ResultReader(self.repo).read_result(result), original)

    def test_init_idempotence(self):
        _, cohort = self.seed()
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        corrected = StudyService(self.repo).put_study("s", "v2", arms(7))
        exported = ResultExporter(self.repo).export_result(result)
        before = snapshot(self.repo)
        for _ in range(2):
            self.repo.initialize()
            self.reopen()
            self.assertEqual(snapshot(self.repo), before)
            self.assertEqual(read_current_revision(self.repo, "s").revision_id, corrected)
            self.assertEqual(ResultExporter(self.repo).export_result(result), exported)

    def test_rejected_batch_survives_reopen(self):
        self.seed()
        before = snapshot(self.repo)
        with self.assertRaises(ValueError):
            StudyService(self.repo).put_studies([
                {"study_id": "s", "source_version": "v2", "arms": arms(8)},
                {"study_id": "s", "source_version": "v1", "arms": arms(4)}])
        self.reopen()
        self.assertEqual(snapshot(self.repo), before)

    def test_exact_export_reopen(self):
        mean = F(10**40 + 1, 3)
        revision = StudyService(self.repo).put_study("large", "v1", arms(mean, (F(1, 7), F(2, 11))))
        cohort = CohortService(self.repo).freeze_cohort([revision], ("A", "B"))
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        exported = ResultExporter(self.repo).export_result(result)
        self.reopen()
        self.assertEqual(ResultReader(self.repo).read_result(result)["estimate"], mean)
        self.assertEqual(ResultReader(self.repo).read_result(result)["variance"], F(25, 77))
        self.assertEqual(ResultExporter(self.repo).export_result(result), exported)

    def test_workday_sample(self):
        import json
        sample_path = Path(__file__).resolve().parents[1] / "examples" / "day.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        revisions = StudyService(self.repo).put_studies(sample["studies"])
        cohort = CohortService(self.repo).freeze_cohort(revisions, sample["pair"])
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, *sample["request"])
        report = ResultReader(self.repo).read_result(result)
        self.assertEqual((report["estimate"], report["variance"]), (F(7, 5), F(8, 5)))
        exported = ResultExporter(self.repo).export_result(result)
        corrected = StudyService(self.repo).put_studies(sample["corrections"])[0]
        new_cohort = CohortService(self.repo).freeze_cohort([corrected, revisions[1]], sample["pair"])
        new_result = DirectAnalyzer(self.repo).analyze_direct(new_cohort, *sample["request"])
        self.assertEqual(ResultReader(self.repo).read_result(new_result)["estimate"], F(39, 5))
        self.reopen()
        self.assertEqual(ResultExporter(self.repo).export_result(result), exported)
