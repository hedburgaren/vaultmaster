# Deployment Notes

Deploy-steg som måste köras på hedburgaren när nya commits landar.
Värdar steg per EPIC i ARC Tasks-projektet `01KQM0W1PVWDCQB5H6A6V18QZ6`.

Live: `https://vm.hedburgaren.se/` · Container path: `/srv/containers/vm.hedburgaren.se/`

---

## EPIC 0a — Släck branden

### Story 1: Discord-notifikationer

Innehåller:
- `api/services/notifier.py` — ny `_send_discord()` (bridge + webhook)
- `api/schemas.py` / `api/models/notification_channel.py` — `discord` i kommentar
- `tests/test_notifier_discord.py` — 5 standalone tests
- `scripts/seed_discord_channels.py` — idempotent seed för 4 kanaler

**Deploy:**

```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat
docker compose up -d api worker beat
docker compose logs --tail 50 api | grep -iE "error|warn" || echo "no errors"
```

**Smoke-test (lokalt, utan deploy):**

```bash
cd /srv/containers/vm.hedburgaren.se
docker compose exec -T api python -m tests.test_notifier_discord
# förväntat: 5 passed.
```

**Seed Discord-kanalerna** (efter deploy):

Hämta `arc-bridge-token` från Notion-page `30974749d022812596cec035c2b799be` (rubrik *arc-discord-bridge → Internal API token*). Hämta `chrille`-lösenordet från samma sida (*VaultMaster*).

```bash
cd /srv/containers/vm.hedburgaren.se
docker compose exec -T api python -m scripts.seed_discord_channels \
    --base-url http://localhost:8000 \
    --username chrille \
    --password '<vm-password>' \
    --bridge-url 'http://host.docker.internal:8600' \
    --bridge-token '<arc-bridge-token>'
```

(`--base-url http://localhost:8000` används inifrån api-containern. Utifrån
hosten kan du köra `--base-url https://vm.hedburgaren.se` istället.)

Förväntat:
- 4 rader skapas: `Discord #allmänt`, `Discord #plastshop`, `Discord #arcgruppen`, `Discord #heartpro`
- Varje kanal får triggers `run.failed,run.partial,storage.warning,storage.critical,server.offline`
- 4 test-meddelanden landar i Discord på respektive kanal

**Verifiering:**

1. Öppna Discord, kolla att test-meddelandet kommit i `#allmänt`, `#plastshop`, `#arcgruppen`, `#heartpro`
2. Pausa ett känt jobb och tvinga det att fela (eller väntar på nästa naturliga fail)
3. Bekräfta att en `Backup Failed`-embed (röd) dyker upp

**Rollback:**

Inget DB-schema ändrat — säkerhet att rulla tillbaka utan migration. Bara
`git revert <commit>` + `docker compose up -d --build api worker beat`. De
seedade DB-raderna kan tas bort via UI eller `DELETE /api/v1/notifications/channels/<id>`.

**Kända begränsningar:**

- Alla fyra kanaler får samma triggers — per-domän-routing baserat på `job_name`
  eller `server`-tag är ett separat task (kommer i polish-pass).
- `host.docker.internal` i `bridge_url` förutsätter att docker-compose-filen har
  `extra_hosts: host.docker.internal:host-gateway`. Den raden finns redan i `api`-tjänsten.

### Story 2: Pausa seafile + beslutsdokument

Innehåller:
- `docs/seafile-backup-strategy.md` — beslutsunderlag (rekommendation: restic)
- `scripts/pause_job.py` — pausa/återstarta jobb via API + ID-prefix

**Pausa nuvarande seafile-jobbet** (UUID börjar `8d9a5991`):

```bash
cd /srv/containers/vm.hedburgaren.se
docker compose exec -T api python -m scripts.pause_job \
    --base-url http://localhost:8000 \
    --username chrille \
    --password '<vm-password>' \
    --id-prefix 8d9a5991 \
    --pause
```

Verifiering:
- Inga nya retries i `docker compose logs --tail 100 worker`
- I UI: jobbet visas som inaktivt
- Celery-kön: `docker compose exec redis redis-cli LLEN backup` ska börja minska om något stack där

**Beslutsdokumentet** (`docs/seafile-backup-strategy.md`) sammanfattar
rsync vs restic vs seafile-native dump och rekommenderar restic. Läs och
besluta innan Story 2 task 3 implementeras.

