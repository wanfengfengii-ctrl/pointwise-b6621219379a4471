from tests import EvidenceCase, arms, snapshot
from evidence.studies.identity import ConflictError
from evidence.studies.revisions import read_current_revision


class TestStudyValidation(EvidenceCase):
    def test_atomic_rejection(self):
        self.study("existing")
        before = snapshot(self.repo)
        for bad, error in ((arms(2, (0, 1)), ValueError), (arms(4), ConflictError)):
            with self.subTest(error=error):
                with self.assertRaises(error):
                    self.studies.put_studies([
                        {"study_id": "new", "source_version": "v1", "arms": arms()},
                        {"study_id": "existing", "source_version": "v1", "arms": bad}])
                self.assertEqual(snapshot(self.repo), before)

    def test_batch_rollback(self):
        first = self.study("s")
        self.study("other")
        before = snapshot(self.repo)
        with self.assertRaises(ConflictError):
            self.studies.put_studies([
                {"study_id": "s", "source_version": "v2", "arms": arms(9)},
                {"study_id": "other", "source_version": "v1", "arms": arms(4)}])
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, first)
        with self.assertRaises(ConflictError):
            self.studies.put_studies([
                {"study_id": "new", "source_version": "v", "arms": arms()},
                {"study_id": "new", "source_version": "v", "arms": arms(4)}])
        self.assertEqual(snapshot(self.repo), before)

    def test_version_conflict(self):
        self.study()
        before = snapshot(self.repo)
        for changed in (arms(2), arms(1, (2, 1))):
            with self.assertRaises(ConflictError):
                self.studies.put_study("s", "v1", changed)
        with self.assertRaises(ConflictError):
            self.studies.withdraw_study("s", "v1")
        self.assertEqual(snapshot(self.repo), before)
        self.studies.withdraw_study("s", "withdraw")
        after = snapshot(self.repo)
        with self.assertRaises(ConflictError):
            self.studies.put_study("s", "withdraw", arms())
        with self.assertRaises(KeyError):
            self.studies.withdraw_study("unknown", "w")
        self.assertEqual(snapshot(self.repo), after)

    def test_numeric_boundary(self):
        invalid = (True, 1.0, None, "NaN", "Infinity", "-Infinity", "1/0", "")
        for bad in invalid:
            for field in ("mean", "variance"):
                with self.subTest(value=bad, field=field):
                    values = arms()
                    values[0][field] = bad
                    before = snapshot(self.repo)
                    with self.assertRaises(ValueError):
                        self.studies.put_study("s", "v", values)
                    self.assertEqual(snapshot(self.repo), before)
        for bad in (0, -1, "-2/3"):
            with self.assertRaises(ValueError):
                self.studies.put_study("s", "v", arms(1, (bad, 1)))
        for bad in ("", " ", None, 1):
            with self.assertRaises(ValueError):
                self.studies.put_study(bad, "v", arms())

    def test_v1_arm_limit(self):
        for values in (arms()[:1], arms() + [dict(arms()[0], treatment="C")],
                       [arms()[0], arms()[0]]):
            before = snapshot(self.repo)
            with self.assertRaises(ValueError):
                self.studies.put_study("s", "v", values)
            self.assertEqual(snapshot(self.repo), before)

    def test_nested_transaction_rollback(self):
        before = snapshot(self.repo)
        with self.assertRaisesRegex(RuntimeError, "outer"):
            with self.repo.transactions.atomic():
                self.study()
                with self.repo.transactions.atomic():
                    self.study("another")
                raise RuntimeError("outer")
        self.assertEqual(snapshot(self.repo), before)
        with self.repo.transactions.atomic():
            self.study("kept")
            try:
                with self.repo.transactions.atomic():
                    self.study("discarded")
                    raise RuntimeError("inner")
            except RuntimeError:
                pass
        self.assertEqual(read_current_revision(self.repo, "kept").study_id, "kept")
        with self.assertRaises(KeyError):
            read_current_revision(self.repo, "discarded")
