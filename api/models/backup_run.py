import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, BigInteger, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class BackupRun(Base):
    __tablename__ = "backup_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_job.id"), nullable=False)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending, running, success, failed, partial, cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    log_lines: Mapped[list | None] = mapped_column(JSONB, default=list)  # [{ts, level, msg}]
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(50), default="scheduler")  # scheduler, manual, retry
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    job = relationship("BackupJob", back_populates="runs")
    server = relationship("Server", back_populates="backup_runs")
    artifacts = relationship("BackupArtifact", back_populates="run", cascade="all, delete-orphan")
