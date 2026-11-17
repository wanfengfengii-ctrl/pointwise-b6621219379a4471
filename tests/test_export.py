import json
import sys
from fractions import Fraction as F
from tests import EvidenceCase
from evidence.archive.repository import IntegrityError
from evidence.archive.encoding import encode_fraction, decode_fraction


class TestExportIntegrity(EvidenceCase):
    def prepared(self, difference=1, variances=(1, 1)):
        revision = self.study(difference=difference, variances=variances)
        cohort = self.cohorts.freeze_cohort([revision], ("A", "B"))
        result = self.analyzer.analyze_direct(cohort, "A", "B")
        return revision, cohort, result

    def test_roundtrip_and_broken_parent(self):
        _, cohort, result = self.prepared()
        exported = json.loads(self.exporter.export_result(result))
        self.assertEqual(exported["format_version"], 1)
        saved = exported["result"]
        differences, variances = [], []
        for member in saved["members"]:
            by_treatment = {arm["treatment"]: arm for arm in member["arms"]}
            # Independent oracle uses only serialized source arms.
            rational = lambda pair: F(int(pair[0]), int(pair[1]))
            differences.append(rational(by_treatment[saved["left"]]["mean"])
                               - rational(by_treatment[saved["right"]]["mean"]))
            variances.append(sum(rational(arm["variance"]) for arm in member["arms"]))
        total = sum(1 / variance for variance in variances)
        estimate = sum(d / v for d, v in zip(differences, variances)) / total
        self.assertEqual(estimate, F(*map(int, saved["estimate"])))
        self.assertEqual(1 / total, F(*map(int, saved["variance"])))
        self.repo.connection.execute("PRAGMA foreign_keys=OFF")
        self.repo.connection.execute("DELETE FROM cohort_members WHERE cohort_id=?", (cohort,))
        self.repo.connection.execute("DELETE FROM cohorts WHERE cohort_id=?", (cohort,))
        for operation in (self.reader.read_result, self.exporter.export_result):
            with self.assertRaises(IntegrityError):
                operation(result)

    def test_exact_encoding(self):
        big = F(10**40 + 1, 3)
        _, _, result = self.prepared(big, (F(1, 7), F(2, 11)))
        read = self.reader.read_result(result)
        self.assertEqual(read["estimate"], big)
        self.assertEqual(read["variance"], F(25, 77))
        exported = json.loads(self.exporter.export_result(result))["result"]
        self.assertEqual(exported["estimate"], [str(10**40 + 1), "3"])
        self.assertEqual(exported["variance"], ["25", "77"])
        self.assertEqual(decode_fraction(encode_fraction(big)), big)
        for bad in (["2", "4"], ["1", "-2"], ["01", "2"], ["-0", "1"],
                    [1, "2"], ["1", "0"], ["0", "2"]):
            with self.assertRaises(ValueError):
                decode_fraction(bad)

    def test_deterministic_export(self):
        _, _, result = self.prepared()
        first = self.exporter.export_result(result)
        self.assertEqual(first, self.exporter.export_result(result))
        self.study(version="v2", difference=8)
        self.studies.withdraw_study("s", "w")
        self.assertEqual(first, self.exporter.export_result(result))

    def test_no_recompute(self):
        _, _, result = self.prepared()
        expected = self.reader.read_result(result)
        exported = self.exporter.export_result(result)
        forbidden = {"analyze_direct", "build_direct_evidence", "calculate_difference",
                     "difference_variance", "inverse_variance_weights", "pool_direct",
                     "build_contributions", "verify_contributions", "build_artifact"}
        def guard(frame, event, arg):
            if (event == "call" and frame.f_globals.get("__name__", "").startswith("evidence.")
                    and frame.f_code.co_name in forbidden):
                raise AssertionError("reading invoked computation: " + frame.f_code.co_name)
        previous = sys.getprofile()
        sys.setprofile(guard)
        try:
            self.assertEqual(self.reader.read_result(result), expected)
            self.assertEqual(self.exporter.export_result(result), exported)
        finally:
            sys.setprofile(previous)

    def test_broken_membership(self):
        revision, cohort, result = self.prepared()
        self.repo.connection.execute("PRAGMA foreign_keys=OFF")
        self.repo.connection.execute("DELETE FROM arms WHERE revision_id=?", (revision,))
        self.repo.connection.execute("DELETE FROM revisions WHERE revision_id=?", (revision,))
        for operation in (self.reader.read_result, self.exporter.export_result):
            with self.assertRaises(IntegrityError):
                operation(result)

    def test_invalid_encoding_and_missing_result_row(self):
        _, _, result = self.prepared()
        self.repo.connection.execute("UPDATE result_evidence SET payload='{}' WHERE result_id=?",
                                     (result,))
        with self.assertRaises(IntegrityError):
            self.reader.read_result(result)
        with self.assertRaises(KeyError):
            self.reader.read_result(999)

    def test_unsupported_version(self):
        self.repo.connection.execute("UPDATE metadata SET version=2")
        with self.assertRaises(IntegrityError):
            self.repo.initialize()
