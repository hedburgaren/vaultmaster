import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channel"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)  # email, slack, ntfy, telegram, webhook
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    triggers: Mapped[list | None] = mapped_column(ARRAY(String), default=list)  # run.success, run.failed, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
