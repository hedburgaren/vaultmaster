FROM python:3.12-slim

# Pinned tool versions. Both land in the backup/restore critical path, so they
# are bumped on purpose rather than drifting on rebuild.
ARG AGE_VERSION=1.3.1
ARG DOCKER_CLI_VERSION=27.5.1

# Add PostgreSQL 16 apt repo + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg2 lsb-release curl ca-certificates \
    && echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg \
    && apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    postgresql-client-16 \
    rclone \
    # age is pinned. It used to fetch dl.filippo.io/age/latest, which made the
    # binary in the encryption path float with whatever upstream published at
    # build time. Bump deliberately, not by rebuilding.
    && curl -fsSL https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz -o /tmp/age.tar.gz \
    && tar -xzf /tmp/age.tar.gz -C /usr/local/bin --strip-components=1 \
    && rm /tmp/age.tar.gz \
    # docker CLI (client only, no daemon). restore_validator shells out to
    # `docker run` to restore dumps into a throwaway postgres container against
    # the mounted socket. Without this binary every postgresql validation died
    # with FileNotFoundError, which is part of why 0 validations had ever
    # passed before 2026-07-19.
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz \
    && apt-get purge -y gnupg2 lsb-release curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bump pip itself for the build (covers GHSA-4xh5-x5gv-qwph + GHSA-6vgw-5pg2-w6jp).
# Then install pinned runtime deps. --no-cache-dir keeps image lean.
RUN pip install --no-cache-dir --upgrade "pip>=26.0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip-audit --strict --progress-spinner=off || echo "pip-audit found vulns at build-time (non-blocking)"

COPY api/ ./api/
COPY migrations/ ./migrations/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