### Story 2 Task 3: Restic-executor

Innehåller:
- `api/services/restic_executor.py` — ny executor (push-based, ingen rclone-transfer)
- `api/tasks/backup_tasks.py` — dispatch + `skip_transfer`-shortcut

**Source-host prereq** (måste finnas på varje server som ska köra
restic-jobb):

```bash
# Installera restic >= 0.16
sudo apt-get install -y restic

# Sätt RESTIC_PASSWORD i SSH-användarens profile
echo 'export RESTIC_PASSWORD="<long-random-password>"' >> ~/.bashrc
source ~/.bashrc
```

Lösenordet ska sparas separat (inte i någon backup) — annars är restic-arkivet
oåterhämtbart om hosten återställs från backup. Tills EPIC 2 är på plats:
spara i Notion credentials-page med tag `restic-password-<host>`.

**Skapa ett restic-backupjobb** (efter Chrilles beslut):

Via UI eller `POST /api/v1/jobs`:

```json
{
  "name": "Seafile Storage (restic)",
  "server_id": "<seafile-server-uuid>",
  "backup_type": "restic",
  "source_config": {
    "paths": ["/srv/containers/seafile/seafile-data"],
    "excludes": ["**/cache/**", "**/tmp/**", "**/.thumb/**"],
    "repo_url": "rclone:b2:hedburgaren-seafile",
    "password_env_var": "RESTIC_PASSWORD",
    "tags": ["seafile"],
    "retention": {"daily": 7, "weekly": 4, "monthly": 6}
  },
  "schedule_cron": "0 3 * * *",
  "destination_ids": [],
  "max_retries": 1
}
```

`destination_ids` är tom — restic pushar direkt till `repo_url`. Inga
artifact-rader skapas i nuvarande iteration; snapshot-ID och metadata
loggas i `BackupRun.log_lines`. (En framtida iteration integrerar
restic-repos som `StorageDestination`-typ.)

**Verifiering efter första körning:**

```bash
# På seafile-source-host:
restic -r rclone:b2:hedburgaren-seafile snapshots
restic -r rclone:b2:hedburgaren-seafile stats
restic -r rclone:b2:hedburgaren-seafile check --read-data-subset=1%
```

Och i VaultMaster: `BackupRun` visar `success` med `size_bytes` =
`data_added` (mycket mindre än 945 GB efter andra körningen pga dedup).

**Rollback:**

`git revert` på commit 1f2a3b4 (eller motsvarande) plus `docker compose
build api worker beat`. Restic-repon på dest påverkas inte av rollback —
de är källkod-oberoende och kan användas via `restic` CLI direkt.

### Story 3: Felmeddelanden visar verklig felorsak

Innehåller:
- `api/tasks/backup_tasks.py` — retry-meddelandet bär nu exc + senaste error-log som kontext
- `api/routers/dashboard.py` — `recent_errors` joinar job + server, lägger till `last_log` och `retry_count`
- `ui/src/components/Topbar.tsx` — full notifikations-info, klickbar → `/runs?expand=<id>`
- `ui/src/app/(app)/runs/page.tsx` — auto-expand + scroll till rad från URL-param

**Deploy:**

```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat ui   # ui rebuilds Next.js bundle
docker compose up -d
```

**Verifiering:**

1. Skapa eller pausa ett jobb så det failar (eller använd test-restore-failure).
2. Vänta tills `BackupRun.status='failed'` syns i dashboard.
3. Öppna VaultMaster i browsern → klicka på klock-ikonen i Topbar.
4. En notis ska visa: jobnamn, server, full felorsak (på flera rader), och en sekundär grå rad med `last_log` om olika från error.
5. Klick på notisen → navigerar till `/runs?expand=<id>`, raden auto-expanderas och scrollas in i view.

**Förväntad förändring i Celery-loggar:**

Före: `Retrying in 60s.`
Efter: `Retrying [retry 1/3 in 60s] tar failed: file changed during read | last log: ...`

---

## EPIC 0b — Backup-validation

