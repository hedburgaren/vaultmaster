#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# VaultMaster Installer
# https://github.com/hedburgaren/vaultmaster
# ─────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[VM]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║   🔐 VaultMaster Installer v2.0       ║"
echo "  ║   Backup Control Center               ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${NC}"

# Check prerequisites
command -v docker >/dev/null 2>&1 || err "Docker is required. Install: https://docs.docker.com/get-docker/"
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || err "Docker Compose is required."
command -v node >/dev/null 2>&1 || err "Node.js is required (v18+). Install: https://nodejs.org/"
command -v npm >/dev/null 2>&1 || err "npm is required."

ok "Prerequisites check passed"

# Clone or update
INSTALL_DIR="${VAULTMASTER_DIR:-./vaultmaster}"

if [ -d "$INSTALL_DIR" ]; then
    info "Updating existing installation in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull --ff-only
else
    info "Cloning VaultMaster to $INSTALL_DIR..."
    git clone https://github.com/hedburgaren/vaultmaster.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

ok "Source code ready"

# Generate .env if it doesn't exist
if [ ! -f .env ]; then
    info "Creating .env from template..."
    cp .env.example .env

    # Generate random secrets
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    PG_PASSWORD=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))")

    # Replace defaults
    sed -i "s|change-this-to-a-random-secret-key|${SECRET_KEY}|g" .env 2>/dev/null || true
    sed -i "s|POSTGRES_PASSWORD=changeme|POSTGRES_PASSWORD=${PG_PASSWORD}|g" .env 2>/dev/null || true
    sed -i "s|changeme@db|${PG_PASSWORD}@db|g" .env 2>/dev/null || true

    ok "Generated .env with random secrets"
    echo -e "  ${CYAN}→ Review and edit .env before production use${NC}"
else
    ok ".env already exists, keeping current config"
fi

# Start Docker services
info "Starting Docker services..."
docker compose up -d --build
ok "API, Worker, Scheduler, PostgreSQL, Redis started"

# Build frontend
info "Installing frontend dependencies..."
cd ui
[ ! -f .env.local ] && cp .env.example .env.local 2>/dev/null || true
npm install --silent
info "Building frontend (this may take a minute)..."
npx next build
ok "Frontend built"

echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  ✅ VaultMaster installed successfully!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  Start the frontend:  ${CYAN}cd ${INSTALL_DIR}/ui && npx next start --port 3100${NC}"
echo -e "  Open in browser:     ${CYAN}http://localhost:3100${NC}"
echo -e "  API docs:            ${CYAN}http://localhost:8100/api/docs${NC}"
echo -e "  Prometheus metrics:  ${CYAN}http://localhost:8100/api/metrics${NC}"
echo ""
echo -e "  On first visit, the setup wizard will guide you"
echo -e "  through creating your admin account."
echo ""
