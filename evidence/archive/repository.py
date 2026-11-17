import json
import sqlite3
from evidence.archive.schema import initialize_archive
from evidence.archive.transactions import TransactionManager


class IntegrityError(sqlite3.IntegrityError):
    pass


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value):
    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        raise IntegrityError("invalid archived JSON") from exc


def _key(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("archive identity must be a positive integer")
    return value


class Repository:
    def __init__(self, path=":memory:", checkpoint=None):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.transactions = TransactionManager(self.connection, checkpoint)
        try:
            self.initialize()
        except BaseException:
            self.connection.close()
            raise

    @classmethod
    def open(cls, path=":memory:", checkpoint=None):
        return cls(path, checkpoint)

    def initialize(self):
        try:
            initialize_archive(self.connection)
        except sqlite3.DatabaseError as exc:
            raise IntegrityError(str(exc)) from exc

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _writing(self):
        if not self.connection.in_transaction:
            raise RuntimeError("repository writes require a business transaction")

    def load_study(self, study_id):
        row = self.connection.execute(
            "SELECT * FROM studies WHERE study_id=?", (study_id,)).fetchone()
        if row is None:
            raise KeyError(study_id)
        return dict(row)

    def find_version(self, study_id, version):
        row = self.connection.execute(
            "SELECT revision_id FROM revisions WHERE study_id=? AND source_version=?",
            (study_id, version)).fetchone()
        return None if row is None else row[0]

    def load_revision(self, revision_id):
        row = self.connection.execute(
            "SELECT * FROM revisions WHERE revision_id=?", (_key(revision_id),)).fetchone()
        if row is None:
            raise KeyError(revision_id)
        result = dict(row)
        result["arms"] = [
            {"treatment": arm["treatment"], "mean": _load(arm["mean"]),
             "variance": _load(arm["variance"])}
            for arm in self.connection.execute(
                "SELECT * FROM arms WHERE revision_id=? ORDER BY treatment", (revision_id,))]
        return result

    def append_revision(self, study_id, source_version, withdrawn, arms):
        self._writing()
        self.connection.execute(
            "INSERT OR IGNORE INTO studies(study_id,current_revision) VALUES (?,NULL)",
            (study_id,))
        cursor = self.connection.execute(
            "INSERT INTO revisions(study_id,source_version,withdrawn) VALUES (?,?,?)",
            (study_id, source_version, int(withdrawn)))
        revision_id = cursor.lastrowid
        for arm in arms:
            self.connection.execute(
                "INSERT INTO arms VALUES (?,?,?,?)",
                (revision_id, arm["treatment"], _dump(arm["mean"]), _dump(arm["variance"])))
        self.connection.execute("UPDATE studies SET current_revision=? WHERE study_id=?",
                                (revision_id, study_id))
        return revision_id

    def store_cohort(self, pair, revision_ids):
        self._writing()
        cursor = self.connection.execute(
            "INSERT INTO cohorts(treatment_a,treatment_b,member_count) VALUES (?,?,?)",
            (*pair, len(revision_ids)))
        cohort_id = cursor.lastrowid
        self.connection.executemany("INSERT INTO cohort_members VALUES (?,?,?)",
                                   [(cohort_id, i, rid) for i, rid in enumerate(revision_ids)])
        return cohort_id

    def load_cohort(self, cohort_id):
        row = self.connection.execute(
            "SELECT * FROM cohorts WHERE cohort_id=?", (_key(cohort_id),)).fetchone()
        if row is None:
            raise KeyError(cohort_id)
        result = dict(row)
        result["members"] = [dict(member) for member in self.connection.execute(
            "SELECT * FROM cohort_members WHERE cohort_id=? ORDER BY position", (cohort_id,))]
        return result

    def store_result(self, cohort_id, header, evidence, weights, contributions):
        self._writing()
        cursor = self.connection.execute("INSERT INTO results(cohort_id,payload) VALUES (?,?)",
                                         (cohort_id, _dump(header)))
        result_id = cursor.lastrowid
        for row in evidence:
            self.connection.execute("INSERT INTO result_evidence VALUES (?,?,?,?)",
                                    (result_id, row["position"], row["revision_id"], _dump(row)))
        for table, rows in (("result_weights", weights),
                            ("result_contributions", contributions)):
            for row in rows:
                self.connection.execute(f"INSERT INTO {table} VALUES (?,?,?)",
                                        (result_id, row["position"], _dump(row)))
        return result_id

    def load_result(self, result_id):
        row = self.connection.execute(
            "SELECT * FROM results WHERE result_id=?", (_key(result_id),)).fetchone()
        if row is None:
            raise KeyError(result_id)
        result = {"result_id": result_id, "cohort_id": row["cohort_id"],
                  "header": _load(row["payload"])}
        for table, name in (("result_evidence", "evidence"),
                            ("result_weights", "weights"),
                            ("result_contributions", "contributions")):
            items = []
            for stored in self.connection.execute(
                    f"SELECT * FROM {table} WHERE result_id=? ORDER BY position", (result_id,)):
                payload = _load(stored["payload"])
                if not isinstance(payload, dict) or payload.get("position") != stored["position"]:
                    raise IntegrityError("stored position mismatch")
                if name == "evidence" and payload.get("revision_id") != stored["revision_id"]:
                    raise IntegrityError("stored revision mismatch")
                items.append(payload)
            result[name] = items
        return result