Innehåller:
- `api/models/backup_validation_run.py` — ny tabell
- `api/services/restore_validator.py` — postgres/files/restic-validators
- `api/services/rclone_client.py` — `download_file_from_storage()`-helper
- `api/tasks/validation_tasks.py` — Celery task `validate_backup_job_task` + `scan_validation_candidates`
- `api/routers/validations.py` — REST-endpoints inkl manuell trigger
- `api/services/notifier.py` — nya events `validation.passed/failed/skipped`
- `api/tasks/celery_app.py` — beat-schedule + ny `validation`-kö
- `docker-compose.yml` — workers lyssnar på `validation`-kön
- `ui/src/lib/api.ts` + `ui/src/app/(app)/jobs/page.tsx` — last-validation-badge + manual trigger

**Deploy:**

```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat ui
docker compose up -d
docker compose logs --tail 50 worker | grep -iE "error|registered|validation" || true
```

`Base.metadata.create_all` skapar nya tabellen vid api-start (ingen manuell migration).

**Förutsättningar på source-host:**
- `docker` tillgängligt för pgvalidation (kör `postgres:16-alpine` temp-container)
- Bind-mount `/var/run/docker.sock` finns redan i compose

**Verifiering:**

1. Manuell trigger via UI: "ShieldCheck"-knappen i jobs-listan kör validation av senaste artifact.
2. Eller via API:
   ```bash
   curl -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"check_type":"restore"}' \
        https://vm.hedburgaren.se/api/v1/validations/jobs/<job-id>/trigger
   ```
3. Vänta 1-30 min beroende på dump-storlek. `GET /api/v1/validations?job_id=<id>` visar status.
4. Vid pass: jobs-listan visar grön sköld med datum.
5. Vid fail: röd sköld + Discord-notifiering "Backup Validation FAILED".

**Auto-schedule:**
- Beat kör `scan_validation_candidates` varje timme.
- Kandidater = aktiva jobb av typ postgresql/files/docker_volumes/restic som inte validerats senaste 24h.
- Kö: `validation` (worker -c 4).

**Begränsningar (MVP):**
- Endast pgdumps får full restore-test. files/docker_volumes får bara `tar -tzf`-listning. restic får `restic check --read-data-subset=1%`.
- Custom-jobb skippas (status='skipped').
- Validation kräver att VaultMaster-API-containern har dockersock + nätverk för att starta `postgres:16-alpine`.

**Rollback:** `git revert <commit>` + `docker compose build api worker beat ui` + `docker compose up -d`. Tabellen `backup_validation_run` ligger kvar i DB men används inte — kan droppas manuellt vid behov:
```sql
DROP TABLE backup_validation_run;
```

---

## EPIC 1 — Säkerhetshärdning

### Server-side hardening (commit 5624fef)

**Innehåller:**
- `api/main.py` — CORS strikt, ingen wildcard-fallback, `SlowAPIMiddleware`
- `api/rate_limiter.py` — delad limiter-instans
- `api/routers/auth.py` — använder shared limiter (decorators var no-ops innan)
- `api/services/ssh_client.py` — `shlex.quote()` runt user-input + PGPASSWORD via env istället för command-line
- `api/services/backup_executor.py` — `_safe_ident()`/`_safe_path()`-validatorer + `shlex.quote()` defense-in-depth
- `tests/test_backup_executor_validation.py` — 9 tester för injektion-rejection

**Pre-deploy: sätt ALLOWED_ORIGINS i `.env`**

I `/srv/containers/vm.hedburgaren.se/.env`:
```
ALLOWED_ORIGINS=https://vm.hedburgaren.se
ENV=production
```

Utan `ALLOWED_ORIGINS` startar API:et inte i prod. (Dev-fallback ger loopback-only.)

**Deploy:**
```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat
docker compose up -d
docker compose logs --tail 30 api | grep -iE "rate|cors|allowed_origins" || true
docker compose exec -T api python -m tests.test_backup_executor_validation
docker compose exec -T api python -m tests.test_notifier_discord
```

**Verifiering:**

1. **CORS strikt:** `curl -H "Origin: https://evil.example" https://vm.hedburgaren.se/api/health -i | grep -i "access-control"` ska INTE inkludera `Access-Control-Allow-Origin: *`.
2. **Rate-limit på login:** 6 snabba `POST /api/v1/auth/login` ska få 429 på 6:e (limit 5/min är konfig i auth.py — om limit-decorator behövs lägga till på login-endpoint, se follow-up).
3. **SSH injection avstängd:** browse-API med `path=/;cat /etc/passwd` ska bara försöka `ls` på den konstiga sökvägen, inte exekvera `cat`.
4. **Backup config validation:** POST `/api/v1/jobs` med `source_config={"db_name":"foo;rm -rf /"}` triggar 400/500 vid run, inte exekvering.

