import json
from fractions import Fraction
from evidence.results.reader import ResultReader
from evidence.archive.encoding import encode_fraction

EXPORT_FORMAT_VERSION = 1
NETWORK_FORMAT_VERSION = 2


def _encode(value):
    if isinstance(value, Fraction):
        return encode_fraction(value)
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    return value


class ResultExporter:
    def __init__(self, repository):
        self.reader = ResultReader(repository)

    def export_result(self, result_id):
        result = self.reader.read_result(result_id)
        return json.dumps({"format_version": EXPORT_FORMAT_VERSION, "result": _encode(result)},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def export_network(self, result_id):
        result = self.reader.read_network(result_id)
        return json.dumps({"format_version": NETWORK_FORMAT_VERSION,
                           "result": _encode(result)},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main():
    import argparse
    import tempfile
    from pathlib import Path
    from evidence.archive.repository import Repository
    from evidence.studies.revisions import StudyService
    from evidence.cohorts.freeze import CohortService
    from evidence.synthesis.requests import DirectAnalyzer
    parser = argparse.ArgumentParser(description="Run a complete evidence workday")
    parser.add_argument("sample", type=Path)
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="evidence-demo-") as directory:
        path = Path(directory) / "day.sqlite"
        with Repository.open(path) as repository:
            studies = StudyService(repository)
            revisions = studies.put_studies(sample["studies"])
            cohort_id = CohortService(repository).freeze_cohort(revisions, sample["pair"])
            result_id = DirectAnalyzer(repository).analyze_direct(cohort_id, *sample["request"])
            result = ResultReader(repository).read_result(result_id)
            expected = Fraction(7, 5), Fraction(8, 5)
            assert (result["estimate"], result["variance"]) == expected
            exported = ResultExporter(repository).export_result(result_id)
            studies.put_studies(sample["corrections"])
            studies.withdraw_study(sample["studies"][0]["study_id"], "withdrawn")
        with Repository.open(path) as repository:
            reopened = ResultExporter(repository).export_result(result_id)
            assert reopened == exported
            print("POINTWISE_SCENARIO " + json.dumps({
                "case_id": "V3.unequal_variances",
                "input": sample["studies"],
                "expected": {"estimate": ["7", "5"], "variance": ["8", "5"]},
                "actual": _encode({"estimate": result["estimate"], "variance": result["variance"]}),
                "downstream_expected": {"export_unchanged_after_reopen": True},
                "downstream_actual": {"export_unchanged_after_reopen": reopened == exported},
                "code_paths": ["evidence/contrasts/batch.py", "evidence/synthesis/pooling.py",
                               "evidence/results/export.py"],
                "oracle": "hand: weights 1/2 and 1/8; normalized 4/5 and 1/5"
            }, sort_keys=True, ensure_ascii=False))
            print(reopened)


if __name__ == "__main__":
    main()
