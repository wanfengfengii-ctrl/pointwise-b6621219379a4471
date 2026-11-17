from dataclasses import dataclass
from fractions import Fraction
from copy import deepcopy
from evidence.contrasts.batch import DirectEvidence
from evidence.contrasts.orientation import resolve_direction
from evidence.synthesis.weights import StudyWeight
from evidence.synthesis.pooling import PooledEffect
from evidence.synthesis.contributions import Contribution, verify_contributions
from evidence.archive.encoding import encode_fraction, decode_fraction
from evidence.archive.repository import IntegrityError


@dataclass(frozen=True)
class DirectResult:
    cohort_id: int
    left: str
    right: str
    effect: PooledEffect
    evidence: tuple
    weights: tuple
    contributions: tuple


def validate_artifact(result, cohort, mathematical=True):
    if result.cohort_id != cohort.cohort_id:
        raise ValueError("artifact parent mismatch")
    resolve_direction(cohort.pair, result.left, result.right)
    expected_keys = [(m.position, m.revision.study_id, m.revision.revision_id)
                     for m in cohort.members]
    if not expected_keys:
        raise ValueError("empty artifact")
    for rows in (result.evidence, result.weights, result.contributions):
        if [row.key for row in rows] != expected_keys:
            raise ValueError("artifact member identity mismatch")
    exact = [result.effect.estimate, result.effect.variance, result.effect.weight_sum]
    exact += [value for row in result.evidence for value in (row.difference, row.variance)]
    exact += [value for row in result.weights for value in (row.raw, row.normalized)]
    exact += [row.value for row in result.contributions]
    if any(not isinstance(value, Fraction) for value in exact):
        raise ValueError("artifact has nonexact values")
    if (result.effect.variance <= 0 or result.effect.weight_sum <= 0
            or any(row.variance <= 0 for row in result.evidence)
            or any(row.raw <= 0 or row.normalized <= 0 for row in result.weights)):
        raise ValueError("artifact has nonpositive uncertainty or weights")
    if mathematical:
        for member, row in zip(cohort.members, result.evidence):
            arms = {arm.treatment: arm for arm in member.revision.arms}
            left, right = arms[result.left], arms[result.right]
            if (row.difference != left.mean - right.mean
                    or row.variance != left.variance + right.variance):
                raise ValueError("artifact evidence differs from source")
        total = sum((weight.raw for weight in result.weights), Fraction())
        for delta, weight in zip(result.evidence, result.weights):
            if weight.raw != 1 / delta.variance or weight.normalized != weight.raw / total:
                raise ValueError("artifact weight mismatch")
        estimate = sum((d.difference * w.raw for d, w in
                        zip(result.evidence, result.weights)), Fraction()) / total
        if result.effect != PooledEffect(estimate, 1 / total, total):
            raise ValueError("artifact summary mismatch")
        verify_contributions(result.evidence, result.weights, result.effect, result.contributions)


def build_artifact(cohort, request, evidence, weights, pooled, contributions):
    result = DirectResult(request.cohort_id, request.left, request.right, pooled,
                          tuple(evidence), tuple(weights), tuple(contributions))
    validate_artifact(result, cohort)
    return result


def archived_parts(result):
    header = {"cohort_id": result.cohort_id, "left": result.left, "right": result.right,
              "estimate": encode_fraction(result.effect.estimate),
              "variance": encode_fraction(result.effect.variance),
              "weight_sum": encode_fraction(result.effect.weight_sum)}
    def identity(row):
        return {"position": row.position, "study_id": row.study_id, "revision_id": row.revision_id}
    evidence = [dict(identity(row), difference=encode_fraction(row.difference),
                     variance=encode_fraction(row.variance)) for row in result.evidence]
    weights = [dict(identity(row), raw=encode_fraction(row.raw),
                    normalized=encode_fraction(row.normalized)) for row in result.weights]
    contributions = [dict(identity(row), value=encode_fraction(row.value))
                     for row in result.contributions]
    return header, evidence, weights, contributions


def restore_artifact(stored, cohort):
    try:
        header = stored["header"]
        if set(header) != {"cohort_id", "left", "right", "estimate", "variance", "weight_sum"}:
            raise ValueError("invalid artifact header")
        def rows(name, extra, record_type):
            restored = []
            for row in stored[name]:
                if set(row) != {"position", "study_id", "revision_id", *extra}:
                    raise ValueError("invalid archived row fields")
                if (type(row["position"]) is not int or type(row["revision_id"]) is not int
                        or not isinstance(row["study_id"], str)):
                    raise ValueError("invalid archived row identity")
                restored.append(record_type(row["position"], row["study_id"], row["revision_id"],
                                            *(decode_fraction(row[key]) for key in extra)))
            return tuple(restored)
        result = DirectResult(header["cohort_id"], header["left"], header["right"],
                              PooledEffect(*(decode_fraction(header[key]) for key in
                                             ("estimate", "variance", "weight_sum"))),
                              rows("evidence", ("difference", "variance"), DirectEvidence),
                              rows("weights", ("raw", "normalized"), StudyWeight),
                              rows("contributions", ("value",), Contribution))
        if type(header["cohort_id"]) is not int or header["cohort_id"] != stored["cohort_id"]:
            raise ValueError("stored parent mismatch")
        validate_artifact(result, cohort, mathematical=False)
        return result
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise IntegrityError("invalid stored result") from exc


def result_copy(result, cohort, result_id):
    members = []
    for member, delta, weight, contribution in zip(cohort.members, result.evidence,
                                                  result.weights, result.contributions):
        revision = member.revision
        members.append({"position": member.position, "study_id": revision.study_id,
                        "revision_id": revision.revision_id, "source_version": revision.source_version,
                        "arms": [{"treatment": arm.treatment, "mean": arm.mean,
                                  "variance": arm.variance} for arm in revision.arms],
                        "difference": delta.difference, "variance": delta.variance,
                        "raw_weight": weight.raw, "normalized_weight": weight.normalized,
                        "contribution": contribution.value})
    return deepcopy({"result_id": result_id, "cohort_id": cohort.cohort_id,
                     "pair": list(cohort.pair), "left": result.left, "right": result.right,
                     "estimate": result.effect.estimate, "variance": result.effect.variance,
                     "weight_sum": result.effect.weight_sum, "members": members})
