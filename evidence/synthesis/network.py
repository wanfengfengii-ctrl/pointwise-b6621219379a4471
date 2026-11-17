"""Joint fixed-effect network synthesis for multi-arm evidence.

Model: y_st = alpha_s + theta_t + e_st with independent known arm variances.
Study intercepts alpha_s are free; treatment effects theta_t are compared
through estimable contrasts inside each connected component.  Fitting uses
unpenalized weighted least squares with the known variances; no residual
scale or heterogeneity is estimated and covariances are not rescaled.
"""
from dataclasses import dataclass
from fractions import Fraction
from evidence.studies.identity import validate_identity
from evidence.archive.repository import IntegrityError

MAX_NETWORK_REQUESTS = 8


@dataclass(frozen=True)
class NetworkStudyEvidence:
    """Frozen joint evidence of one study: all arms stay together."""
    position: int
    study_id: str
    revision_id: int
    source_version: str
    arms: tuple

    @property
    def key(self):
        return self.position, self.study_id, self.revision_id


@dataclass(frozen=True)
class ComponentSolution:
    treatments: tuple
    theta: tuple
    covariance: tuple


@dataclass(frozen=True)
class NetworkSolution:
    evidence: tuple
    treatments: tuple
    components: tuple
    groups: tuple


@dataclass(frozen=True)
class NetworkRequestAnswer:
    left: str
    right: str
    status: str
    estimate: object


def build_network_evidence(network):
    """Hand off frozen per-study joint evidence with identity to the analysis."""
    evidence = []
    seen = set()
    for index, member in enumerate(network.members):
        revision = member.revision
        if member.position != index or revision.study_id in seen:
            raise IntegrityError("invalid frozen member identity")
        seen.add(revision.study_id)
        if revision.withdrawn or not 2 <= len(revision.arms) <= 6:
            raise IntegrityError("invalid frozen network evidence")
        evidence.append(NetworkStudyEvidence(member.position, revision.study_id,
                                             revision.revision_id, revision.source_version,
                                             revision.arms))
    if not evidence:
        raise IntegrityError("empty frozen network")
    return tuple(evidence)


def validate_network_requests(requests):
    if not isinstance(requests, (list, tuple)):
        raise ValueError("requests must be a list or tuple")
    if len(requests) > MAX_NETWORK_REQUESTS:
        raise ValueError("at most eight requests per analysis")
    validated = []
    for item in requests:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("each request must be a pair of treatments")
        left, right = item
        validate_identity(left, "treatment")
        validate_identity(right, "treatment")
        validated.append((left, right))
    return tuple(validated)


def treatment_components(evidence):
    """Connected components of treatments linked by co-occurring in a study."""
    treatments = sorted({arm.treatment for row in evidence for arm in row.arms})
    parent = {treatment: treatment for treatment in treatments}

    def find(treatment):
        root = treatment
        while parent[root] != root:
            root = parent[root]
        while parent[treatment] != root:
            parent[treatment], treatment = root, parent[treatment]
        return root

    for row in evidence:
        first = row.arms[0].treatment
        for arm in row.arms[1:]:
            left, right = find(first), find(arm.treatment)
            if left != right:
                parent[max(left, right)] = min(left, right)
    groups = {}
    for treatment in treatments:
        groups.setdefault(find(treatment), []).append(treatment)
    return tuple(tuple(members) for _, members in sorted(groups.items()))


def normal_equations(rows, treatments):
    """Reduced information matrix and right-hand side for one component.

    Study intercepts are profiled out exactly; the reference treatment
    treatments[0] is constrained to zero.  The reduced system of a
    connected component with positive variances is positive definite.
    """
    reduced = {treatment: i for i, treatment in enumerate(treatments[1:])}
    size = len(reduced)
    matrix = [[Fraction(0)] * size for _ in range(size)]
    rhs = [Fraction(0)] * size
    for row in rows:
        arms = row.arms
        weights = [Fraction(1) / arm.variance for arm in arms]
        total = sum(weights, Fraction(0))
        shifted = sum(weight * arm.mean for weight, arm in zip(weights, arms)) / total
        for arm, weight in zip(arms, weights):
            i = reduced.get(arm.treatment)
            if i is None:
                continue
            rhs[i] += weight * (arm.mean - shifted)
            for other, other_weight in zip(arms, weights):
                j = reduced.get(other.treatment)
                if j is None:
                    continue
                matrix[i][j] += (weight if arm.treatment == other.treatment
                                 else Fraction(0)) - weight * other_weight / total
    return matrix, rhs