**Rollback:** `git revert 5624fef && docker compose build api worker beat && docker compose up -d`. Tar inte ned tabeller eller config.

### Beroendeuppgraderingar (commit följer)

**Innehåller:**
- `requirements.txt` — `python-jose==3.3.0` → `PyJWT==2.10.1`
- `api/auth.py` — `from jose import JWTError, jwt` → `import jwt; from jwt import PyJWTError`
- `ui/package.json` — Next.js `14.2.21` → `14.2.35`

**Deploy backend:**
```bash
docker compose build api worker beat
docker compose up -d api worker beat
docker compose exec -T api python -c "import jwt; print(jwt.__version__)"
# Verifiera login fortfarande fungerar:
curl -X POST https://vm.hedburgaren.se/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"chrille","password":"<pwd>"}' | head
```

**Deploy frontend (förslag):**
```bash
cd /srv/containers/vm.hedburgaren.se/ui
rm -f package-lock.json
docker compose build ui
docker compose up -d ui
```

(`rm package-lock.json` regenererar lockfilen mot ny next-version. `npm ci` med stale lock skulle annars failas med "EUSAGE".)

**Verifiering:**
- API: login → JWT funkar, både skapa och validera token.
- UI: laddar utan TS-typfel; ingen regression i Topbar/runs/jobs (testade sektioner från EPIC 0a/0b).

**Rollback:** `git revert <commit>` + om npm: ` rm package-lock.json && npm install` igen.

---

## EPIC 2 — Credential-kärna

### 2A: Crypto + model + CRUD/reveal (commit 132cc50)

**Pre-deploy: generera och sätt CREDENTIALS_MASTER_KEYS**

```bash
# Generera en Fernet-nyckel:
python -c "from cryptography.fernet import Fernet; print('v1:' + Fernet.generate_key().decode())"
# Output, t.ex.: v1:JTKXkqK_nWfVw...
```

Lägg i `/srv/containers/vm.hedburgaren.se/.env`:
```
CREDENTIALS_MASTER_KEYS=v1:<base64-Fernet-key>
```

**KRITISKT:** denna nyckel är HEMLIG och ska aldrig backas upp tillsammans med data. Spara separat (Notion-page med extra åtkomstskydd, eller offline). Om nyckeln går förlorad är credential-tabellen oåterhämtbar.

**Deploy:**
```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat
docker compose up -d api worker beat
docker compose exec -T api python -m tests.test_credentials_crypto
docker compose exec -T api python -c "from api.services.credentials_crypto import get_crypto; print('crypto loaded, latest version:', get_crypto().latest_version)"
```

**Verifiering (CRUD-flöde):**
```bash
TOKEN=$(curl -s -X POST https://vm.hedburgaren.se/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"chrille","password":"<pwd>"}' | jq -r .access_token)

# Skapa
curl -X POST https://vm.hedburgaren.se/api/v1/credentials \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Test Key","credential_type":"api_key","plaintext_value":"sk-secret-xyz"}'

# Lista (plaintext är INTE med)
curl -H "Authorization: Bearer $TOKEN" https://vm.hedburgaren.se/api/v1/credentials | jq

# Reveal med fel password (ska 403)
curl -X POST https://vm.hedburgaren.se/api/v1/credentials/<id>/reveal \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"password":"wrong","purpose":"test"}'

# Reveal med rätt password (returnerar plaintext + audit-rad)
curl -X POST https://vm.hedburgaren.se/api/v1/credentials/<id>/reveal \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"password":"<vm-password>","purpose":"manual-check"}'
```

### 2B: Storage encryption + Notion-import (commit följer)

**Storage encryption** är delvis bakåtkompatibel: gamla `StorageDestination`-rader med plaintext i `config` fortsätter fungera (rclone reading-path testar `enc:`-prefix). Vid nästa edit i UI re-encrypteras secrets.

