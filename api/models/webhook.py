import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Text, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Webhook(Base):
    __tablename__ = "webhook"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255))  # HMAC signing secret
    events: Mapped[list | None] = mapped_column(ARRAY(String), default=list)  # backup.started, backup.completed, backup.failed, restore.started, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    headers: Mapped[dict | None] = mapped_column(JSONB, default=dict)  # custom headers
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
