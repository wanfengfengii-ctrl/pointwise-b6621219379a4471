from tests import EvidenceCase, arms, snapshot


class TestContrastOrientation(EvidenceCase):
    def test_reverse_and_reorder(self):
        first = self.study("one", difference=2, variances=(1, 3))
        second = self.studies.put_study("two", "v1", list(reversed(arms(2, (1, 3)))))
        forward = self.result([first, second])
        reverse = self.result([first, second], "B", "A")
        self.assertEqual(forward["estimate"], 2)
        self.assertEqual(reverse["estimate"], -2)
        self.assertEqual(forward["variance"], reverse["variance"])
        for positive, negative in zip(forward["members"], reverse["members"]):
            for field in ("difference", "contribution"):
                self.assertEqual(positive[field], -negative[field])
            for field in ("variance", "raw_weight", "normalized_weight"):
                self.assertEqual(positive[field], negative[field])
        self.assertEqual(forward["members"][0]["difference"], forward["members"][1]["difference"])

    def test_direction_contract(self):
        cid = self.cohorts.freeze_cohort([self.study()], ("A", "B"))
        for left, right in (("A", "A"), ("A", "C"), ("", "B")):
            before = snapshot(self.repo)
            with self.assertRaises(ValueError):
                self.analyzer.analyze_direct(cid, left, right)
            self.assertEqual(snapshot(self.repo), before)
        with self.assertRaises(KeyError):
            self.analyzer.analyze_direct(999, "A", "B")
