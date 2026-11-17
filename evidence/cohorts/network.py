from dataclasses import dataclass
from evidence.studies.revisions import read_revision
from evidence.cohorts.membership import validate_network_membership
from evidence.archive.repository import IntegrityError


@dataclass(frozen=True)
class NetworkMember:
    position: int
    revision: object


@dataclass(frozen=True)
class FrozenNetwork:
    network_id: int
    members: tuple


def read_network_cohort(repository, network_id):
    row = repository.load_network(network_id)
    try:
        members = row["members"]
        if len(members) != row["member_count"]:
            raise ValueError("missing network member")
        revisions = []
        for index, member in enumerate(members):
            if member["position"] != index or member["network_id"] != network_id:
                raise ValueError("invalid network member position")
            revisions.append(read_revision(repository, member["revision_id"]))
        validate_network_membership(revisions)
        return FrozenNetwork(network_id, tuple(
            NetworkMember(i, revision) for i, revision in enumerate(revisions)))
    except (ValueError, KeyError, TypeError) as exc:
        raise IntegrityError("broken frozen network") from exc
