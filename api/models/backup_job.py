import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class BackupJob(Base):
    __tablename__ = "backup_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    backup_type: Mapped[str] = mapped_column(String(50), nullable=False)  # postgresql, docker_volumes, files, do_snapshot, custom
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id"), nullable=False)
    source_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule_cron: Mapped[str] = mapped_column(String(100), nullable=False)  # cron expression
    destination_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    retention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("retention_policy.id"))
    tags: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    domain: Mapped[str | None] = mapped_column(String(100))  # plastshop, heartpro, arc_gruppen, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    encrypt: Mapped[bool] = mapped_column(Boolean, default=False)
    pre_script: Mapped[str | None] = mapped_column(String(1000))  # shell command to run before backup
    post_script: Mapped[str | None] = mapped_column(String(1000))  # shell command to run after backup
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    server = relationship("Server", back_populates="backup_jobs")
    retention_policy = relationship("RetentionPolicy", back_populates="backup_jobs")
    runs = relationship("BackupRun", back_populates="job", cascade="all, delete-orphan")
