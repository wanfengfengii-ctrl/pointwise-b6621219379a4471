from dataclasses import dataclass
from fractions import Fraction
from copy import deepcopy
from evidence.studies.identity import StudyIdentity, validate_identity
from evidence.studies.arms import ArmStatistics
from evidence.synthesis.network import (NetworkStudyEvidence, NetworkRequestAnswer,
                                        verify_network_solution, verify_network_answers,
                                        MAX_NETWORK_REQUESTS)
from evidence.cohorts.membership import MAX_NETWORK_TREATMENTS
from evidence.archive.encoding import encode_fraction, decode_fraction
from evidence.archive.repository import IntegrityError

STATUSES = ("estimable", "not_estimable")


@dataclass(frozen=True)
class NetworkResult:
    network_id: int
    treatments: tuple
    answers: tuple
    covariance: tuple
    members: tuple
    solution: object


def validate_network_artifact(result, network, mathematical=True):
    if result.network_id != network.network_id:
        raise ValueError("artifact parent mismatch")
    expected = [(member.position, member.revision.study_id, member.revision.revision_id)
                for member in network.members]
    if not expected:
        raise ValueError("empty artifact")
    if [(member.position, member.study_id, member.revision_id)
            for member in result.members] != expected:
        raise ValueError("artifact member identity mismatch")
    for member, frozen in zip(result.members, network.members):
        revision = frozen.revision
        if (member.source_version != revision.source_version
                or tuple(member.arms) != tuple(revision.arms)):
            raise ValueError("artifact member evidence mismatch")
    treatments = tuple(sorted({arm.treatment for member in result.members
                               for arm in member.arms}))
    if (tuple(result.treatments) != treatments
            or not 1 <= len(treatments) <= MAX_NETWORK_TREATMENTS):
        raise ValueError("artifact treatments mismatch")
    if not 0 <= len(result.answers) <= MAX_NETWORK_REQUESTS:
        raise ValueError("invalid request count")
    known = set(treatments)
    for answer in result.answers:
        validate_identity(answer.left, "treatment")
        validate_identity(answer.right, "treatment")
        if answer.left not in known or answer.right not in known:
            raise ValueError("request outside frozen treatments")
        if answer.status not in STATUSES:
            raise ValueError("invalid request status")
        if answer.status == "estimable":
            if not isinstance(answer.estimate, Fraction):
                raise ValueError("estimable request lacks exact estimate")
        elif answer.estimate is not None:
            raise ValueError("not estimable request carries an estimate")
    size = len(result.answers)
    if (len(result.covariance) != size
            or any(len(row) != size for row in result.covariance)):
        raise ValueError("covariance shape mismatch")
    for i, first in enumerate(result.answers):
        for j, second in enumerate(result.answers):
            value = result.covariance[i][j]
            if first.status == "not_estimable" or second.status == "not_estimable":
                if value is not None:
                    raise ValueError("not estimable covariance leaked")
            elif not isinstance(value, Fraction):
                raise ValueError("missing exact covariance")
        if result.covariance[i] != tuple(result.covariance[k][i]
                                         for k in range(size)):
            raise ValueError("asymmetric covariance")
        if (first.status == "estimable" and result.covariance[i][i] is not None
                and result.covariance[i][i] < 0):
            raise ValueError("negative variance")
    if mathematical:
        if result.solution is None:
            raise ValueError("solution required for reconciliation")
        verify_network_solution(result.members, result.solution)
        verify_network_answers(result.solution, result.answers, result.covariance)


def build_network_artifact(network, solution, answers, covariance):
    result = NetworkResult(network.network_id, solution.treatments, tuple(answers),
                           tuple(covariance), solution.evidence, solution)
    validate_network_artifact(result, network)
    return result


def archived_network_parts(result):
    header = {"network_id": result.network_id,
              "treatments": list(result.treatments),
              "requests": [[answer.left, answer.right] for answer in result.answers],
              "status": [answer.status for answer in result.answers],
              "estimates": [encode_fraction(answer.estimate)
                            if answer.estimate is not None else None
                            for answer in result.answers],
              "covariance": [[encode_fraction(value) if value is not None else None
                              for value in row] for row in result.covariance]}
    members = [{"position": member.position, "study_id": member.study_id,
                "revision_id": member.revision_id, "source_version": member.source_version,
                "arms": [{"treatment": arm.treatment, "mean": encode_fraction(arm.mean),
                          "variance": encode_fraction(arm.variance)}
                         for arm in member.arms]}
               for member in result.members]
    return header, members


