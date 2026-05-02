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
