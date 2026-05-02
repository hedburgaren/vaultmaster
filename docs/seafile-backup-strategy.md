# Seafile backup-strategi — beslutsunderlag

**Status:** Förslag, väntar Chrilles bekräftelse · **Skriven:** 2026-05-02

## Bakgrund

Seafile på hedburgaren har **945 GB** under `/srv/containers/seafile/seafile-data/storage`.
Nuvarande VaultMaster-jobb (`ARC Gruppen Odoo Files`, UUID `8d9a5991`) kör
`tar -czf … storage/` över SSH och timar ut i 2-timmars cykler. Det
fungerar inte och har aldrig gjort det. Disaster-incidenten 2026-05-01
visade att jobbet bara genererat retry-spam i ett halvår utan att någon
visste — eftersom notifikationer inte fungerade (separat fix i Story 1).

## Krav

1. **Komplett:** alla 945 GB med rimlig dataförlust (≤ 24h)
2. **Verifierbart:** vi måste kunna restora och kontrollera integritet
3. **Effektivt:** måste klara sig på en daglig cykel utan att stuva sig själv
4. **Härdat mot ransomware:** dest får inte vara skrivbart från source
5. **Retention:** minst 7 dagliga / 4 veckovisa / 6 månadsvisa snapshots (GFS)
6. **Operationellt rimligt:** ska gå att övervaka, inga shell-pipeline-monster

## Alternativ

### A) rsync över SSH

```
rsync -aHx --delete --link-dest=PREV /srv/containers/seafile/seafile-data/ DEST/<datestamp>/
```

| Aspekt | Bedömning |
|---|---|
| Initial copy | ~6-12h (945 GB över LAN-nivå-nät) |
| Daglig delta | ~10-30 min (få nya files i seafile-block-store) |
| Storage on dest | 945 GB + delta per snapshot (hardlink-dedup på fil-nivå) |
| Versionering | Per-snapshot katalog via `--link-dest` |
| Encryption on dest | Nej (om dest inte är krypterad disk/dest-side) |
| Restore | Kopiera tillbaka, sedan `seaf-fsck` |
| Resume vid avbrott | Ja (rsync är bra på det) |
| Kompatibilitet | Trivialt, finns överallt |
| Beroenden | rsync >=3.1 (för `--info`) |
| Operational risk | Låg — rsync är väl beprövat |

**Nackdel:** rsync `--link-dest` deduplicerar bara på fil-nivå. Seafile
lagrar små block (~1 MB), så dedup vinns redan via seafile självt. Men
mellan snapshots händer låg dedup. → diskbehov: 945 GB + ~5-10 GB/dag
delta = ~1.05 TB efter 30 dagar.

### B) restic — krypterad deduperad snapshot store

```
restic -r DEST init
restic -r DEST backup /srv/containers/seafile/seafile-data
restic -r DEST forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic -r DEST check
```

| Aspekt | Bedömning |
|---|---|
| Initial copy | ~12-24h (CPU-bundet pga AES-256 + chunking) |
| Daglig delta | ~30-60 min (chunk-dedup + dedup mot tidigare snapshots) |
| Storage on dest | ~250-400 GB efter dedup (block-nivå dedup hittar seafile-block) |
| Versionering | Native — `restic snapshots` listar alla |
| Encryption on dest | Ja, AES-256 native |
| Restore | `restic restore SNAPSHOT --target /restore` — kan välja file/dir |
| Resume vid avbrott | Ja, robust |
| Kompatibilitet | Behöver `restic`-binär (10 MB single-binary, finns för alla plattformar) |
| Beroenden | restic >=0.16 |
| Operational risk | Medel — kräver att repo-passwordet skyddas separat |
| Bonus | `restic mount` — montera snapshot via FUSE för selektiv recovery |

**Nackdel:** initial snapshot är CPU-tung. Vi förlorar mycket med rclone
"copyto"-modellen — restic skriver direkt till dest (S3/SFTP/local). Men
det är OK: VaultMaster kan trigga `restic backup` istället för `tar |
rclone`.

### C) Seafile-native dump

```
docker compose exec seafile seaf-cli list  # eller seaf-fsck för konsistens
docker compose exec seafile-db mysqldump --single-transaction seafile-db
docker compose exec seafile-db mysqldump --single-transaction ccnet-db
docker compose exec seafile-db mysqldump --single-transaction seahub-db
tar storage/  # eller rsync
```

| Aspekt | Bedömning |
|---|---|
| Initial copy | Som A/B + DB-dump (~30s) |
| Daglig delta | Storage-del som A/B + DB-dump |
| Storage on dest | Som A/B (DB-dump är trivial storlek) |
| Versionering | Måste byggas själv |
| Encryption on dest | Beror på storage-del |
| Restore | Restora DB först, sen storage, kör `seaf-fsck` |
| Resume vid avbrott | Beror på storage-del |
| Kompatibilitet | Seafile-version-bunden — kan brytas vid uppgradering |
| Beroenden | Storage-tool + mysqldump |
| Operational risk | Hög — kompositkomplex, fler delar att misslyckas |

**Fördel:** logiskt konsistent restore (DB + storage matchar). Vid bara
storage-restore med rsync/restic riskerar vi att DB pekar på filer som
inte finns eller tvärtom.

**Hur stort är problemet?** Seafile är robust — `seaf-fsck` repararar
mismatch automatiskt. I praktiken räcker storage-only-snapshots med
mysqldump som *tilläggs*-jobb som kompletterar.

## Rekommendation

**Restic (alt B) för storage + mysqldump som separat tilläggsjobb (alt C-light).**

Anledningar:
1. **Dedup-vinst:** 945 GB → ~250-400 GB på dest. Sparar ~600 GB diskplats.
2. **Versionerad GFS native:** redan en del av VaultMaster:s retention-modell,
   matchar (`api/services/rotation.py`) konceptuellt — vi kan delegera till
   restic-forget.
3. **Krypterad on-disk:** ger oss en lager mot ransomware om dest komprometteras.
4. **Resume-bar vid avbrott:** löser exakt det problem vi hade 2026-05-01.
5. **Logisk konsistens:** komplettera med `mysqldump` som ett 2-MB-jobb
   parallellt — minimal extra komplexitet.

**Konkret implementation:**

- Ny executor `api/services/restic_executor.py` som tar `source_config`:
  ```json
  {
    "paths": ["/srv/containers/seafile/seafile-data"],
    "exclude": ["**/cache/**", "**/tmp/**"],
    "repo_url": "rclone:b2:hedburgaren-seafile",
    "password_secret_ref": "credential:seafile-restic-pw",
    "retention": {"daily": 7, "weekly": 4, "monthly": 6}
  }
  ```
- Backup-typ `restic` läggs till i `BackupJob.backup_type`
- Restic kör direkt på source-host över SSH (ingen tar | rclone-pipeline)
- Repo-password lagras i (kommande) credentials-store, fallback `.env`

**Förvaltning:**

- `restic check` veckovis (bygger förtroende)
- `restic prune` månatligt (frigör utrymme efter forget)
- `restic snapshots` exponeras i UI som "Snapshot history"

**Stöd för andra jobb:** restic-executorn är generisk — kan användas för
samma typ av redan-existerande filjobb (Odoo filestores, etc.) där tar
inte är optimalt.

## Nästa steg

1. Pausa nuvarande seafile-jobbet (separat task)
2. Chrille bekräftar val (eller väljer annan riktning)
3. Implementera `restic_executor.py` (separat task)
4. Förbered B2-bucket (eller annan dest) + repo-password
5. Test-restore en delvis snapshot till tom container för att verifiera
