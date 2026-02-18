import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Boolean, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class StorageDestination(Base):
    __tablename__ = "storage_destination"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    backend: Mapped[str] = mapped_column(String(50), nullable=False)  # local, s3, gdrive, sftp, b2
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # backend-specific config
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger, default=0)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    artifacts = relationship("BackupArtifact", back_populates="storage_destination")
