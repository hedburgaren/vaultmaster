import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class BackupValidationRun(Base):
    """A scheduled or manual restore-validation attempt for a backup job's
    most recent (or specified) artifact.

    Validates that a backup is actually restorable — not just that it
    completed. Created in response to the 2026-05-01 incident where
    backups had been silently accepted but never tested.
    """

    __tablename__ = "backup_validation_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_job.id"), nullable=False)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_artifact.id"))
    # For restic-type jobs there's no artifact row yet; record the snapshot id directly.
    restic_snapshot_id: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending, running, passed, failed, skipped
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # What we checked, how it went
    check_type: Mapped[str] = mapped_column(String(50), default="restore")  # restore, integrity, sample
    error_message: Mapped[str | None] = mapped_column(Text)
    log_lines: Mapped[list | None] = mapped_column(JSONB, default=list)
    triggered_by: Mapped[str] = mapped_column(String(50), default="scheduler")  # scheduler, manual, post-backup

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job = relationship("BackupJob")
    artifact = relationship("BackupArtifact")
