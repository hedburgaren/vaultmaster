#!/usr/bin/env bash
# deploy-backup-flow.sh: för ut backup-flödet per maskin (kort DEV-13, Chrilles krav 2026-11-15)
# till VaultMaster på hedburgaren. Körs från plastdesk, som chrille, med Chrilles bypass:
#   bash /home/chrille/dev/projects/vaultmaster-backup-flow/scripts/deploy-backup-flow.sh
#
# Efteråt har hedburgaren, plastdesk och plastop var sin arbetsplats (kö och worker), så att en
# avstängd laptop eller desktop aldrig håller serverns kopior. plastop hämtas inte längre på fasta
# tider: laptopen checkar in själv (laptop/install-on-plastop.sh, när plastop är på).
#
#   1. Kontroller: grenen är ren, testerna går igenom lokalt, produktionen står på 7f44dba och är ren.
#   2. main = backup-flow (fast-forward), push till GitHub.
#   3. Väntar tills ingen kopia, validering eller återställning pågår (högst 3 h).
#   4. Dump av VaultMasters databas före migreringen.
#   5. git pull i produktionen; bara de väntade filerna ändras. Testerna körs i produktionens image.
#   6. Migrering 0011, nya workers startas, övriga startas om tillsammans.
#   7. Kontroll: alla containrar uppe, varje worker lyssnar på rätt kö, API svarar, hälsokollar per kö.
#   8. plastops jobb utan schema, incheckningstoken skapas (scripts/vm_flow_setup.py).
#   9. Dumpen från steg 4 tas bort när allt är kontrollerat.
# Återställning: se ROLLBACK längst ner, skriptet skriver ut den vid fel efter steg 5.
set -euo pipefail
shopt -s inherit_errexit
WT=/home/chrille/dev/projects/vaultmaster-backup-flow
MAIN=/home/chrille/dev/projects/vaultmaster
PROD=/srv/containers/vm.hedburgaren.se
OLD=7f44dba
IMAGE=vmhedburgarense-worker:latest
PY=/tmp/vm-venv/bin/python
TS=$(date +%Y%m%d-%H%M%S)
DUMP=/tmp/vm-pre-0011-$TS.dump
LOG=/tmp/deploy-backup-flow-$TS.log
exec > >(tee -a "$LOG") 2>&1
PULLED=no
rollback_hint() {
  [ "$PULLED" = yes ] || return 0
  echo
  echo "ROLLBACK (kör inte utan Klådan):"
  echo "  ssh hedburgaren 'cd $PROD && docker exec vaultmaster-api alembic downgrade 0010_stale_and_missed_triggers'"
  echo "  ssh hedburgaren 'cd $PROD && docker compose stop workstation-worker laptop-worker && git reset -q --hard $OLD'"
  echo "  ssh hedburgaren 'docker restart vaultmaster-worker vaultmaster-scheduler vaultmaster-beat vaultmaster-api'"
  echo "  Databasdump före migreringen: $DUMP"
}
fail() { echo; echo "STOPP: $*"; rollback_hint; echo "Logg: $LOG"; exit 1; }
trap 'fail "oväntat fel på rad $LINENO"' ERR

echo "== 1. Kontroller"
[ "$(hostname)" = "PlastDesk" ] || fail "körs från plastdesk"
[ -z "$(git -C "$WT" status --porcelain)" ] || fail "arbetskopian har ocommittade ändringar"
[ "$(git -C "$WT" rev-parse --abbrev-ref HEAD)" = backup-flow ] || fail "fel gren"
git -C "$WT" merge-base --is-ancestor "$OLD" HEAD || fail "grenen bygger inte på $OLD"
for m in test_workstation_lane test_scheduler_lane test_quiet_hosts; do
  (cd "$WT" && "$PY" -m "tests.$m" > "/tmp/deploy-bf-$m.log" 2>&1) || fail "testet $m går inte igenom lokalt (/tmp/deploy-bf-$m.log)"
  echo "ok lokalt: $m"
done
CUR=$(ssh hedburgaren "git -C $PROD rev-parse --short=7 HEAD")
[ "$CUR" = "$OLD" ] || fail "produktionen står på $CUR, väntade $OLD. Inget ändrat."
[ -z "$(ssh hedburgaren "git -C $PROD status --porcelain --untracked-files=no")" ] || fail "spårade filer ändrade i produktionen"
EXPECTED=$(git -C "$WT" diff --name-only "$OLD" HEAD | sort)
NEW=$(git -C "$WT" rev-parse HEAD)
echo "ok: produktionen på $OLD, ny version ${NEW:0:7}, $(wc -l <<<"$EXPECTED") filer"

echo "== 2. main och push"
git -C "$MAIN" fetch -q origin
[ "$(git -C "$MAIN" rev-parse origin/main)" = "$(git -C "$MAIN" rev-parse "$OLD")" ] || fail "origin/main har flyttat sig sedan $OLD"
git -C "$MAIN" merge -q --ff-only backup-flow
git -C "$MAIN" push -q origin main
[ "$(git -C "$MAIN" rev-parse origin/main)" = "$NEW" ] || fail "pushen gick inte fram"
echo "ok: origin/main = ${NEW:0:7}"

