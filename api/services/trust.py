"""Trust verdict per backup job.

The trust report answers the question an operator actually asks ("kan jag
lita på det här jobbet?") without digging through run history. The verdict
is computed from facts, and the facts travel with it: a green row with
hidden numbers is just a prettier version of the silent-success pattern
this codebase was built to kill.

Levels and their meaning:

  green  fresh successful copy, artifacts exist, validation recent and
         passing, and at least one off-site destination has a copy
  yellow something is stale or thinning (see reason keys) but the core
         holds: there IS a restorable copy
  red    no restorable copy in sight: never succeeded, no artifacts, or
         the latest validation FAILED (a backup that cannot be restored
         is decoration)

Reason keys are stable strings; the UI translates them. Server never
guesses Swedish or English for the operator.
"""

from datetime import datetime, timedelta, timezone


def trust_verdict(
    now: datetime,
    job_active: bool,
    last_success_at: datetime | None,
    oldest_artifact_at: datetime | None,
    artifact_count: int,
    destinations_with_copy: int,
    last_validation_at: datetime | None,
    last_validation_status: str | None,
    max_hours_between_success: int = 48,
    validation_stale_days: int = 7,
) -> dict:
    """Compute {level, reasons} for one job from plain facts."""
    reasons: list[str] = []

    def age_hours(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        return (now - dt).total_seconds() / 3600

    # Core: is there a restorable copy at all?
    if last_success_at is None:
        reasons.append("never_succeeded")
    if artifact_count <= 0:
        reasons.append("no_artifacts")

    # A failed validation is the loudest signal there is: the copy exists
    # and cannot be restored.
    if last_validation_status in ("failed",):
        reasons.append("validation_failed")

    # Freshness, only for jobs that are supposed to run.
    if job_active and last_success_at is not None:
        hours = age_hours(last_success_at)
        if hours is not None and hours > max_hours_between_success:
            reasons.append("stale_success")

    # Validation coverage. Jobs without a validator (custom types) carry
    # None/None and are not punished for it; validation_skip is a fact, not
    # a verdict.
    if last_validation_at is not None and last_validation_status not in ("failed",):
        days = age_hours(last_validation_at) / 24
        if days > validation_stale_days:
            reasons.append("validation_stale")

    if artifact_count > 0 and destinations_with_copy < 2:
        # One destination is a single point of failure: the local archive
        # counts, the off-site copy is what makes a backup survive the
        # machine. Zero is that plus an inconsistency worth seeing.
        reasons.append("no_offsite")

    if "never_succeeded" in reasons or "no_artifacts" in reasons or "validation_failed" in reasons:
        level = "red"
    elif reasons:
        level = "yellow"
    else:
        level = "green"

    return {"level": level, "reasons": reasons}
