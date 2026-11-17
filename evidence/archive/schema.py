import sqlite3

SCHEMA_VERSION = 1
DDL_STATEMENTS = (
    "CREATE TABLE metadata(version INTEGER NOT NULL)",
    "CREATE TABLE studies(study_id TEXT PRIMARY KEY, current_revision INTEGER REFERENCES revisions(revision_id) DEFERRABLE INITIALLY DEFERRED)",
    "CREATE TABLE revisions(revision_id INTEGER PRIMARY KEY AUTOINCREMENT, study_id TEXT NOT NULL REFERENCES studies(study_id), source_version TEXT NOT NULL, withdrawn INTEGER NOT NULL CHECK(withdrawn IN (0,1)), UNIQUE(study_id,source_version))",
    "CREATE TABLE arms(revision_id INTEGER NOT NULL REFERENCES revisions(revision_id), treatment TEXT NOT NULL, mean TEXT NOT NULL, variance TEXT NOT NULL, PRIMARY KEY(revision_id,treatment))",
    "CREATE TABLE cohorts(cohort_id INTEGER PRIMARY KEY AUTOINCREMENT, treatment_a TEXT NOT NULL, treatment_b TEXT NOT NULL, member_count INTEGER NOT NULL CHECK(member_count>0))",
    "CREATE TABLE cohort_members(cohort_id INTEGER NOT NULL REFERENCES cohorts(cohort_id), position INTEGER NOT NULL CHECK(position>=0), revision_id INTEGER NOT NULL REFERENCES revisions(revision_id), PRIMARY KEY(cohort_id,position), UNIQUE(cohort_id,revision_id))",
    "CREATE TABLE results(result_id INTEGER PRIMARY KEY AUTOINCREMENT, cohort_id INTEGER NOT NULL REFERENCES cohorts(cohort_id), payload TEXT NOT NULL)",
    "CREATE TABLE result_evidence(result_id INTEGER NOT NULL REFERENCES results(result_id), position INTEGER NOT NULL, revision_id INTEGER NOT NULL REFERENCES revisions(revision_id), payload TEXT NOT NULL, PRIMARY KEY(result_id,position))",
    "CREATE TABLE result_weights(result_id INTEGER NOT NULL REFERENCES results(result_id), position INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(result_id,position), FOREIGN KEY(result_id,position) REFERENCES result_evidence(result_id,position))",
    "CREATE TABLE result_contributions(result_id INTEGER NOT NULL REFERENCES results(result_id), position INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(result_id,position), FOREIGN KEY(result_id,position) REFERENCES result_evidence(result_id,position))",
)


def initialize_archive(connection):
    if connection.in_transaction:
        raise sqlite3.IntegrityError("initialize outside business transactions")
    connection.execute("BEGIN IMMEDIATE")
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables:
            for statement in DDL_STATEMENTS:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata VALUES (?)", (SCHEMA_VERSION,))
        else:
            expected = {"metadata", "studies", "revisions", "arms", "cohorts",
                        "cohort_members", "results", "result_evidence",
                        "result_weights", "result_contributions"}
            if tables != expected:
                raise sqlite3.IntegrityError("unsupported archive structure")
            versions = connection.execute("SELECT version FROM metadata").fetchall()
            if [tuple(row) for row in versions] != [(SCHEMA_VERSION,)]:
                raise sqlite3.IntegrityError("unsupported archive version")
            for statement in DDL_STATEMENTS[1:]:
                table = statement.split("(")[0].split()[-1]
                connection.execute(f"SELECT * FROM {table} LIMIT 0")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
