# hedburgaren — Disaster Recovery Plan

**Status:** Living document · v1 2026-05-02 · Owner: Chrille

> Skrivet efter brutalhaveriet 2026-05-01 där en kombination av disk-fel
> och avsaknad av notifieringar gjorde att vi körde blint i månader.
> Detta är vad vi gör NÄSTA gång det smäller.

---

## 0. Triage — när någonting just brann

**Innan du gör något: ta en bild av tillståndet.**

```bash
hostname; uptime; df -h; free -h
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
journalctl -p err -n 100 --no-pager
dmesg -T | tail -50
```

Spara output i `/tmp/triage-$(date +%Y%m%d_%H%M%S).log`. Den är guld
värd när vi felsöker dagen efter.

**Avgör tier:**
- **Tier 1 — host levande, en service nere** → gå till §3 per-system
- **Tier 2 — host levande, flera services nere, disk-fel suspect** → gå till §2 stabilisera
- **Tier 3 — host död / kernel panic / disk borta** → gå till §4 bare-metal

---

## 1. System-inventarie (vad ska räddas)

| System | Path | Storlek | Backup-källa | RPO | RTO | Krit |
|---|---|---|---|---|---|---|
| **VaultMaster** (vm.hedburgaren.se) | `/srv/containers/vm.hedburgaren.se/` | <1 GB | DB via pgdump-jobb, kod via git, `.env` separat | 24h | 1h | Hög |
| **Odoo PlastShop** (utv.plastshop.se) | `/srv/odoo/plastshop/` | ~5 GB DB + filestore | pgdump + filestore-tar via VaultMaster | 24h | 2h | Krit |
| **Odoo ARC Gruppen** | `/srv/odoo/arcgruppen.se/` | ~2 GB | dito | 24h | 2h | Hög |
| **Odoo HeartPro** | `/srv/odoo/heartpro.se/` | ~1 GB | dito | 24h | 2h | Med |
| **Odoo Jollyfood** | `/srv/odoo/jollyfood/` | ~500 MB | dito | 24h | 2h | Med |
| **n8n** | `/srv/n8n/hedburgaren/` | ~200 MB | DB-pgdump + workspace-tar | 24h | 1h | Hög |
| **NocoDB** | `/srv/containers/nocodb/` | ~500 MB | pgdump | 24h | 1h | Med |
| **Seafile** | `/srv/containers/seafile/seafile-data/` | 945 GB | restic (efter EPIC 0a Story 2.3 deploy) | 24h | 4-12h | Hög |
| **arc-discord-bridge** | `/srv/containers/arc-discord-bridge/` | <100 MB | git + `.env` | N/A | 30 min | Med |
| **arc-tasks** (lokala) | `/srv/containers/arc-tasks/` | ~200 MB | DB-pgdump | 24h | 1h | Hög |
| **render-engine** | `/srv/containers/render-engine/` | ~100 MB | git | N/A | 30 min | Låg |
| **arc-sidebar** | `/srv/containers/arc-sidebar/` | ~100 MB | git + `.env` | N/A | 30 min | Med |
| **dify / litellm / crew** | `/srv/containers/{dify,litellm,crew}` | ~5 GB | DB + workspace | 24h | 2h | Med |

**Krit-prio i recovery-ordning** (Tier 3 bare-metal):
1. Linux base + Docker + nginx
2. VaultMaster (vi behöver den för att restora resten)
3. Postgres-DB:erna (alla Odoo + n8n + nocodb)
4. Odoo-containers (PlastShop först — högst kund-impact)
5. Seafile (lång restore-tid — börja parallellt tidigt)
6. n8n + NocoDB
7. Övriga AI-services (dify/litellm/crew)
8. arc-discord-bridge + arc-sidebar (cosmetic — sist)

---

## 2. Tier 2 — Stabilisera vid pågående disk-fel

Innan något restoras: stoppa skrivning för att inte skriva mer korrupt
data.

```bash
# Frys ALLA non-critical containers (bara DB:erna kvar)
docker compose --project-directory /srv/containers/seafile down  # 945 GB skriver mest
docker compose --project-directory /srv/n8n/hedburgaren down
for d in arc-discord-bridge arc-sidebar arc-tasks render-engine dify litellm; do
  docker compose --project-directory /srv/containers/$d down 2>/dev/null
done

# Kolla SMART:
sudo smartctl -a /dev/sda  # eller /dev/nvme0n1 — anpassa
sudo smartctl -a /dev/sdb

# Filsystem-check (read-only först, kräver unmount för full):
sudo fsck -nf /dev/sda1   # -n = no-modify, -f = force-check
```

