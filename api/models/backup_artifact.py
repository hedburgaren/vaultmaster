import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, BigInteger, Boolean, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class BackupArtifact(Base):
    __tablename__ = "backup_artifact"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_run.id"), nullable=False)
    storage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("storage_destination.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    remote_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    domain: Mapped[str | None] = mapped_column(String(100))
    db_name: Mapped[str | None] = mapped_column(String(255))
    server_name: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    run = relationship("BackupRun", back_populates="artifacts")
    storage_destination = relationship("StorageDestination", back_populates="artifacts")
