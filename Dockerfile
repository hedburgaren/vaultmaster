FROM python:3.12-slim

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
    && curl -sSL https://dl.filippo.io/age/latest?for=linux/amd64 -o /tmp/age.tar.gz \
    && tar -xzf /tmp/age.tar.gz -C /usr/local/bin --strip-components=1 \
    && rm /tmp/age.tar.gz \
    && apt-get purge -y gnupg2 lsb-release curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY migrations/ ./migrations/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
