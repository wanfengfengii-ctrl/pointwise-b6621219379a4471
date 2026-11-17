from evidence.studies.identity import canonical_treatment_pair

MAX_NETWORK_MEMBERS = 80
MAX_NETWORK_TREATMENTS = 20


def validate_membership(revisions, treatment_pair):
    pair = canonical_treatment_pair(treatment_pair)
    if not revisions:
        raise ValueError("empty cohort")
    seen = set()
    for revision in revisions:
        if revision.study_id in seen:
            raise ValueError("a study can contribute only one revision")
        seen.add(revision.study_id)
        if revision.withdrawn or canonical_treatment_pair(
                arm.treatment for arm in revision.arms) != pair:
            raise ValueError("revision does not match cohort treatment pair")
    return pair


def validate_network_membership(revisions):
    if not revisions:
        raise ValueError("empty network")
    if len(revisions) > MAX_NETWORK_MEMBERS:
        raise ValueError("network exceeds eighty studies")
    seen = set()
    treatments = set()
    for revision in revisions:
        if revision.study_id in seen:
            raise ValueError("a study can contribute only one revision")
        seen.add(revision.study_id)
        if revision.withdrawn or not revision.arms:
            raise ValueError("revision is not network evidence")
        treatments.update(arm.treatment for arm in revision.arms)
    if len(treatments) > MAX_NETWORK_TREATMENTS:
        raise ValueError("network exceeds twenty treatments")
    return tuple(sorted(treatments))