**Beslut Tier 2-vägval:**
- SMART OK + fsck OK → bug i applikation; gå till §3
- SMART degraderad men funktionellt → omedelbart kopiera kritisk data till annan disk; planera disk-byte; gå till §3 efter
- Disk-failure imminent → Tier 3, byt host

---

## 3. Per-system recovery

### 3.1 VaultMaster

```bash
cd /srv/containers/vm.hedburgaren.se
git status                    # är arbetsträdet rent?
docker compose ps             # vilka är upp?
docker compose logs --tail 100 api worker beat | grep -iE "error|fail|panic"
```

**API failar startup** (vanlig orsak: race + create_all):
```bash
docker compose up -d --force-recreate api worker beat
```

**DB-anslutning failar** (vanlig orsak: .env-pwd-mismatch):
```bash
# Verifiera mot DB-container:
docker exec -e PGPASSWORD="$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2)" \
  vaultmaster-db psql -U vaultmaster -d vaultmaster -c "SELECT 1"
# Om "password authentication failed" — synca:
docker exec -e PGPASSWORD="$(docker exec vaultmaster-db sh -c 'echo $POSTGRES_PASSWORD')" \
  vaultmaster-db psql -U vaultmaster -d vaultmaster -c "ALTER USER vaultmaster WITH PASSWORD '...'"
```

**Lockout (alla admins inaktiva)** — direkt SQL:
```bash
docker exec -e PGPASSWORD="$(grep ^POSTGRES_PASSWORD /srv/containers/vm.hedburgaren.se/.env | cut -d= -f2)" \
  vaultmaster-db psql -U vaultmaster -d vaultmaster \
  -c "UPDATE \"user\" SET is_active=true, is_admin=true WHERE username='chrille'"
```

**Tappade `CREDENTIALS_MASTER_KEYS`** — utan nyckel kan credential-tabellen
inte avläsas. Hämta från off-host backup (se §5). Om förlorad permanent:
```bash
docker exec -e PGPASSWORD=... vaultmaster-db psql -U vaultmaster -d vaultmaster \
  -c "TRUNCATE credential CASCADE"
# Sen kör scripts/import_notion_credentials.py mot Notion-kopian
```

**Full bare-metal-restore av VM** (§4 + dessa steg):
```bash
git clone https://github.com/hedburgaren/vaultmaster /srv/containers/vm.hedburgaren.se
cd /srv/containers/vm.hedburgaren.se
# Restore .env från säker plats (se §5):
cp /path/to/safe-backup/.env .
# Restore DB-dump:
docker compose up -d db
docker compose exec -T db pg_restore -U vaultmaster -d vaultmaster < /path/to/vaultmaster.dump
docker compose up -d
```

### 3.2 Odoo (4 instanser)

Varje Odoo-instance har samma layout: `docker-compose.yml`, `addons/`,
`config/`, postgres-volym `pgdata`.

```bash
cd /srv/odoo/plastshop  # eller annan instans
docker compose ps
docker compose logs --tail 100 odoo db | grep -iE "error|fatal"
```

**Restore från VaultMaster-backup:**

1. **Hitta senaste lyckade artifact:**
   ```bash
   # i VaultMaster UI: Backupjobb → 'PlastShop Postgres Daily' → Senaste run
   # eller via API:
   curl -H "Authorization: Bearer $TOKEN" \
     https://vm.hedburgaren.se/api/v1/artifacts?domain=plastshop&backup_type=postgresql \
     | jq '.[0]'
   ```
2. **Trigger restore i UI** (eller manuellt):
   ```bash
   docker compose stop odoo
   docker compose exec -T db psql -U odoo18 -c "DROP DATABASE \"utv.plastshop.se\""
   docker compose exec -T db psql -U odoo18 -c "CREATE DATABASE \"utv.plastshop.se\" OWNER odoo18"
   gunzip -c /path/to/utv.plastshop.se_*.dump.gz \
     | docker compose exec -T db pg_restore -U odoo18 -d utv.plastshop.se
   docker compose up -d odoo
   ```
3. **Kontrollera filestore** (uploads, attachments):
   ```bash
   ls /srv/odoo/plastshop/data/filestore/utv.plastshop.se/ | head
   # Om tom: restore filestore från vault-master files-jobb
   ```
4. **Smoke-test:** `curl -I https://utv.plastshop.se/web/login` ska ge 200/302.

### 3.3 Seafile (945 GB)

Den stora. Använd restic (EPIC 0a Story 2.3) — INTE tar-pipeline.

