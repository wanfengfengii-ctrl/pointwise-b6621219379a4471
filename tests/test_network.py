import json
import sys
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path
from tests import EvidenceCase, arms, snapshot
from evidence.archive.repository import Repository, IntegrityError
from evidence.studies.identity import ConflictError
from evidence.studies.revisions import StudyService, read_revision, read_current_revision
from evidence.cohorts.freeze import CohortService
from evidence.synthesis.requests import DirectAnalyzer, NetworkAnalyzer
from evidence.results.reader import ResultReader
from evidence.results.export import ResultExporter

NETWORK_TABLES = ("networks", "network_members", "network_results",
                  "network_result_members")


def full_snapshot(repository):
    return snapshot(repository) + tuple(
        (name, tuple(tuple(row) for row in repository.connection.execute(
            f"SELECT * FROM {name} ORDER BY rowid"))) for name in NETWORK_TABLES)


def invert_fractions(matrix):
    """Independent exact inversion used only by the test oracle."""
    size = len(matrix)
    aug = [list(row) + [F(1) if i == j else F(0) for j in range(size)]
           for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = next(r for r in range(col, size) if aug[r][col])
        aug[col], aug[pivot] = aug[pivot], aug[col]
        aug[col] = [value / aug[col][col] for value in aug[col]]
        for r in range(size):
            if r != col and aug[r][col]:
                aug[r] = [a - aug[r][col] * b for a, b in zip(aug[r], aug[col])]
    return [row[size:] for row in aug]


def oracle_answer(studies, requests):
    """Independent oracle: full design-matrix WLS, study intercepts kept.

    The reference treatment is the last of each component, unlike the
    production solver, and no intercept absorption is used.
    """
    treatments = sorted({t for study in studies for t in study})
    adjacent = {t: set() for t in treatments}
    for study in studies:
        for t in study:
            adjacent[t].update(u for u in study if u != t)
    placement, components = {}, []
    for seed in treatments:
        if seed in placement:
            continue
        component, stack = [], [seed]
        while stack:
            current = stack.pop()
            if current in placement:
                continue
            placement[current] = len(components)
            component.append(current)
            stack.extend(sorted(adjacent[current]))
        components.append(sorted(component))
    thetas, covariances = {}, {}
    for index, component in enumerate(components):
        members = [study for study in studies if set(study) & set(component)]
        reference = component[-1]
        params = [("alpha", i) for i in range(len(members))]
        params += [("theta", t) for t in component if t != reference]
        slot = {p: i for i, p in enumerate(params)}
        size = len(params)
        matrix = [[F(0)] * size for _ in range(size)]
        rhs = [F(0)] * size
        for i, study in enumerate(members):
            for t, (mean, variance) in study.items():
                weight = F(1) / variance
                row = [("alpha", i)] + ([("theta", t)] if t != reference else [])
                for a in row:
                    rhs[slot[a]] += weight * mean
                    for b in row:
                        matrix[slot[a]][slot[b]] += weight
        inverse = invert_fractions(matrix)
        beta = [sum(inverse[i][j] * rhs[j] for j in range(size)) for i in range(size)]
        thetas[index] = {t: (F(0) if t == reference else beta[slot[("theta", t)]])
                         for t in component}
        covariances[index] = {(t, u): (F(0) if reference in (t, u) else
                                       inverse[slot[("theta", t)]][slot[("theta", u)]])
                              for t in component for u in component}
    status, estimates = [], []
    for left, right in requests:
        if left == right:
            status.append("estimable")
            estimates.append(F(0))
        elif placement[left] == placement[right]:
            status.append("estimable")
            estimates.append(thetas[placement[left]][left]
                             - thetas[placement[right]][right])
        else:
            status.append("not_estimable")
            estimates.append(None)
    covariance = []
    for i, (left_i, right_i) in enumerate(requests):
        row = []
        for j, (left_j, right_j) in enumerate(requests):
            if status[i] == "not_estimable" or status[j] == "not_estimable":
                row.append(None)
            elif left_i == right_i or left_j == right_j \
                    or placement[left_i] != placement[left_j]:
                row.append(F(0))
            else:
                cov = covariances[placement[left_i]]
                row.append(cov[(left_i, left_j)] - cov[(left_i, right_j)]
                           - cov[(right_i, left_j)] + cov[(right_i, right_j)])
        covariance.append(row)
    return status, estimates, covariance


def study_dict(*entries):
    return {treatment: (F(mean), F(variance)) for treatment, mean, variance in entries}


class NetworkCase(EvidenceCase):
    def setUp(self):
        super().setUp()
        self.network_analyzer = NetworkAnalyzer(self.repo)

    def network_report(self, revisions, requests):
        network = self.cohorts.freeze_network(list(revisions))
        result = self.network_analyzer.analyze_network(network, requests)
        return self.reader.read_network(result), result, network


class TestMultiarmRegistration(NetworkCase):
    def test_save_and_read_multiarm(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "C", "mean": "2", "variance": "1"},
            {"treatment": "A", "mean": "1/3", "variance": "1/2"},
            {"treatment": "B", "mean": 1, "variance": "3/2"}])
        restored = read_revision(self.repo, revision)
        self.assertEqual([arm.treatment for arm in restored.arms], ["A", "B", "C"])
        self.assertEqual(restored.arms[0].mean, F(1, 3))
        self.assertEqual(restored.arms[0].variance, F(1, 2))
        self.assertFalse(restored.withdrawn)
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, revision)

    def test_replay_arm_order_and_pointer(self):
        first = self.studies.save_multiarm("s", "v1", [
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        second = self.studies.save_multiarm("s", "v2", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 5, "variance": 1}])
        before = full_snapshot(self.repo)
        replay = self.studies.save_multiarm("s", "v1", [
            {"treatment": "C", "mean": 2, "variance": 1},
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        self.assertEqual(replay, first)
        self.assertEqual(full_snapshot(self.repo), before)
        self.assertEqual(read_current_revision(self.repo, "s").revision_id, second)

    def test_conflicts(self):
        base = [{"treatment": "A", "mean": 0, "variance": 1},
                {"treatment": "B", "mean": 1, "variance": 1},
                {"treatment": "C", "mean": 2, "variance": 1}]
        self.studies.save_multiarm("s", "v1", base)
        before = full_snapshot(self.repo)
        changed_stats = [dict(row) for row in base]
        changed_stats[0]["mean"] = 9
        changed_set = base[:2]
        for bad in (changed_stats, changed_set):
            with self.assertRaises(ConflictError):
                self.studies.save_multiarm("s", "v1", bad)
        with self.assertRaises(ConflictError):
            self.studies.withdraw_study("s", "v1")
        self.assertEqual(full_snapshot(self.repo), before)
        self.studies.withdraw_study("s", "w")
        after = full_snapshot(self.repo)
        with self.assertRaises(ConflictError):
            self.studies.save_multiarm("s", "w", base)
        self.assertEqual(full_snapshot(self.repo), after)

    def test_shared_identity_with_v1(self):
        two = [{"treatment": "A", "mean": 1, "variance": 1},
               {"treatment": "B", "mean": 0, "variance": 1}]
        revision = self.studies.put_study("s", "v1", two)
        self.assertEqual(self.studies.save_multiarm("s", "v1", list(reversed(two))),
                         revision)
        with self.assertRaises(ConflictError):
            self.studies.save_multiarm("s", "v1", two + [
                {"treatment": "C", "mean": 0, "variance": 1}])
        other = self.studies.save_multiarm("t", "v1", two + [
            {"treatment": "C", "mean": 2, "variance": 1}])
        self.assertEqual(self.studies.put_study("t", "v2", two),
                         read_current_revision(self.repo, "t").revision_id)
        self.assertNotEqual(other, revision)

    def test_arm_count_and_duplicate_limits(self):
        def entry(n):
            return [{"treatment": f"T{i}", "mean": i, "variance": 1} for i in range(n)]
        for bad in (entry(1), entry(7)):
            before = full_snapshot(self.repo)
            with self.assertRaises(ValueError):
                self.studies.save_multiarm("s", "v1", bad)
            self.assertEqual(full_snapshot(self.repo), before)
        six = self.studies.save_multiarm("s", "v1", entry(6))
        self.assertEqual(len(read_revision(self.repo, six).arms), 6)
        with self.assertRaises(ValueError):
            self.studies.save_multiarm("d", "v1", [
                {"treatment": "A", "mean": 0, "variance": 1},
                {"treatment": "A", "mean": 1, "variance": 1}])
        with self.assertRaises(ValueError):
            self.studies.put_study("v", "v1", entry(3))

    def test_numeric_and_identity_rules(self):
        for bad in (True, 1.5, None, "NaN", "Infinity", "-Infinity", "1/0", ""):
            for field in ("mean", "variance"):
                values = [{"treatment": "A", "mean": 0, "variance": 1},
                          {"treatment": "B", "mean": 1, "variance": 1},
                          {"treatment": "C", "mean": 2, "variance": 1}]
                values[1][field] = bad
                before = full_snapshot(self.repo)
                with self.assertRaises(ValueError):
                    self.studies.save_multiarm("s", "v1", values)
                self.assertEqual(full_snapshot(self.repo), before)
        for bad in (0, -1, "-2/3"):
            with self.assertRaises(ValueError):
                self.studies.save_multiarm("s", "v1", [
                    {"treatment": "A", "mean": 0, "variance": bad},
                    {"treatment": "B", "mean": 1, "variance": 1}])
        for bad in ("", " ", None, 1):
            with self.assertRaises(ValueError):
                self.studies.save_multiarm(bad, "v1", [
                    {"treatment": "A", "mean": 0, "variance": 1},
                    {"treatment": "B", "mean": 1, "variance": 1}])

    def test_input_mutation_isolation(self):
        records = [{"treatment": "A", "mean": 0, "variance": 1},
                   {"treatment": "B", "mean": 1, "variance": 1},
                   {"treatment": "C", "mean": 2, "variance": 1}]
        revision = self.studies.save_multiarm("s", "v1", records)
        records[0]["mean"] = 999
        records.append({"treatment": "D", "mean": 3, "variance": 1})
        restored = read_revision(self.repo, revision)
        self.assertEqual(len(restored.arms), 3)
        self.assertEqual(restored.arms[0].mean, F(0))


class TestNetworkFreeze(NetworkCase):
    def multiarm(self, study_id, pairs, version="v1"):
        return self.studies.save_multiarm(study_id, version, [
            {"treatment": t, "mean": m, "variance": v} for t, m, v in pairs])

    def test_freeze_preserves_order_and_defers_fit(self):
        one = self.multiarm("one", [("A", 0, 1), ("B", 1, 1), ("C", 2, 1)])
        two = self.multiarm("two", [("B", 10, 1), ("C", 12, 1)])
        three = self.multiarm("three", [("D", 4, 1), ("E", 7, 1)])
        network = self.cohorts.freeze_network([three, one, two])
        self.assertIsInstance(network, int)
        stored = self.repo.load_network(network)
        self.assertEqual([m["revision_id"] for m in stored["members"]],
                         [three, one, two])
        self.assertEqual(self.repo.connection.execute(
            "SELECT count(*) FROM network_results").fetchone()[0], 0)
        report, _, _ = self.network_report([three, one, two], [("E", "D")])
        self.assertEqual([m["position"] for m in report["members"]], [0, 1, 2])
        self.assertEqual([m["revision_id"] for m in report["members"]],
                         [three, one, two])

    def test_size_limits(self):
        revisions = [self.study(f"s{i}") for i in range(81)]
        network = self.cohorts.freeze_network(revisions[:80])
        self.assertIsInstance(network, int)
        before = full_snapshot(self.repo)
        with self.assertRaises(ValueError):
            self.cohorts.freeze_network(revisions)
        self.assertEqual(full_snapshot(self.repo), before)
        with self.assertRaises(ValueError):
            self.cohorts.freeze_network([])
        self.assertEqual(full_snapshot(self.repo), before)

    def test_treatment_limit(self):
        revisions = [self.multiarm(f"s{i}", [(f"T{2*i}", 0, 1), (f"T{2*i+1}", 1, 1)])
                       for i in range(10)]
        network = self.cohorts.freeze_network(revisions)
        self.assertIsInstance(network, int)
        extra = self.multiarm("extra", [("T0", 0, 1), ("T20", 1, 1)])
        before = full_snapshot(self.repo)
        with self.assertRaises(ValueError):
            self.cohorts.freeze_network(revisions + [extra])
        self.assertEqual(full_snapshot(self.repo), before)

    def test_selection_rejections(self):
        first = self.study("one")
        second_version = self.study("one", "v2", difference=4)
        other = self.multiarm("two", [("A", 0, 1), ("C", 2, 1)])
        for ids in ([first, first], [first, second_version], [999], [first, "x"]):
            before = full_snapshot(self.repo)
            with self.assertRaises((ValueError, KeyError)):
                self.cohorts.freeze_network(ids)
            self.assertEqual(full_snapshot(self.repo), before)
        for bad in ("12", {"r": first}, {first}, None, 1):
            with self.assertRaises(ValueError):
                self.cohorts.freeze_network(bad)
        self.assertEqual(full_snapshot(self.repo), before)
        network = self.cohorts.freeze_network((first, other))
        self.assertIsInstance(network, int)

    def test_withdrawal_rules(self):
        revision = self.multiarm("s", [("A", 0, 1), ("B", 1, 1), ("C", 2, 1)])
        second = self.multiarm("s", [("A", 0, 1), ("B", 3, 1), ("C", 2, 1)], "v2")
        historical_ok = self.cohorts.freeze_network([revision])
        self.assertIsInstance(historical_ok, int)
        withdrawn = self.studies.withdraw_study("s", "w")
        for ids in ([revision], [withdrawn], [second]):
            before = full_snapshot(self.repo)
            with self.assertRaises(ValueError):
                self.cohorts.freeze_network(ids)
            self.assertEqual(full_snapshot(self.repo), before)

    def test_freeze_cohort_still_two_arm_only(self):
        multi = self.multiarm("m", [("A", 0, 1), ("B", 1, 1), ("C", 2, 1)])
        before = full_snapshot(self.repo)
        with self.assertRaises(ValueError):
            self.cohorts.freeze_cohort([multi], ("A", "B"))
        self.assertEqual(full_snapshot(self.repo), before)
        two = self.multiarm("t", [("B", 1, 1), ("A", 0, 1)])
        cohort = self.cohorts.freeze_cohort([two], ("A", "B"))
        self.assertEqual(self.reader.read_result(
            self.analyzer.analyze_direct(cohort, "A", "B"))["estimate"], F(-1))


class TestNetworkAnalysis(NetworkCase):
    def test_shared_control_handcase(self):
        revision = self.studies.save_multiarm("three", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        report, _, _ = self.network_report([revision], [("B", "A"), ("C", "A")])
        self.assertEqual(report["estimates"], [F(1), F(2)])
        self.assertEqual(report["covariance"],
                         [[F(2), F(1)], [F(1), F(2)]])
        self.assertEqual(report["treatments"], ["A", "B", "C"])

    def test_indirect_handcase(self):
        ab = self.studies.save_multiarm("ab", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        bc = self.studies.save_multiarm("bc", "v1", [
            {"treatment": "B", "mean": 10, "variance": 1},
            {"treatment": "C", "mean": 12, "variance": 1}])
        report, _, _ = self.network_report([ab, bc], [("C", "A")])
        self.assertEqual(report["estimates"], [F(3)])
        self.assertEqual(report["covariance"], [[F(4)]])

    def test_disconnected_handcase(self):
        ab = self.studies.save_multiarm("ab", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        cd = self.studies.save_multiarm("cd", "v1", [
            {"treatment": "C", "mean": 4, "variance": 1},
            {"treatment": "D", "mean": 7, "variance": 1}])
        report, _, _ = self.network_report([ab, cd], [("A", "C"), ("B", "A")])
        self.assertEqual(report["status"], ["not_estimable", "estimable"])
        self.assertEqual(report["estimates"], [None, F(1)])
        self.assertEqual(report["covariance"], [[None, None], [None, F(2)]])

    def test_mixed_evidence_against_oracle(self):
        abc = self.studies.save_multiarm("abc", "v1", [
            {"treatment": "A", "mean": "1/3", "variance": "1/2"},
            {"treatment": "B", "mean": "5/3", "variance": "3/2"},
            {"treatment": "C", "mean": "7/3", "variance": "2/5"}])
        ab = self.study("ab", difference=2, variances=(F(1, 2), F(3, 2)))
        bc = self.studies.save_multiarm("bc", "v1", [
            {"treatment": "B", "mean": 10, "variance": 2},
            {"treatment": "C", "mean": 13, "variance": 1}])
        de = self.studies.save_multiarm("de", "v1", [
            {"treatment": "D", "mean": 4, "variance": 1},
            {"treatment": "E", "mean": 7, "variance": 1}])
        requests = [("B", "A"), ("C", "A"), ("C", "B"), ("E", "D"), ("A", "D"),
                    ("A", "A"), ("B", "C"), ("D", "E")]
        report, _, _ = self.network_report([abc, ab, bc, de], requests)
        studies = [study_dict(("A", F(1, 3), F(1, 2)), ("B", F(5, 3), F(3, 2)),
                              ("C", F(7, 3), F(2, 5))),
                   study_dict(("A", 2, F(1, 2)), ("B", 0, F(3, 2))),
                   study_dict(("B", 10, 2), ("C", 13, 1)),
                   study_dict(("D", 4, 1), ("E", 7, 1))]
        status, estimates, covariance = oracle_answer(studies, requests)
        self.assertEqual(report["status"], status)
        self.assertEqual(report["estimates"], estimates)
        self.assertEqual(report["covariance"], covariance)
        self.assertEqual(report["treatments"], ["A", "B", "C", "D", "E"])

    def test_permutation_invariance(self):
        def build(reverse):
            entries = [("one", [("A", 0, 1), ("B", 1, 1), ("C", 2, 1)]),
                       ("two", [("B", 10, 2), ("C", 12, 1)]),
                       ("three", [("A", "1/2", "1/2"), ("C", "5/2", "3/2")])]
            if reverse:
                entries = [(name, list(reversed(spec))) for name, spec in
                           reversed(entries)]
            revisions = [self.studies.save_multiarm(name, "v1", [
                {"treatment": t, "mean": m, "variance": v} for t, m, v in spec])
                for name, spec in entries]
            network = self.cohorts.freeze_network(revisions)
            result = self.network_analyzer.analyze_network(
                network, [("C", "A"), ("B", "A"), ("C", "B")])
            report = self.reader.read_network(result)
            return report["status"], report["estimates"], report["covariance"]
        forward = build(False)
        with Repository.open() as other:
            service = StudyService(other)
            entries = [("one", [("A", 0, 1), ("B", 1, 1), ("C", 2, 1)]),
                       ("two", [("B", 10, 2), ("C", 12, 1)]),
                       ("three", [("A", "1/2", "1/2"), ("C", "5/2", "3/2")])]
            revisions = [service.save_multiarm(name, "v1", [
                {"treatment": t, "mean": m, "variance": v} for t, m, v in spec])
                for name, spec in reversed(entries)]
            network = CohortService(other).freeze_network(revisions)
            result = NetworkAnalyzer(other).analyze_network(
                network, [("C", "A"), ("B", "A"), ("C", "B")])
            backward_report = ResultReader(other).read_network(result)
            backward = (backward_report["status"], backward_report["estimates"],
                        backward_report["covariance"])
        self.assertEqual(forward, backward)

    def test_common_mean_shift_invariance(self):
        def contrast(shift):
            revision = self.studies.save_multiarm(f"s{shift}", "v1", [
                {"treatment": "A", "mean": F(0) + shift, "variance": 1},
                {"treatment": "B", "mean": F(1) + shift, "variance": 1},
                {"treatment": "C", "mean": F(2) + shift, "variance": 1}])
            network = self.cohorts.freeze_network([revision])
            result = self.network_analyzer.analyze_network(
                network, [("B", "A"), ("C", "A"), ("C", "B")])
            report = self.reader.read_network(result)
            return report["estimates"], report["covariance"]
        self.assertEqual(contrast(F(0)), contrast(F(10**30, 7)))

    def test_reverse_duplicate_and_self_requests(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        requests = [("B", "A"), ("A", "B"), ("B", "A"), ("A", "A"), ("C", "C")]
        report, _, _ = self.network_report([revision], requests)
        self.assertEqual(report["estimates"], [F(1), F(-1), F(1), F(0), F(0)])
        self.assertEqual(report["requests"], [["B", "A"], ["A", "B"], ["B", "A"],
                                              ["A", "A"], ["C", "C"]])
        for j, expected in enumerate([F(2), F(-2), F(2), F(0), F(0)]):
            self.assertEqual(report["covariance"][0][j], expected)
        self.assertEqual(report["covariance"][3], [F(0)] * 5)
        self.assertEqual(report["covariance"][4], [F(0)] * 5)

    def test_empty_requests_publish(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        report, result, network = self.network_report([revision], [])
        self.assertEqual(report["network_id"], network)
        self.assertEqual(report["result_id"], result)
        for key in ("requests", "status", "estimates", "covariance"):
            self.assertEqual(report[key], [])
        self.assertEqual(len(report["members"]), 1)
        exported = json.loads(self.exporter.export_network(result))
        self.assertEqual(exported["result"]["covariance"], [])

    def test_request_validation(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        network = self.cohorts.freeze_network([revision])
        ok = self.network_analyzer.analyze_network(network, [("A", "B")] * 8)
        self.assertIsInstance(ok, int)
        before = full_snapshot(self.repo)
        for bad in ([("A", "B")] * 9, "AB", [("A",)], [("A", "B", "A")],
                    [("A", 1)], [("A", "")], [(" ", "A")],
                    [{"A": "B"}], [None]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.network_analyzer.analyze_network(network, bad)
                self.assertEqual(full_snapshot(self.repo), before)
        for unknown in ([("A", "Z")], [("Z", "Z")], [("A", "B"), ("Z", "A")]):
            with self.assertRaises(KeyError):
                self.network_analyzer.analyze_network(network, unknown)
            self.assertEqual(full_snapshot(self.repo), before)
        with self.assertRaises(KeyError):
            self.network_analyzer.analyze_network(999, [])
        self.assertEqual(full_snapshot(self.repo), before)

    def test_direct_entry_rejects_network_id(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        network = self.cohorts.freeze_network([revision])
        network_result = self.network_analyzer.analyze_network(network, [("B", "A")])
        before = full_snapshot(self.repo)
        with self.assertRaises(KeyError):
            self.analyzer.analyze_direct(network, "A", "B")
        with self.assertRaises(KeyError):
            self.reader.read_network(999)
        with self.assertRaises(KeyError):
            self.reader.read_result(network_result)
        self.assertEqual(full_snapshot(self.repo), before)


class TestNetworkPublication(NetworkCase):
    def test_checkpoint_failure_rolls_back_and_retries(self):
        with tempfile.TemporaryDirectory(prefix="evidence-network-") as directory:
            path = Path(directory) / "archive.sqlite"
            with Repository.open(path) as repository:
                revision = StudyService(repository).save_multiarm("s", "v1", [
                    {"treatment": "A", "mean": 0, "variance": 1},
                    {"treatment": "B", "mean": 1, "variance": 1},
                    {"treatment": "C", "mean": 2, "variance": 1}])
                network = CohortService(repository).freeze_network([revision])
                existing = NetworkAnalyzer(repository).analyze_network(
                    network, [("B", "A")])
                before = full_snapshot(repository)
                def interrupt(name):
                    if name == "after_contributions":
                        raise RuntimeError("publication interrupted after contributions")
                repository.transactions.callback = interrupt
                with self.assertRaisesRegex(RuntimeError, "after contributions"):
                    NetworkAnalyzer(repository).analyze_network(
                        network, [("C", "A"), ("B", "A")])
                self.assertEqual(full_snapshot(repository), before)
                self.assertEqual(ResultReader(repository).read_network(
                    existing)["estimates"], [F(1)])
            with Repository.open(path) as repository:
                self.assertEqual(full_snapshot(repository), before)
                result = NetworkAnalyzer(repository).analyze_network(
                    network, [("C", "A"), ("B", "A")])
                report = ResultReader(repository).read_network(result)
                self.assertEqual(report["estimates"], [F(2), F(1)])
                self.assertEqual(report["covariance"],
                                 [[F(2), F(1)], [F(1), F(2)]])
                self.assertEqual(repository.connection.execute(
                    "SELECT count(*) FROM network_results").fetchone()[0], 2)

    def test_empty_request_failure_rolls_back(self):
        revision = self.studies.save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1}])
        network = self.cohorts.freeze_network([revision])
        before = full_snapshot(self.repo)
        self.repo.transactions.callback = lambda name: (_ for _ in ()).throw(
            RuntimeError("boom")) if name == "after_contributions" else None
        with self.assertRaises(RuntimeError):
            self.network_analyzer.analyze_network(network, [])
        self.assertEqual(full_snapshot(self.repo), before)
        self.repo.transactions.callback = None
        result = self.network_analyzer.analyze_network(network, [])
        self.assertEqual(self.reader.read_network(result)["requests"], [])


class TestNetworkHistory(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="evidence-network-history-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "archive.sqlite"
        self.repo = Repository.open(self.path)

    def tearDown(self):
        self.repo.close()

    def reopen(self):
        self.repo.close()
        self.repo = Repository.open(self.path)

    def seed(self):
        revision = StudyService(self.repo).save_multiarm("s", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        network = CohortService(self.repo).freeze_network([revision])
        return revision, network

    def test_correction_withdrawal_and_reopen(self):
        revision, network = self.seed()
        result = NetworkAnalyzer(self.repo).analyze_network(
            network, [("B", "A"), ("C", "A")])
        exported = ResultExporter(self.repo).export_network(result)
        corrected = StudyService(self.repo).save_multiarm("s", "v2", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 9, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        fresh = CohortService(self.repo).freeze_network([corrected])
        fresh_result = NetworkAnalyzer(self.repo).analyze_network(fresh, [("B", "A")])
        self.assertEqual(ResultReader(self.repo).read_network(
            fresh_result)["estimates"], [F(9)])
        StudyService(self.repo).withdraw_study("s", "w")
        again = NetworkAnalyzer(self.repo).analyze_network(
            network, [("B", "A"), ("C", "A")])
        self.assertEqual(ResultReader(self.repo).read_network(again)["estimates"],
                         [F(1), F(2)])
        self.reopen()
        self.assertEqual(ResultExporter(self.repo).export_network(result), exported)
        old = ResultReader(self.repo).read_network(result)
        self.assertEqual(old["members"][0]["revision_id"], revision)
        self.assertEqual(old["estimates"], [F(1), F(2)])
        before = full_snapshot(self.repo)
        with self.assertRaises(ValueError):
            CohortService(self.repo).freeze_network([revision])
        self.assertEqual(full_snapshot(self.repo), before)

    def test_correction_before_first_analysis(self):
        revision, network = self.seed()
        StudyService(self.repo).save_multiarm("s", "v2", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 99, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        self.reopen()
        result = NetworkAnalyzer(self.repo).analyze_network(network, [("B", "A")])
        report = ResultReader(self.repo).read_network(result)
        self.assertEqual(report["estimates"], [F(1)])
        self.assertEqual(report["members"][0]["revision_id"], revision)

    def test_report_mutation_isolation(self):
        _, network = self.seed()
        result = NetworkAnalyzer(self.repo).analyze_network(
            network, [("B", "A"), ("C", "A")])
        original = ResultReader(self.repo).read_network(result)
        changed = ResultReader(self.repo).read_network(result)
        changed["members"][0]["arms"][0]["mean"] = F(999)
        changed["covariance"][0][0] = F(-1)
        changed["estimates"].append(F(5))
        changed["treatments"].clear()
        self.assertEqual(ResultReader(self.repo).read_network(result), original)

    def test_v1_archive_upgrade_preserves_data(self):
        revision = StudyService(self.repo).put_study("s", "v1", arms())
        cohort = CohortService(self.repo).freeze_cohort([revision], ("A", "B"))
        result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        exported = ResultExporter(self.repo).export_result(result)
        self.reopen()
        connection = self.repo.connection
        for table in NETWORK_TABLES:
            connection.execute(f"DROP TABLE {table}")
        before = snapshot(self.repo)
        self.reopen()
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(ResultExporter(self.repo).export_result(result), exported)
        multi = StudyService(self.repo).save_multiarm("m", "v1", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        network = CohortService(self.repo).freeze_network([multi])
        network_result = NetworkAnalyzer(self.repo).analyze_network(
            network, [("C", "A")])
        self.assertEqual(ResultReader(self.repo).read_network(
            network_result)["estimates"], [F(2)])
        self.repo.initialize()
        self.reopen()
        self.assertEqual(ResultExporter(self.repo).export_result(result), exported)
        self.assertEqual(ResultReader(self.repo).read_network(
            network_result)["estimates"], [F(2)])

    def test_coexisting_result_spaces(self):
        _, network = self.seed()
        network_result = NetworkAnalyzer(self.repo).analyze_network(
            network, [("B", "A")])
        with self.assertRaises(KeyError):
            ResultReader(self.repo).read_result(network_result)
        v1_revision = StudyService(self.repo).put_study("v", "v1", arms())
        cohort = CohortService(self.repo).freeze_cohort([v1_revision], ("A", "B"))
        v1_result = DirectAnalyzer(self.repo).analyze_direct(cohort, "A", "B")
        self.assertEqual(ResultReader(self.repo).read_result(v1_result)["estimate"],
                         F(1))
        self.assertEqual(ResultReader(self.repo).read_network(
            network_result)["estimates"], [F(1)])
        self.assertEqual(json.loads(ResultExporter(self.repo).export_result(
            v1_result))["format_version"], 1)
        self.assertEqual(json.loads(ResultExporter(self.repo).export_network(
            network_result))["format_version"], 2)


class TestNetworkExport(NetworkCase):
    def prepared(self):
        abc = self.studies.save_multiarm("abc", "v1", [
            {"treatment": "A", "mean": "1/3", "variance": "1/2"},
            {"treatment": "B", "mean": "5/3", "variance": "3/2"},
            {"treatment": "C", "mean": "7/3", "variance": "2/5"}])
        bc = self.studies.save_multiarm("bc", "v1", [
            {"treatment": "B", "mean": 10, "variance": 2},
            {"treatment": "C", "mean": 13, "variance": 1}])
        de = self.studies.save_multiarm("de", "v1", [
            {"treatment": "D", "mean": 4, "variance": 1},
            {"treatment": "E", "mean": 7, "variance": 1}])
        network = self.cohorts.freeze_network([abc, bc, de])
        requests = [("C", "A"), ("B", "A"), ("E", "D"), ("A", "D"), ("B", "B")]
        result = self.network_analyzer.analyze_network(network, requests)
        return result, network, requests

    def test_format_and_determinism(self):
        result, _, _ = self.prepared()
        first = self.exporter.export_network(result)
        decoded = json.loads(first)
        self.assertEqual(decoded["format_version"], 2)
        self.assertEqual(first, self.exporter.export_network(result))
        self.studies.save_multiarm("abc", "v2", [
            {"treatment": "A", "mean": 0, "variance": 1},
            {"treatment": "B", "mean": 1, "variance": 1},
            {"treatment": "C", "mean": 2, "variance": 1}])
        self.studies.withdraw_study("abc", "w")
        self.assertEqual(first, self.exporter.export_network(result))
        saved = decoded["result"]
        self.assertEqual(saved["status"], ["estimable", "estimable", "estimable",
                                           "not_estimable", "estimable"])
        self.assertIsNone(saved["estimates"][3])
        self.assertEqual(saved["estimates"][4], ["0", "1"])
        self.assertIsNone(saved["covariance"][3][0])
        self.assertIsNone(saved["covariance"][0][3])
        self.assertEqual(saved["covariance"][4],
                         [["0", "1"]] * 3 + [None] + [["0", "1"]])

    def test_independent_oracle_from_export(self):
        result, _, requests = self.prepared()
        saved = json.loads(self.exporter.export_network(result))["result"]
        rational = lambda pair: F(int(pair[0]), int(pair[1]))
        studies = []
        for member in saved["members"]:
            studies.append({arm["treatment"]: (rational(arm["mean"]),
                                               rational(arm["variance"]))
                            for arm in member["arms"]})
        pairs = [tuple(pair) for pair in saved["requests"]]
        status, estimates, covariance = oracle_answer(studies, pairs)
        decode = lambda value: None if value is None else rational(value)
        self.assertEqual(saved["status"], status)
        self.assertEqual([decode(v) for v in saved["estimates"]], estimates)
        self.assertEqual([[decode(v) for v in row] for row in saved["covariance"]],
                         covariance)

    def test_broken_parent_network(self):
        result, network, _ = self.prepared()
        self.repo.connection.execute("PRAGMA foreign_keys=OFF")
        self.repo.connection.execute("DELETE FROM network_members WHERE network_id=?",
                                     (network,))
        self.repo.connection.execute("DELETE FROM networks WHERE network_id=?",
                                     (network,))
        for operation in (self.reader.read_network, self.exporter.export_network):
            with self.assertRaises(IntegrityError):
                operation(result)

    def test_broken_member_revision(self):
        result, network, _ = self.prepared()
        revision = self.repo.load_network(network)["members"][0]["revision_id"]
        self.repo.connection.execute("PRAGMA foreign_keys=OFF")
        self.repo.connection.execute("DELETE FROM arms WHERE revision_id=?", (revision,))
        self.repo.connection.execute("DELETE FROM revisions WHERE revision_id=?",
                                     (revision,))
        for operation in (self.reader.read_network, self.exporter.export_network):
            with self.assertRaises(IntegrityError):
                operation(result)

    def test_missing_member_row_and_corrupted_payloads(self):
        result, network, _ = self.prepared()
        self.repo.connection.execute(
            "DELETE FROM network_result_members WHERE result_id=? AND position=2",
            (result,))
        with self.assertRaises(IntegrityError):
            self.reader.read_network(result)
        result, _, _ = self.prepared()
        self.repo.connection.execute(
            "UPDATE network_results SET payload='{}' WHERE result_id=?", (result,))
        with self.assertRaises(IntegrityError):
            self.reader.read_network(result)
        result, _, _ = self.prepared()
        row = self.repo.connection.execute(
            "SELECT payload FROM network_result_members WHERE result_id=? AND position=0",
            (result,)).fetchone()
        payload = json.loads(row[0])
        payload["arms"][0]["mean"] = ["1", "0"]
        self.repo.connection.execute(
            "UPDATE network_result_members SET payload=? WHERE result_id=? AND position=0",
            (json.dumps(payload), result))
        with self.assertRaises(IntegrityError):
            self.reader.read_network(result)
        with self.assertRaises(KeyError):
            self.reader.read_network(999)

    def test_no_recompute_on_read(self):
        result, _, _ = self.prepared()
        expected = self.reader.read_network(result)
        exported = self.exporter.export_network(result)
        forbidden = {"analyze_network", "build_network_evidence", "solve_network",
                     "solve_component", "answer_requests", "normal_equations",
                     "invert_exact", "treatment_components", "build_network_artifact",
                     "verify_network_solution", "verify_network_answers"}
        def guard(frame, event, arg):
            if (event == "call"
                    and frame.f_globals.get("__name__", "").startswith("evidence.")
                    and frame.f_code.co_name in forbidden):
                raise AssertionError("reading invoked computation: "
                                     + frame.f_code.co_name)
        previous = sys.getprofile()
        sys.setprofile(guard)
        try:
            self.assertEqual(self.reader.read_network(result), expected)
            self.assertEqual(self.exporter.export_network(result), exported)
        finally:
            sys.setprofile(previous)


class TestNetworkExamples(unittest.TestCase):
    def test_hand_examples_verify(self):
        import network_examples
        network_examples.verify()

    def test_hand_examples_demo(self):
        import network_examples
        network_examples.demo()