För att tvinga migration av existerande rader:
```bash
docker compose exec -T api python -c "
import asyncio
from sqlalchemy import select
from api.database import async_session
from api.models.storage_destination import StorageDestination
from api.services.credentials_crypto import encrypt_dict_secrets

async def migrate():
    async with async_session() as db:
        for d in (await db.execute(select(StorageDestination))).scalars():
            d.config = encrypt_dict_secrets(dict(d.config or {}))
        await db.commit()
asyncio.run(migrate())
"
```

**Notion-import:**

```bash
docker compose exec -T api python -m scripts.import_notion_credentials \
  --base-url http://localhost:8000 \
  --vm-username chrille \
  --vm-password '<vm-password>' \
  --notion-token 'ntn_...' \
  --page-id 30974749d022812596cec035c2b799be
# (dry-run by default — granska output)

# När det ser bra ut, kör med --apply:
docker compose exec -T api python -m scripts.import_notion_credentials \
  --base-url http://localhost:8000 \
  --vm-username chrille \
  --vm-password '<vm-password>' \
  --notion-token 'ntn_...' \
  --page-id 30974749d022812596cec035c2b799be \
  --apply
```

Idempotent på `name` — re-run uppdaterar existerande rader. Markera Notion-sidan `[migrerad]` manuellt efter lyckad import.

**Rollback:**
- Crypto: dropp `credential`-tabellen + ta bort `CREDENTIALS_MASTER_KEYS` ur env. API startar fortsatt.
- Storage encryption: är defensivt — fallback till plaintext om crypto inte är konfig. Inga manuella steg.

---

## EPIC 3 — Credential UI

Innehåller:
- `ui/src/components/Toast.tsx` — global toast-system med `<ToastProvider>` + `useToast()`
- `ui/src/components/ConfirmModal.tsx` — destructive-aware confirm-dialog
- `ui/src/app/(app)/layout.tsx` — `<ToastProvider>` runt hela appen
- `ui/src/components/Sidebar.tsx` + `i18n.ts` — ny `Credentials`-flik
- `ui/src/app/(app)/credentials/page.tsx` — full UI:
  - Lista med sök, type-filter, tag-filter
  - Detaljpanel med Info-/Audit-flikar
  - Reveal-modal med re-auth + 60s auto-clear timer + copy-to-clipboard som rensar efter 30s
  - Create-modal med show/hide-toggle
  - Audit-flik visar `audit_log`-rader filtrerade på `resource_type=credential` + `resource_id`

**Deploy:**
```bash
cd /srv/containers/vm.hedburgaren.se/ui
rm -f package-lock.json
cd ..
docker compose build ui
docker compose up -d ui
```

**Verifiering:**
1. Logga in i UI, klicka Credentials i sidebar.
2. Klicka "New" → skapa en test-credential.
3. Klicka raden, klicka "Reveal", ange ditt password, syfte "test".
4. Plaintext visas, timer räknar ner från 60. Klicka Copy.
5. Vänta tills timer går till 0 — plaintext försvinner från DOM.
6. Klicka Audit-flik på samma credential — se `credential.create` och `credential.reveal` med `purpose=test`.
7. Försök Reveal med fel password → "Re-auth failed" toast + en `credential.reveal.denied`-rad i audit.

**Begränsningar:**
- Story 4 ("ersätt alert/confirm globalt"): infrastrukturen finns (`Toast`, `ConfirmModal`) och används i credentials-sidan. Refactor av befintliga `alert()`/`confirm()`-anrop i jobs/artifacts/etc. är scope-utvidgning som förvarvas separat.

**Rollback:** `git revert <commit>` + `docker compose build ui && docker compose up -d ui`. Inga DB-ändringar.

---

## EPIC 4 — Credential MCP

Innehåller:
- `api/models/mcp_client.py` — ny tabell `mcp_client` (key_hash + scopes per AI-agent)
- `api/mcp/auth.py` — `get_mcp_client` dependency som validerar `X-MCP-Key`
- `api/mcp/server.py` — `/api/mcp/v1/`-endpoints med `tools`, `tools/search_credentials`, `tools/get_credential`
- `api/routers/mcp_clients.py` — admin-CRUD + key rotation
- `api/schemas.py` — MCPClient-scheman
- `tests/test_mcp_visibility.py` — 6 tester för scope-intersection-logiken