```bash
# På seafile-source-host, försäkra att restic finns + RESTIC_PASSWORD i env:
which restic && restic version
echo $RESTIC_PASSWORD | wc -c  # > 1?

# Lista snapshots:
restic -r rclone:b2:hedburgaren-seafile snapshots

# Full restore (riskabel om disken är trasig — gör till temp först):
restic -r rclone:b2:hedburgaren-seafile restore latest \
  --target /mnt/restore/seafile

# Selektiv restore (en användares data):
restic -r rclone:b2:hedburgaren-seafile restore latest \
  --target /mnt/restore/partial \
  --include '/srv/containers/seafile/seafile-data/storage/blocks/<libraryid>'

# Verifiera repo-integritet (1% read-data-subset, ~5 min):
restic -r rclone:b2:hedburgaren-seafile check --read-data-subset=1%
```

Efter restore: `seaf-fsck` på den restorade datan reparerar mismatch
mellan storage och DB.

### 3.4 Postgres point-in-time recovery (PITR)

**Status: ej aktiverat idag.** Vi har dagliga pgdump:s, vilket ger upp
till 24h dataförlust. För PITR krävs WAL-archiving.

Plan i EPIC 7 Story `01KQMAMTV8E2NZD3NDPX077769`:
- Aktivera `archive_mode=on` på alla Postgres-containers
- `archive_command='cp %p /var/lib/postgresql/wal-archive/%f'`
- Bind-mount wal-archive på /mnt/wal/<dbname>
- Backup wal-archive-katalogen via VaultMaster files-jobb

Tills aktiverat: max RPO är 24h.

### 3.5 Docker-only services (n8n, NocoDB, Discord-bridge etc.)

Generellt mönster:

```bash
cd /srv/containers/<service>
docker compose down
# Restore från VaultMaster-backup:
gunzip -c /path/to/<service>.dump.gz | docker compose exec -T db pg_restore -U <user> -d <db>
# Eller restore .env + workspace:
tar -xzf /path/to/<service>-files.tar.gz -C /
docker compose up -d
```

Per-service login + smoke-test (se DEPLOY.md per system).

---

## 4. Tier 3 — Bare-metal restore (host borta)

**Förutsättningar:**
- Ny Ubuntu 24.04 LTS-host (samma som hedburgaren)
- Root-tillgång + nätverk
- Kan nå backup-storage (B2/S3 + master-key off-host)

### 4.1 Base-OS

```bash
# Sätt hostname + tidszon
hostnamectl set-hostname hedburgaren
timedatectl set-timezone Europe/Stockholm

# Patcha + reboot
apt-get update && apt-get upgrade -y && reboot

# Användare + sudoers
useradd -m -s /bin/bash chrille && usermod -aG sudo chrille
# Kopiera over .ssh/authorized_keys till /home/chrille/.ssh/

# Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker chrille

# nginx + certbot
apt-get install -y nginx certbot python3-certbot-nginx
```

### 4.2 Restore /srv-trädet

**Källa:** off-host kopia av `/srv` (vilket man? — flagged som öppen
fråga: behöver formell off-host-strategi för hela /srv, idag är det
endast credentials-master-key som är off-host).

```bash
# Plats för storage:
mkdir -p /srv/containers /srv/odoo /srv/n8n /mnt/backup /srv/archive

# Restore code från GitHub (alla repos):
for repo in vaultmaster arc-discord-bridge arc-sidebar arc-tasks render-engine; do
  git clone https://github.com/hedburgaren/$repo /srv/containers/$repo
done

# Restore .env-filer (KRITISKT — innehåller secrets — kommer från
# off-host-backup, INTE från GitHub):
# manual: cp /backup/path/.env /srv/containers/<service>/.env

# Restore Odoo-instanser (kod via git, addons via VM-backup):
for inst in plastshop arcgruppen.se heartpro.se jollyfood; do
  git clone https://github.com/hedburgaren/odoo-$inst /srv/odoo/$inst
done
```

### 4.3 Restore master keys

Se §5.

### 4.4 Restore data

I prio-ordning från §1:

```bash
# 1. VaultMaster själv (vi behöver den för att hantera resten):
cd /srv/containers/vm.hedburgaren.se
docker compose up -d db
sleep 5
gunzip -c /backup/path/vaultmaster.dump.gz \
  | docker compose exec -T db pg_restore -U vaultmaster -d vaultmaster
docker compose up -d

# 2. Postgres-DB:er (parallellt):
for inst in plastshop arcgruppen.se heartpro.se jollyfood; do
  cd /srv/odoo/$inst
  docker compose up -d db
done
# Restore varje DB i ordning av kund-impact:
# (per-instans-recept, se §3.2)

# 3. Seafile (start först, kommer ta längst):
restic -r rclone:b2:hedburgaren-seafile restore latest \
  --target /srv/containers/seafile/seafile-data &

# 4. n8n + NocoDB + AI-services (parallellt):
for svc in n8n/hedburgaren containers/nocodb containers/dify containers/litellm; do
  cd /srv/$svc
  docker compose up -d
done
```

