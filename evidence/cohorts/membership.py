from evidence.studies.identity import canonical_treatment_pair


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