**Designbeslut (Kimi:s rekommendation):** `get_credential` returnerar plaintext direkt. Skydd:
- `mcp_enabled` måste vara `true` på credentialen
- Klientens `scopes` måste skära credentialens `mcp_scopes ∪ tags`
- Varje anrop loggas i `audit_log` med `client_id`, `purpose`, IP
- "Not found" och "not visible" returnerar samma 404 för att inte läcka existens

**Deploy:**
```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat
docker compose up -d api worker beat
docker compose exec -T api python -m tests.test_mcp_visibility
docker compose exec -T api python -c "from api.models.mcp_client import MCPClient; print(MCPClient.__table__.columns.keys())"
```

`Base.metadata.create_all` skapar tabellen vid api-restart.

**Skapa en MCP-klient (admin-flow via API):**
```bash
TOKEN=$(curl -s -X POST https://vm.hedburgaren.se/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"chrille","password":"<pwd>"}' | jq -r .access_token)

curl -X POST https://vm.hedburgaren.se/api/v1/mcp-clients \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"klada-cli","scopes":["plastshop","ai"],"rate_limit_per_minute":60}'
```

Svaret innehåller `raw_key` (typ `mcp_xxxxxxxxxx...`) — **denna visas en gång** och måste sparas direkt. Lagra den t.ex. i `.env` på Klådan/n8n eller som credential med `mcp_enabled=false` (vi lagrar inte våra MCP-nycklar i samma vault som de är till för att läsa).

**Test som MCP-klient:**
```bash
MCP_KEY="mcp_..."

# List tool catalog
curl https://vm.hedburgaren.se/api/mcp/v1/tools \
  -H "X-MCP-Key: $MCP_KEY"

# Search
curl -X POST https://vm.hedburgaren.se/api/mcp/v1/tools/search_credentials \
  -H "X-MCP-Key: $MCP_KEY" -H "Content-Type: application/json" \
  -d '{"arguments":{"query":"groq","tags":["ai"]}}'

# Get plaintext
curl -X POST https://vm.hedburgaren.se/api/mcp/v1/tools/get_credential \
  -H "X-MCP-Key: $MCP_KEY" -H "Content-Type: application/json" \
  -d '{"arguments":{"id":"<credential-uuid>","purpose":"klada-runtime-call"}}'
```

**Verifiering av audit:**
- I VaultMaster UI → Credentials → välj credentialen → Audit-flik
- `mcp.credential.search` och `mcp.credential.get` ska visas med klientnamn + purpose
- Försök med en credential som INTE är `mcp_enabled` eller där scope inte matchar → `mcp.credential.get.denied`

**Begränsningar (MVP):**
- Inte full FastMCP SSE-binding — det är custom REST som följer MCP-tools-mönstret. AI-klienter kan anropa det direkt via httpx; för fullständig MCP SSE-discovery krävs senare wrapping. Logiken (auth, scope, audit) är samma.
- Per-klient rate-limiting läggs på som SlowAPI-decorator i en follow-up (modellen har `rate_limit_per_minute`-fält redo).

**Rollback:** `git revert <commit>` + `docker compose build api worker beat && docker compose up -d`. `mcp_client`-tabellen kan ligga kvar eller droppas vid behov.

---

## EPIC 5 — Operational maturity

Innehåller:
- `api/middleware/audit.py` — `AuditLogMiddleware` skriver en blanket-audit-rad per muterande request
- `api/routers/auth.py` — TOTP setup/verify/disable + login kräver code om `totp_enabled`
- `api/routers/credentials.py` — reveal kräver TOTP om `totp_enabled`
- `api/tasks/credential_tasks.py` — `scan_credential_expiry`-task (daily)
- `api/services/notifier.py` — events `credential.expiring` / `credential.expired`
- `requirements.txt` — `pyotp==2.9.0`, `qrcode[pil]==8.0`
- `scripts/check_server_heartbeat.py` — diagnostic CLI för stale heartbeats

**Deploy:**
```bash
cd /srv/containers/vm.hedburgaren.se
git pull
docker compose build api worker beat
docker compose up -d api worker beat
docker compose exec -T api python -c "import pyotp; print('pyotp', pyotp.__version__)"
```

### Audit-log instrumentation

`AuditLogMiddleware` registrerar automatiskt en `http.<method>` audit-rad
för varje 2xx-svar på POST/PUT/PATCH/DELETE under `/api/v1/`, med användare
upplöst från Authorization eller X-API-Key. Routers som redan loggar
domänspecifika rader (credentials, mcp_clients) fortsätter göra det —
middleware är blanket-coverage utöver dem.

