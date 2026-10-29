"""Refuse to run against a database whose schema does not match the models.

Exists because of a concrete incident, 2026-07-19/20: a purged_at column was
added to the BackupArtifact model while the matching migration had not run.
SQLAlchemy includes every mapped column in every SELECT and INSERT, so the
mismatch broke backups, rotation, purge and validation at the first query
that touched the table, hours after the deploy looked healthy. The API
started, the health check was green, and the failure surfaced only when a
scheduled task happened to run.

A process that cannot work must refuse to start, not start and fail at some
later query. Both entry points call this at boot:

  - main.py lifespan (the API)
  - celery worker init via _run_async (the workers, which is where the 2026
    incident actually detonated; a guard only on the API would have missed it)

create_all cannot be trusted for this: it creates missing TABLES but silently
ignores missing COLUMNS on existing tables, which is exactly the failing case.
"""

import logging

from sqlalchemy import inspect

from api.database import Base, engine

logger = logging.getLogger(__name__)


class SchemaMismatch(RuntimeError):
    """The database is missing columns the models expect."""


def _diff_sync(sync_conn) -> list[str]:
    insp = inspect(sync_conn)
    present_tables = set(insp.get_table_names())
    problems: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in present_tables:
            problems.append(f"table {table_name} missing entirely")
            continue
        db_cols = {c["name"] for c in insp.get_columns(table_name)}
        missing = {c.name for c in table.columns} - db_cols
        if missing:
            problems.append(f"{table_name}: missing column(s) {sorted(missing)}")
    return problems


async def assert_schema_matches() -> int:
    """Raise SchemaMismatch if any mapped column is absent from the database.

    Returns the number of tables checked, so callers can log something that
    could not have been produced by a check that never ran.

    Extra columns in the database are deliberately tolerated: they are what a
    not-yet-wired migration looks like, and old code running against a newer
    schema is the safe direction.
    """
    # Populate the registry ourselves. In celery's beat and worker processes
    # nothing has imported the models when the init signal fires, so
    # Base.metadata was empty and the first version of this guard reported
    # "0 tables match their models" as success. A guard that verifies zero
    # things and passes is the exact defect class it was written against.
    import api.models  # noqa: F401

    if not Base.metadata.tables:
        raise SchemaMismatch(
            "model registry is empty even after importing api.models. "
            "Refusing to treat a check of nothing as a pass."
        )

    async with engine.connect() as conn:
        problems = await conn.run_sync(_diff_sync)
    if problems:
        raise SchemaMismatch(
            "model/schema mismatch, refusing to run: " + "; ".join(problems)
            + ". Run the pending alembic migration, or roll the code back."
        )
    return len(Base.metadata.tables)