def _restore_member(payload):
    if set(payload) != {"position", "study_id", "revision_id", "source_version", "arms"}:
        raise ValueError("invalid archived member fields")
    if (type(payload["position"]) is not int
            or type(payload["revision_id"]) is not int):
        raise ValueError("invalid archived member identity")
    StudyIdentity(payload["study_id"], payload["source_version"])
    records = payload["arms"]
    if not isinstance(records, list) or not 2 <= len(records) <= 6:
        raise ValueError("invalid archived member arms")
    arms = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"treatment", "mean", "variance"}:
            raise ValueError("invalid archived arm record")
        arms.append(ArmStatistics(record["treatment"], decode_fraction(record["mean"]),
                                  decode_fraction(record["variance"])))
    treatments = [arm.treatment for arm in arms]
    if len(set(treatments)) != len(treatments) or treatments != sorted(treatments):
        raise ValueError("archived arms not canonical")
    return NetworkStudyEvidence(payload["position"], payload["study_id"],
                                payload["revision_id"], payload["source_version"],
                                tuple(arms))


def restore_network_artifact(stored, network):
    try:
        header = stored["header"]
        if set(header) != {"network_id", "treatments", "requests", "status",
                           "estimates", "covariance"}:
            raise ValueError("invalid network header")
        if (type(header["network_id"]) is not int
                or header["network_id"] != stored["network_id"]):
            raise ValueError("stored parent mismatch")
        treatments = header["treatments"]
        if (not isinstance(treatments, list)
                or not 1 <= len(treatments) <= MAX_NETWORK_TREATMENTS):
            raise ValueError("invalid archived treatments")
        for treatment in treatments:
            validate_identity(treatment, "treatment")
        if treatments != sorted(treatments) or len(set(treatments)) != len(treatments):
            raise ValueError("archived treatments not canonical")
        requests = header["requests"]
        if not isinstance(requests, list) or len(requests) > MAX_NETWORK_REQUESTS:
            raise ValueError("invalid archived requests")
        known = set(treatments)
        for pair in requests:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("invalid archived request pair")
            validate_identity(pair[0], "treatment")
            validate_identity(pair[1], "treatment")
            if pair[0] not in known or pair[1] not in known:
                raise ValueError("archived request outside treatments")
        status, estimates, covariance = (header["status"], header["estimates"],
                                         header["covariance"])
        size = len(requests)
        if (not isinstance(status, list) or len(status) != size
                or any(value not in STATUSES for value in status)):
            raise ValueError("invalid archived status")
        if not isinstance(estimates, list) or len(estimates) != size:
            raise ValueError("invalid archived estimates")
        if (not isinstance(covariance, list) or len(covariance) != size
                or any(not isinstance(row, list) or len(row) != size
                       for row in covariance)):
            raise ValueError("invalid archived covariance")
        answers = []
        for pair, state, estimate in zip(requests, status, estimates):
            if state == "estimable":
                answers.append(NetworkRequestAnswer(pair[0], pair[1], state,
                                                    decode_fraction(estimate)))
            else:
                if estimate is not None:
                    raise ValueError("not estimable request carries an estimate")
                answers.append(NetworkRequestAnswer(pair[0], pair[1], state, None))
        matrix = []
        for i, row in enumerate(covariance):
            decoded = []
            for j, value in enumerate(row):
                if status[i] == "not_estimable" or status[j] == "not_estimable":
                    if value is not None:
                        raise ValueError("not estimable covariance leaked")
                    decoded.append(None)
                else:
                    decoded.append(decode_fraction(value))
            matrix.append(tuple(decoded))
        members = tuple(_restore_member(payload) for payload in stored["members"])
        if [member.position for member in members] != list(range(len(members))):
            raise ValueError("archived member positions not consecutive")
        result = NetworkResult(header["network_id"], tuple(treatments), tuple(answers),
                               tuple(matrix), members, None)
        validate_network_artifact(result, network, mathematical=False)
        return result
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise IntegrityError("invalid stored network result") from exc


def network_result_copy(result, result_id):
    return deepcopy({"result_id": result_id, "network_id": result.network_id,
                     "treatments": list(result.treatments),
                     "requests": [[answer.left, answer.right] for answer in result.answers],
                     "status": [answer.status for answer in result.answers],
                     "estimates": [answer.estimate for answer in result.answers],
                     "covariance": [list(row) for row in result.covariance],
                     "members": [{"position": member.position, "study_id": member.study_id,
                                  "revision_id": member.revision_id,
                                  "source_version": member.source_version,
                                  "arms": [{"treatment": arm.treatment, "mean": arm.mean,
                                            "variance": arm.variance}
                                           for arm in member.arms]}
                                 for member in result.members]})