**Verifiering:**
```bash
TOKEN=$(curl -sX POST https://vm.hedburgaren.se/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"chrille","password":"<pwd>"}' | jq -r .access_token)

curl -X POST https://vm.hedburgaren.se/api/v1/servers \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"audit-test","host":"127.0.0.1"}'

curl -H "Authorization: Bearer $TOKEN" \
  "https://vm.hedburgaren.se/api/v1/audit?action=http&limit=5" | jq
```

Du ska se `http.post` med detail `POST /api/v1/servers → 201`.

### TOTP

**Aktivera (per användare):**
```bash
TOKEN=...
SETUP=$(curl -sX POST https://vm.hedburgaren.se/api/v1/auth/totp/setup \
  -H "Authorization: Bearer $TOKEN")
echo "$SETUP" | jq -r .qr_png_base64 | sed 's|data:image/png;base64,||' | base64 -d > /tmp/totp.png
# Skanna /tmp/totp.png med Authenticator. Mata in koden:
curl -X POST https://vm.hedburgaren.se/api/v1/auth/totp/verify \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"totp_code":"123456"}'
# Svar: {"enabled": true}
```

**Login efter aktivering:** body måste inkludera `totp_code` — annars 401 "TOTP code required".
**Reveal efter aktivering:** request måste inkludera `totp_code` utöver `password` — annars 403.
**Disable:** `POST /auth/totp/disable` med både `password` OCH giltig `totp_code`.

**UI-uppdatering kommer separat** — login-sidan och reveal-modalen behöver code-inputfält när `totp_enabled=true` returneras av `/auth/me`. Backend är redo idag, frontend-fält kan landa i en följdkommit.

### Credential expiry-warnings

Beat-task körs dagligen kl 00:00 UTC (86400s-schedule). Den skannar alla
credentials med `expires_at != NULL` och fyrar:
- `credential.expiring` om < 7 dagar kvar
- `credential.expired` om passerat

Notifications routas via befintlig Discord-bridge (EPIC 0a) till alla
NotificationChannel-rader som har dessa events i triggers-array. Lägg
till dem i seed-skriptet eller via UI:
```bash
docker compose exec -T api python -m scripts.seed_discord_channels \
  --triggers run.failed,run.partial,storage.warning,storage.critical,server.offline,credential.expiring,credential.expired \
  ...
```

**Test:** skapa en credential med `expires_at` imorgon, kör tasken manuellt:
```bash
docker compose exec -T worker celery -A api.tasks.celery_app call api.tasks.credential_tasks.scan_credential_expiry
```
Inom 1-2 minuter ska Discord få ett `Credential Expiring`-meddelande.

### VaultMaster-agent recovery (incidenten 2026-05-01)

`scripts/check_server_heartbeat.py` listar servrar med stale heartbeats
och föreslår diagnostiska steg. Acceptance från task: UI visar
"Servrar online: 1/1".

```bash
docker compose exec -T api python -m scripts.check_server_heartbeat \
  --base-url http://localhost:8000 \
  --username chrille --password '<pwd>' \
  --threshold-minutes 15
```

**Rotsorsak 2026-05-01 (att undersöka manuellt på hedburgaren):**
- VaultMaster-agenten på source-host slutade heartbeata
- Möjliga orsaker:
  1. Agent-processen har dött (`ps aux | grep vaultmaster-agent` eller `systemctl status vaultmaster-agent`)
  2. Disk fullt → loggning failas → agent kraschar (`df -h /`)
  3. SSH-nyckel utbytt utan att VaultMaster-config uppdaterades
  4. Klock-skew > 5 min → JWT auth failas (`timedatectl status`)
- Recovery: starta om agent-tjänsten, kolla logfilen, verifiera nästa
  heartbeat i UI

**Rollback:**
- TOTP: kan inaktiveras per user via `/totp/disable`. Kan också rullas
  tillbaka via direkt SQL: `UPDATE "user" SET totp_enabled=false, totp_secret=NULL WHERE username='chrille'` om låst ute.
- Audit-middleware: `git revert <commit>` + rebuild — inga DB-ändringar.
- Expiry-task: `git revert` + rebuild + `docker compose restart beat` så beat-schedule omladas.