echo "== 3. Väntar på ledig worker"
for i in $(seq 1 180); do
  OUT=$(ssh hedburgaren "docker exec vaultmaster-worker celery -A api.tasks.celery_app inspect active 2>&1" || true)
  if grep -q ': OK' <<<"$OUT" && ! grep -qE 'run_backup_task|validate_backup_job_task|enforce_retention|restore' <<<"$OUT"; then
    echo "ledig"; break
  fi
  [ "$i" = 180 ] && fail "workern har varit upptagen i 3 h, försök igen senare (koden är pushad men inte utförd)"
  echo "  arbete pågår, nytt försök om 60 s ($i/180)"; sleep 60
done

echo "== 4. Databasdump"
ssh hedburgaren "docker exec vaultmaster-db sh -c 'pg_dump -Fc -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\"' > $DUMP && test -s $DUMP && ls -la $DUMP"

echo "== 5. git pull och test i produktionens image"
ssh hedburgaren "git -C $PROD pull --ff-only -q"
PULLED=yes
CHANGED=$(ssh hedburgaren "git -C $PROD diff --name-only $OLD HEAD" | sort)
[ "$CHANGED" = "$EXPECTED" ] || { ssh hedburgaren "git -C $PROD reset -q --hard $OLD"; PULLED=no; fail "oväntade filer i pullen, återställt till $OLD"; }
for m in test_workstation_lane test_scheduler_lane; do
  ssh hedburgaren "docker run --rm -v $PROD:/app:ro -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python $IMAGE -m tests.$m" > "/tmp/deploy-bf-prod-$m.log" 2>&1 \
    || { ssh hedburgaren "git -C $PROD reset -q --hard $OLD"; PULLED=no; fail "testet $m gick inte igenom i produktionens image, återställt (/tmp/deploy-bf-prod-$m.log)"; }
  echo "ok i produktionens image: $m ($(tail -1 "/tmp/deploy-bf-prod-$m.log"))"
done

echo "== 6. Migrering och omstart"
ssh hedburgaren "docker exec vaultmaster-api alembic upgrade head"
ssh hedburgaren "docker exec vaultmaster-api alembic current" | tee /tmp/deploy-bf-alembic.txt
grep -q '0011' /tmp/deploy-bf-alembic.txt || fail "migreringen står inte på 0011"
ssh hedburgaren "cd $PROD && docker compose up -d --no-deps workstation-worker laptop-worker"
ssh hedburgaren "docker restart vaultmaster-worker vaultmaster-scheduler vaultmaster-beat vaultmaster-api >/dev/null"
sleep 25

echo "== 7. Kontroll"
ssh hedburgaren "docker ps --format '{{.Names}} {{.Status}}' | grep vaultmaster-" | tee /tmp/deploy-bf-ps.txt
for c in worker scheduler beat api workstation-worker laptop-worker; do
  grep -q "^vaultmaster-$c Up" /tmp/deploy-bf-ps.txt || fail "vaultmaster-$c är inte uppe"
done
H=$(ssh hedburgaren "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/api/health")
[ "$H" = 200 ] || fail "API svarar $H"
for trio in "vaultmaster-worker:celery:backup" "vaultmaster-workstation-worker:workstation:workstation" "vaultmaster-laptop-worker:laptop:laptop" "vaultmaster-scheduler:scheduler:scheduler"; do
  IFS=: read -r c node q <<<"$trio"
  Q=$(ssh hedburgaren "docker exec $c sh -c 'celery -A api.tasks.celery_app inspect active_queues -d $node@\$(hostname)' 2>&1" || true)
  grep -q "'name': '$q'" <<<"$Q" || fail "$c lyssnar inte på kön $q"
  if [ "$c" != vaultmaster-worker ]; then
    [ "$(grep -o "'name': '[a-z_]*'" <<<"$Q" | sort -u | wc -l)" = 1 ] || fail "$c lyssnar på fler köer än $q"
  else
    grep -qE "'name': '(workstation|laptop)'" <<<"$Q" && fail "den gemensamma workern lyssnar på workstation eller laptop"
  fi
  echo "ok: $c lyssnar på $q"
done
echo "väntar på hälsokollarna per kö (högst 6 min)"
for i in $(seq 1 36); do
  A=$(ssh hedburgaren "docker logs --since 7m vaultmaster-worker 2>&1 | grep -c 'check_server_health.*succeeded'" || true)
  B=$(ssh hedburgaren "docker logs --since 7m vaultmaster-workstation-worker 2>&1 | grep -c 'check_workstation_health.*succeeded'" || true)
  C=$(ssh hedburgaren "docker logs --since 7m vaultmaster-laptop-worker 2>&1 | grep -c 'check_laptop_health.*succeeded'" || true)
  [ "${A:-0}" -gt 0 ] && [ "${B:-0}" -gt 0 ] && [ "${C:-0}" -gt 0 ] && { echo "ok: hälsokoll körd på backup, workstation och laptop"; break; }
  [ "$i" = 36 ] && fail "hälsokollarna kom inte på alla tre köer (backup=$A workstation=$B laptop=$C)"
  sleep 10
done
ssh hedburgaren "docker logs --since 8m vaultmaster-worker vaultmaster-workstation-worker vaultmaster-laptop-worker vaultmaster-scheduler 2>&1 | grep -iE 'traceback' | tail -3" || true

echo "== 8. plastop utan schema, incheckningstoken"
(cd "$WT" && python3 -I scripts/vm_flow_setup.py) || fail "inställningen av plastop misslyckades"

echo "== 9. Städning"
ssh hedburgaren "rm -f $DUMP" && echo "databasdumpen borttagen"
trap - ERR
echo
echo "KLART: VaultMaster kör ${NEW:0:7}. Nästa steg när plastop är på: bash $WT/laptop/install-on-plastop.sh"
