import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# ── Server ──
class ServerCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    auth_type: str  # ssh_key, ssh_password, api, local
    provider: str = "custom"
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    api_token: str | None = None  # will be encrypted before storage
    tags: list[str] = []
    meta: dict = {}


class ServerUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    auth_type: str | None = None
    provider: str | None = None
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    api_token: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
    meta: dict | None = None


class ServerOut(BaseModel):
    id: uuid.UUID
    name: str
    host: str
    port: int
    auth_type: str
    provider: str
    ssh_user: str | None
    ssh_key_path: str | None = None
    tags: list[str] | None
    is_active: bool
    last_seen: datetime | None
    last_error: str | None
    meta: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Retention Policy ──
class RetentionPolicyCreate(BaseModel):
    name: str
    keep_hourly: int = 0
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 3
    keep_yearly: int = 0
    max_age_days: int = 365


class RetentionPolicyUpdate(BaseModel):
    name: str | None = None
    keep_hourly: int | None = None
    keep_daily: int | None = None
    keep_weekly: int | None = None
    keep_monthly: int | None = None
    keep_yearly: int | None = None
    max_age_days: int | None = None


class RetentionPolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    keep_hourly: int
    keep_daily: int
    keep_weekly: int
    keep_monthly: int
    keep_yearly: int
    max_age_days: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Storage Destination ──
class StorageDestinationCreate(BaseModel):
    name: str
    backend: str  # local, s3, gdrive, sftp, b2
    config: dict = {}
    capacity_bytes: int | None = None


class StorageDestinationUpdate(BaseModel):
    name: str | None = None
    backend: str | None = None
    config: dict | None = None
    is_active: bool | None = None
    capacity_bytes: int | None = None


class StorageDestinationOut(BaseModel):
    id: uuid.UUID
    name: str
    backend: str
    config: dict
    is_active: bool
    capacity_bytes: int | None
    used_bytes: int | None
    last_checked: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Backup Job ──
class BackupJobCreate(BaseModel):
    name: str
    backup_type: str  # postgresql, docker_volumes, files, do_snapshot, custom
    server_id: uuid.UUID
    source_config: dict = {}
    schedule_cron: str
    destination_ids: list[uuid.UUID] = []
    retention_id: uuid.UUID | None = None
    retention_overrides: dict = {}  # {dest_id: policy_id} per-destination override
    tags: list[str] = []
    domain: str | None = None
    encrypt: bool = False
    pre_script: str | None = None
    post_script: str | None = None
    max_retries: int = 2


class BackupJobUpdate(BaseModel):
    name: str | None = None
    backup_type: str | None = None
    source_config: dict | None = None
    schedule_cron: str | None = None
    destination_ids: list[uuid.UUID] | None = None
    retention_id: uuid.UUID | None = None
    retention_overrides: dict | None = None
    tags: list[str] | None = None
    domain: str | None = None
    is_active: bool | None = None
    encrypt: bool | None = None
    pre_script: str | None = None
    post_script: str | None = None
    max_retries: int | None = None


class BackupJobOut(BaseModel):
    id: uuid.UUID
    name: str
    backup_type: str
    server_id: uuid.UUID
    source_config: dict
    schedule_cron: str
    destination_ids: list[uuid.UUID] | None
    retention_id: uuid.UUID | None
    retention_overrides: dict | None = {}
    tags: list[str] | None
    domain: str | None
    is_active: bool
    encrypt: bool
    pre_script: str | None
    post_script: str | None
    max_retries: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Backup Run ──
class BackupRunOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    server_id: uuid.UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    size_bytes: int | None
    log_lines: list | None
    error_message: str | None
    triggered_by: str
    retry_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Backup Artifact ──
class BackupArtifactOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    storage_id: uuid.UUID
    filename: str
    remote_path: str
    size_bytes: int
    checksum_sha256: str
    is_encrypted: bool
    backup_type: str
    tags: list[str] | None
    domain: str | None
    db_name: str | None
    server_name: str | None
    expires_at: datetime | None
    is_deleted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ArtifactSearch(BaseModel):
    q: str | None = None
    backup_type: str | None = None
    domain: str | None = None
    server_name: str | None = None
    tags: list[str] | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    limit: int = Field(default=50, le=200)
    offset: int = 0


# ── Notification Channel ──
class NotificationChannelCreate(BaseModel):
    name: str
    channel_type: str  # email, slack, ntfy, telegram, webhook
    config: dict = {}
    triggers: list[str] = []


class NotificationChannelUpdate(BaseModel):
    name: str | None = None
    channel_type: str | None = None
    config: dict | None = None
    triggers: list[str] | None = None
    is_active: bool | None = None


class NotificationChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    channel_type: str
    config: dict
    triggers: list[str] | None
    is_active: bool
    last_sent: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Auth ──
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class SetupStatus(BaseModel):
    needs_setup: bool


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email_addresses: list[str] | None = []
    role: str | None = None
    is_active: bool
    is_admin: bool
    totp_enabled: bool = False
    api_key_prefix: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    email_addresses: list[str] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ApiKeyOut(BaseModel):
    api_key: str
    prefix: str
    message: str = "Store this key securely — it will not be shown again."


# ── Dashboard ──
class DashboardOut(BaseModel):
    servers_online: int
    servers_total: int
    jobs_active: int
    jobs_total: int
    storage_destinations: list[dict]
    runs_24h: int
    runs_success_24h: int
    runs_failed_24h: int
    success_rate: float
    next_runs: list[dict]
    active_runs: list[dict]
    recent_errors: list[dict]
    # Health widgets
    server_health: list[dict] = []
    total_artifacts: int = 0
    total_artifact_bytes: int = 0
    last_successful_backup: str | None = None
    hours_since_last_backup: float | None = None
    storage_warnings: list[dict] = []
