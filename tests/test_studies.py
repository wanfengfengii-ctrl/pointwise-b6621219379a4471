from fractions import Fraction
from tests import EvidenceCase, arms, snapshot
from evidence.studies.revisions import read_revision, read_current_revision


class TestStudyRevisions(EvidenceCase):
    def test_replay_and_correction(self):
        first = self.study(difference=1)
        self.assertEqual(self.study(difference=1), first)
        second = self.study(version="v2", difference=3)
        self.assertNotEqual(first, second)
        self.assertEqual(read_revision(self.repo, first).arms[0].mean, Fraction(1))
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, second)

    def test_arm_reorder_replay(self):
        first = self.study()
        before = snapshot(self.repo)
        self.assertEqual(self.studies.put_study("s", "v1", list(reversed(arms()))), first)
        self.assertEqual(snapshot(self.repo), before)

    def test_history_replay_pointer(self):
        first = self.study()
        second = self.study(version="alpha", difference=7)
        self.assertEqual(self.study(), first)
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, second)
        withdrawn = self.studies.withdraw_study("s", "withdraw")
        self.assertEqual(self.studies.withdraw_study("s", "withdraw"), withdrawn)
        self.assertEqual(self.study(), first)
        self.assertTrue(read_current_revision(self.repo, "s").withdrawn)
        revived = self.study(version="return", difference=-2)
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, revived)

    def test_identity_preservation_and_batch_replay(self):
        ids = self.studies.put_studies([
            {"study_id": "s", "source_version": "v", "arms": arms()},
            {"study_id": "s", "source_version": "v", "arms": list(reversed(arms()))},
            {"study_id": " s", "source_version": "v", "arms": arms()},
            {"study_id": "S", "source_version": "v", "arms": arms()}])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(read_revision(self.repo, ids[2]).study_id, " s")
