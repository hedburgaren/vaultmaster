import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class RetentionPolicy(Base):
    __tablename__ = "retention_policy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    keep_hourly: Mapped[int] = mapped_column(Integer, default=0)
    keep_daily: Mapped[int] = mapped_column(Integer, default=7)
    keep_weekly: Mapped[int] = mapped_column(Integer, default=4)
    keep_monthly: Mapped[int] = mapped_column(Integer, default=3)
    keep_yearly: Mapped[int] = mapped_column(Integer, default=0)
    max_age_days: Mapped[int] = mapped_column(Integer, default=365)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    backup_jobs = relationship("BackupJob", back_populates="retention_policy")
