"""Public hand cases and calls; no network estimator implementation."""
import argparse
import json
import tempfile
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from evidence.archive.repository import Repository
from evidence.studies.revisions import StudyService
from evidence.cohorts.freeze import CohortService
from evidence.results.reader import ResultReader
from evidence.results.export import ResultExporter


def arm(treatment, mean, variance=1):
    return {"treatment": treatment, "mean": mean, "variance": variance}


def cases():
    return [
        {
            "name": "shared_control",
            "studies": [("three", [arm("A", 0), arm("B", 1), arm("C", 2)])],
            "requests": [("B", "A"), ("C", "A"), ("A", "B"), ("B", "A"), ("A", "A")],
            "status": ["estimable"] * 5,
            "estimates": list(map(F, [1, 2, -1, 1, 0])),
            "covariance": [list(map(F, row)) for row in [
                [2, 1, -2, 2, 0], [1, 2, -1, 1, 0], [-2, -1, 2, -2, 0],
                [2, 1, -2, 2, 0], [0, 0, 0, 0, 0]]],
        },
        {
            "name": "indirect",
            "studies": [
                ("ab", [arm("A", 0), arm("B", 1)]),
                ("bc", [arm("B", 10), arm("C", 12)]),
            ],
            "requests": [("C", "A"), ("A", "C")],
            "status": ["estimable"] * 2,
            "estimates": [F(3), F(-3)],
            "covariance": [[F(4), F(-4)], [F(-4), F(4)]],
        },
        {
            "name": "disconnected",
            "studies": [
                ("ab", [arm("A", 0), arm("B", 1)]),
                ("cd", [arm("C", 4), arm("D", 7)]),
            ],
            "requests": [("B", "A"), ("D", "C"), ("A", "C"), ("A", "A")],
            "status": ["estimable", "estimable", "not_estimable", "estimable"],
            "estimates": [F(1), F(3), None, F(0)],
            "covariance": [
                [F(2), F(0), None, F(0)], [F(0), F(2), None, F(0)],
                [None, None, None, None], [F(0), F(0), None, F(0)]],
        },
    ]


def check(report, case):
    assert report["requests"] == [list(pair) for pair in case["requests"]]
    for key in ("status", "estimates", "covariance"):
        assert report[key] == case[key], (case["name"], key, report[key], case[key])
    values = report["estimates"] + [v for row in report["covariance"] for v in row]
    assert all(v is None or isinstance(v, F) for v in values)
    assert [m["position"] for m in report["members"]] == list(range(len(case["studies"])))
    for member in report["members"]:
        assert all(isinstance(a[k], F) for a in member["arms"] for k in ("mean", "variance"))


def exercise(repository, case, reverse=False):
    # Import only when exercising V2; V1 normal regression remains runnable.
    from evidence.synthesis.requests import NetworkAnalyzer
    entries = deepcopy(case["studies"])
    if reverse:
        entries.reverse()
        for _, arms in entries:
            arms.reverse()
    service = StudyService(repository)
    revisions = [service.save_multiarm(name, "initial", arms) for name, arms in entries]
    network = CohortService(repository).freeze_network(revisions)
    result = NetworkAnalyzer(repository).analyze_network(network, deepcopy(case["requests"]))
    report = ResultReader(repository).read_network(result)
    check(report, case)
    assert [(m["study_id"], m["revision_id"]) for m in report["members"]] == [
        (name, revision) for (name, _), revision in zip(entries, revisions)]
    exported = ResultExporter(repository).export_network(result)
    assert json.loads(exported)["format_version"] == 2
    changed = ResultReader(repository).read_network(result)
    changed["members"][0]["arms"][0]["mean"] = F(999)
    changed["covariance"].clear()
    assert ResultReader(repository).read_network(result) == report
    empty = NetworkAnalyzer(repository).analyze_network(network, [])
    empty_report = ResultReader(repository).read_network(empty)
    assert all(empty_report[k] == [] for k in ("requests", "status", "estimates", "covariance"))
    return network, result, report, exported


def verify():
    for case in cases():
        for reverse in (False, True):
            with Repository.open() as repository:
                exercise(repository, case, reverse)
    print("NETWORK_HAND_CASES_OK")


def demo():
    from evidence.synthesis.requests import NetworkAnalyzer
    case = cases()[0]
    with tempfile.TemporaryDirectory(prefix="network-demo-") as directory:
        path = Path(directory) / "evidence.sqlite"
        with Repository.open(path) as repository:
            network, result, report, exported = exercise(repository, case)
            corrected_arms = [arm("A", 0), arm("B", 9), arm("C", 2)]
            corrected = StudyService(repository).save_multiarm("three", "corrected", corrected_arms)
            fresh = CohortService(repository).freeze_network([corrected])
            fresh_result = NetworkAnalyzer(repository).analyze_network(fresh, [("B", "A")])
            assert ResultReader(repository).read_network(fresh_result)["estimates"] == [F(9)]
            # Existing queue must still use the original revision, even after withdrawal.
            StudyService(repository).withdraw_study("three", "withdrawn")
            again = NetworkAnalyzer(repository).analyze_network(network, case["requests"])
            check(ResultReader(repository).read_network(again), case)
        with Repository.open(path) as repository:
            assert ResultReader(repository).read_network(result) == report
            assert ResultExporter(repository).export_network(result) == exported
            print(json.dumps({
                "case": case["name"],
                "expected_estimates": ["1", "2", "-1", "1", "0"],
                "shared_control_covariance": str(report["covariance"][0][1]),
                "old_export_unchanged_after_reopen": True,
            }, ensure_ascii=False, sort_keys=True))
            print(exported)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hand-audit fixed multi-arm network examples")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify()
    else:
        demo()
