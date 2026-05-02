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