def invert_exact(matrix):
    """Exact Fraction Gauss-Jordan inversion of a nonsingular square matrix."""
    size = len(matrix)
    if size == 0:
        return []
    if any(len(row) != size for row in matrix):
        raise ValueError("matrix must be square")
    aug = [[Fraction(value) for value in row]
           + [Fraction(1) if i == j else Fraction(0) for j in range(size)]
           for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = next((r for r in range(col, size) if aug[r][col]), None)
        if pivot is None:
            raise ValueError("singular information matrix")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pivot_value = aug[col][col]
        aug[col] = [value / pivot_value for value in aug[col]]
        for r in range(size):
            if r != col and aug[r][col]:
                factor = aug[r][col]
                aug[r] = [a - factor * b for a, b in zip(aug[r], aug[col])]
    return [row[size:] for row in aug]


def solve_component(rows, treatments):
    matrix, rhs = normal_equations(rows, treatments)
    inverse = invert_exact(matrix)
    size = len(treatments)
    theta = [Fraction(0)] * size
    covariance = [[Fraction(0)] * size for _ in range(size)]
    for p in range(1, size):
        theta[p] = sum(inverse[p - 1][k] * rhs[k] for k in range(size - 1))
        for q in range(1, size):
            covariance[p][q] = inverse[p - 1][q - 1]
    return ComponentSolution(treatments, tuple(theta),
                             tuple(tuple(row) for row in covariance))


def solve_network(evidence):
    if not evidence:
        raise ValueError("network evidence required")
    components = treatment_components(evidence)
    solutions = []
    groups = []
    for treatments in components:
        member = set(treatments)
        rows = tuple(row for row in evidence if row.arms[0].treatment in member)
        solutions.append(solve_component(rows, treatments))
        groups.append(rows)
    return NetworkSolution(evidence, tuple(sorted({
        arm.treatment for row in evidence for arm in row.arms})),
        tuple(solutions), tuple(groups))


def _placement(solution):
    placement = {}
    for index, component in enumerate(solution.components):
        for position, treatment in enumerate(component.treatments):
            placement[treatment] = (index, position)
    return placement


def answer_requests(solution, requests):
    placement = _placement(solution)
    answers = []
    for left, right in requests:
        if left not in placement:
            raise KeyError(left)
        if right not in placement:
            raise KeyError(right)
        if left == right:
            answers.append(NetworkRequestAnswer(left, right, "estimable", Fraction(0)))
        elif placement[left][0] == placement[right][0]:
            component = solution.components[placement[left][0]]
            estimate = (component.theta[placement[left][1]]
                        - component.theta[placement[right][1]])
            answers.append(NetworkRequestAnswer(left, right, "estimable", estimate))
        else:
            answers.append(NetworkRequestAnswer(left, right, "not_estimable", None))
    covariance = []
    for first in answers:
        row = []
        for second in answers:
            if first.status == "not_estimable" or second.status == "not_estimable":
                row.append(None)
            elif first.left == first.right or second.left == second.right:
                row.append(Fraction(0))
            elif placement[first.left][0] != placement[second.left][0]:
                row.append(Fraction(0))
            else:
                component = solution.components[placement[first.left][0]]
                cov = component.covariance
                row.append(cov[placement[first.left][1]][placement[second.left][1]]
                           - cov[placement[first.left][1]][placement[second.right][1]]
                           - cov[placement[first.right][1]][placement[second.left][1]]
                           + cov[placement[first.right][1]][placement[second.right][1]])
        covariance.append(tuple(row))
    return tuple(answers), tuple(covariance)


def verify_network_solution(evidence, solution):
    """Independent reconciliation: substitute the solution into the model.

    Rebuilds components and normal equations from the frozen evidence and
    checks A*theta = b and A*V = I exactly, without re-running the solver.
    """
    if solution.evidence != evidence:
        raise ValueError("solution evidence mismatch")
    components = treatment_components(evidence)
    if tuple(component.treatments for component in solution.components) != components:
        raise ValueError("solution components mismatch")
    if len(solution.groups) != len(components):
        raise ValueError("solution grouping mismatch")
    for rows, component in zip(solution.groups, solution.components):
        if tuple(sorted(row.key for row in rows)) != tuple(sorted(
                row.key for row in evidence
                if row.arms[0].treatment in set(component.treatments))):
            raise ValueError("solution group evidence mismatch")
        matrix, rhs = normal_equations(rows, component.treatments)
        size = len(component.treatments)
        if component.theta[0] != 0 or any(
                component.covariance[0][p] != 0 or component.covariance[p][0] != 0
                for p in range(size)):
            raise ValueError("reference constraint violated")
        theta = component.theta[1:]
        for i in range(size - 1):
            if sum(matrix[i][k] * theta[k] for k in range(size - 1)) != rhs[i]:
                raise ValueError("normal equations not satisfied")
            for j in range(size - 1):
                product = sum(matrix[i][k] * component.covariance[k + 1][j + 1]
                              for k in range(size - 1))
                if product != (Fraction(1) if i == j else Fraction(0)):
                    raise ValueError("covariance is not the information inverse")


def verify_network_answers(solution, answers, covariance):
    requests = tuple((answer.left, answer.right) for answer in answers)
    expected_answers, expected_covariance = answer_requests(solution, requests)
    if expected_answers != tuple(answers) or expected_covariance != tuple(covariance):
        raise ValueError("network answers do not reconcile with the solution")
