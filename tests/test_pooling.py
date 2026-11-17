from fractions import Fraction as F
from tests import EvidenceCase
from evidence.cohorts.reader import read_cohort
from evidence.contrasts.orientation import resolve_direction
from evidence.contrasts.batch import build_direct_evidence
from evidence.synthesis.weights import inverse_variance_weights
from evidence.synthesis.pooling import pool_direct
from evidence.synthesis.contributions import build_contributions, verify_contributions
from evidence.results.artifact import build_artifact
from evidence.results.publication import ResultPublisher
from evidence.synthesis.requests import DirectRequest
from dataclasses import replace


class TestDirectPooling(EvidenceCase):
    def test_exact_weighted_result(self):
        result = self.result([self.study("s1"), self.study("s2", difference=3)])
        self.assertEqual((result["estimate"], result["variance"]), (F(2), F(1)))
        self.assertEqual([m["raw_weight"] for m in result["members"]], [F(1, 2)] * 2)
        self.assertEqual([m["normalized_weight"] for m in result["members"]], [F(1, 2)] * 2)
        self.assertEqual([m["contribution"] for m in result["members"]], [F(1, 2), F(3, 2)])
        self.assertEqual(sum(m["contribution"] for m in result["members"]), result["estimate"])

    def test_unequal_variances(self):
        result = self.result([self.study("z", variances=(F(1, 2), F(3, 2))),
                              self.study("a", difference=3, variances=(3, 5))])
        self.assertEqual([m["variance"] for m in result["members"]], [F(2), F(8)])
        self.assertEqual([m["raw_weight"] for m in result["members"]], [F(1, 2), F(1, 8)])
        self.assertEqual([m["normalized_weight"] for m in result["members"]], [F(4, 5), F(1, 5)])
        self.assertEqual((result["estimate"], result["variance"]), (F(7, 5), F(8, 5)))
        self.assertEqual([m["contribution"] for m in result["members"]], [F(4, 5), F(3, 5)])

    def test_contribution_identity(self):
        z, a = self.study("z"), self.study("a", difference=3)
        for ids in ([z, a], [a, z]):
            result = self.result(ids)
            self.assertEqual([row["revision_id"] for row in result["members"]], ids)
            self.assertEqual({row["study_id"]: row["contribution"] for row in result["members"]},
                             {"z": F(1, 2), "a": F(3, 2)})

    def test_reject_misbound_contributions(self):
        ids = [self.study("z"), self.study("a", difference=3)]
        cid = self.cohorts.freeze_cohort(ids, ("A", "B"))
        cohort = read_cohort(self.repo, cid)
        evidence = build_direct_evidence(cohort, resolve_direction(cohort.pair, "A", "B"))
        weights = inverse_variance_weights(evidence)
        pooled = pool_direct(evidence, weights)
        contributions = build_contributions(evidence, weights, pooled)
        wrong = (replace(contributions[0], value=F(3, 2)),
                 replace(contributions[1], value=F(1, 2)))
        with self.assertRaises(ValueError):
            verify_contributions(evidence, weights, pooled, wrong)
        artifact = build_artifact(cohort, DirectRequest(cid, "A", "B"),
                                  evidence, weights, pooled, contributions)
        with self.assertRaises(ValueError):
            ResultPublisher(self.repo).publish(replace(artifact, contributions=wrong))
        self.assertEqual(self.repo.connection.execute("SELECT count(*) FROM results").fetchone()[0], 0)