### 4.5 Nginx + DNS

```bash
# Restore nginx-conf:
rsync /backup/path/nginx/ /etc/nginx/

# Cert via Cloudflare DNS-challenge (eftersom port 80 inte är öppen):
certbot certonly --nginx -d vm.hedburgaren.se,utv.plastshop.se,...

# Verifiera Cloudflare DNS pekar på rätt IP (se ARC-credentials-page för token)
# Ingen ändring behövs om vi behåller samma IP.
```

### 4.6 Bekräftelse

```bash
# Per-domän smoke-tests:
for url in https://vm.hedburgaren.se/api/health \
           https://utv.plastshop.se/web/login \
           https://arcgruppen.se/web/login \
           https://heartpro.se/web/login \
           https://n8n.hedburgaren.se/healthz \
           https://nocodb.hedburgaren.se; do
  curl -sI --max-time 10 $url | head -1
done
```

**Förväntat tid total Tier 3:** 6-12h (varav Seafile-restore står för 4-8h).

---

## 5. Master-key recovery

`CREDENTIALS_MASTER_KEYS` (Fernet-nyckel från EPIC 2) är **den enda
secret som inte får backas tillsammans med data**. Om den läckt eller
backats med data är hela credential-tabellen oåterhämtbar.

**Off-host-strategi (story `01KQMAMTV9J97YWMXCPYKRJPD3` — TBD):**
- 1 förseglat kuvert i bankfack (Chrille)
- 1 kopia hos förtroend-nav (TBD)
- 1 GPG-krypterad fil hos GitHub Secret eller Bitwarden Personal Vault

Vid recovery:
```bash
# Hämta nyckeln från en av off-host-källorna
echo "CREDENTIALS_MASTER_KEYS=v1:..." >> /srv/containers/vm.hedburgaren.se/.env
docker compose -f /srv/containers/vm.hedburgaren.se/docker-compose.yml up -d --force-recreate api worker
# Verifiera att en gammal credential går att decrypta:
curl -X POST https://vm.hedburgaren.se/api/v1/credentials/<id>/reveal \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"password":"<vm-pwd>","purpose":"DR-recovery-test"}'
```

---

## 6. Test-procedur (kvartalsvis DR-drill)

Varje 90:e dag — ungefär 2026-08-01, 2026-11-01, 2027-02-01 — kör en
övning enligt något av följande scenarion. Alternera så vi täcker alla
över tid:

| Drill | Scenario | Vad som testas |
|---|---|---|
| **D1: VaultMaster-restore** | Spinn upp en tom VM-instance på en virt + restora från senaste backup | §3.1, §5 |
| **D2: Odoo-restore (en instans)** | PlastShop-DB till temp-container, läs in dump, smoke-test | §3.2 |
| **D3: Seafile partial-restore** | En användares lib från restic till `/mnt/restore-test` | §3.3 |
| **D4: PITR** *(efter aktivering)* | Restore till specifik timestamp inom senaste 24h | §3.4 |
| **D5: Bare-metal full** *(årsvis)* | Hela §4-flödet på VM eller låne-server | §4 |

Varje övning ska producera en **post-mortem** som uppdaterar denna doc.

---

## 7. Kontaktlista vid katastrof

| Roll | Person | Kontakt |
|---|---|---|
| Primär | Chrille | hedberg.chrille@gmail.com, telefon |
| Backup off-host-keeper | TBD | TBD |
| Cloudflare/DNS | Chrille | 1Password |
| ISP/host-leverantör | TBD | TBD |
| Bankfack med master-key | Chrille | Personlig info |

Update: så fort vi har 2 personer, lägg in som Story under EPIC 7.

---

## 8. Öppna frågor

1. **Off-host-backup för hela `/srv/`** — idag är det bara
   credentials-master-key som är off-host. Hela `/srv/` borde också
   speglas till t.ex. B2 eller annan host. Story behöver skapas.
2. **PITR-aktivering** — story `01KQMAMTV8E2NZD3NDPX077769`. Tills
   aktiverat är max RPO 24h.
3. **Hot-standby host** — kan vi ha en virtuell server som löpande
   speglar produktionen via Postgres-replication + restic-restore? Skulle
   sänka RTO från 6-12h till <30min.
4. **Cold-storage-arkiv** — månatlig snapshot av allt på offline-disk
   (bankfack) som *inte* kan ransomware-krypteras eftersom den är fysiskt
   urkopplad.

---

## Versionsändringar

- **v1 2026-05-02** (Klådan): första utkast efter brutalhaveriet
  2026-05-01 + lockout-incident 2026-05-02.
