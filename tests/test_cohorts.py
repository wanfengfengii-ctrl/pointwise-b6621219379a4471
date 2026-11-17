from tests import EvidenceCase, snapshot
from evidence.cohorts.reader import read_cohort


class TestFrozenCohorts(EvidenceCase):
    def test_membership_rejection(self):
        first = self.study("one")
        other_pair = self.study("other", pair=("A", "C"))
        for ids in ([], [first, first], [first, other_pair]):
            before = snapshot(self.repo)
            with self.assertRaises(ValueError):
                self.cohorts.freeze_cohort(ids, ("A", "B"))
            self.assertEqual(snapshot(self.repo), before)
        before = snapshot(self.repo)
        with self.assertRaises(KeyError):
            self.cohorts.freeze_cohort([999], ("A", "B"))
        self.assertEqual(snapshot(self.repo), before)

    def test_same_study_versions(self):
        first = self.study()
        second = self.study(version="v2", difference=4)
        before = snapshot(self.repo)
        with self.assertRaises(ValueError):
            self.cohorts.freeze_cohort([first, second], ("A", "B"))
        self.assertEqual(snapshot(self.repo), before)

    def test_historical_active_selection(self):
        first = self.study()
        self.study(version="v2", difference=4)
        independent = self.study("other", difference=3)
        cohort = self.cohorts.freeze_cohort([independent, first], ("B", "A"))
        frozen = read_cohort(self.repo, cohort)
        self.assertEqual(frozen.pair, ("A", "B"))
        self.assertEqual([member.revision.revision_id for member in frozen.members],
                         [independent, first])
        result = self.reader.read_result(self.analyzer.analyze_direct(cohort, "A", "B"))
        self.assertEqual(result["estimate"], 2)
