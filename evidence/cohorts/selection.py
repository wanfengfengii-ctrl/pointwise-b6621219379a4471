from evidence.studies.revisions import read_revision, read_current_revision


def select_revisions(repository, revision_ids):
    if isinstance(revision_ids, (str, bytes)):
        raise ValueError("revision identities must be a sequence")
    try:
        ids = tuple(revision_ids)
    except TypeError as exc:
        raise ValueError("invalid revision sequence") from exc
    selected = []
    for revision_id in ids:
        revision = read_revision(repository, revision_id)
        if revision.withdrawn:
            raise ValueError("withdrawal revision is not evidence")
        if read_current_revision(repository, revision.study_id).withdrawn:
            raise ValueError("currently withdrawn study cannot enter a new cohort")
        selected.append(revision)
    return tuple(selected)
