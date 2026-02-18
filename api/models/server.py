import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class Server(Base):
    __tablename__ = "server"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22)
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ssh_key, ssh_password, api, local
    provider: Mapped[str] = mapped_column(String(100), default="custom")  # custom, digitalocean, hetzner, linode
    ssh_user: Mapped[str | None] = mapped_column(String(100))
    ssh_key_path: Mapped[str | None] = mapped_column(String(500))
    api_token_encrypted: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB, default=dict)  # os_info, disk_usage, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    backup_jobs = relationship("BackupJob", back_populates="server", cascade="all, delete-orphan")
    backup_runs = relationship("BackupRun", back_populates="server")
