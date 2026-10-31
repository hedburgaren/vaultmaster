#!/usr/bin/env bash
# deploy-quiet-hosts.sh: för ut VM.QUIET.01 till VaultMaster på hedburgaren och märker plastop.
# Körs av Chrille från plastdesk, som chrille.
#
# Efteråt larmar plastop inte när datorn är avstängd: inget "server offline", och en
# misslyckad kopia larmar bara om jobbet inte lyckats på 96 timmar. Kopiorna körs som förut
# när datorn är på.
#
#   1. Kontroll: produktionens config.py och backup_tasks.py är exakt origin/main (md5),
#      quiet_hosts.py finns inte än.
#   2. Backup av de två filerna (<fil>.pre-quiet-hosts).
#   3. Tre filer in (config.py, backup_tasks.py, ny services/quiet_hosts.py).
#   4. Servern plastop får taggen intermittent (en rad, inget annat ändras).
#   5. vaultmaster-api, -worker och -beat startas om, API:t svarar, loggen visas.
# Återställning: kopiera tillbaka <fil>.pre-quiet-hosts, ta bort quiet_hosts.py, starta om
# de tre containrarna. Taggen är ofarlig utan koden och kan tas bort i UI:t.
set -euo pipefail
REPO=/home/chrille/dev/projects/wt-vm-quiet-hosts
COMMIT=d1127ea
APP=/srv/containers/vm.hedburgaren.se/api
declare -A OLD_MD5=(
  [config.py]=380dc53bc8993559977c15913ec114f6
  [tasks/backup_tasks.py]=ae9b85bdd7c9d3ddf0e7f9307cfcad5c
)
FILES=(config.py tasks/backup_tasks.py services/quiet_hosts.py)
TMP="$(mktemp -d)"
declare -A NEW_MD5
for f in "${FILES[@]}"; do
  mkdir -p "${TMP}/$(dirname "${f}")"
  git -C "${REPO}" show "${COMMIT}:api/${f}" > "${TMP}/${f}"
  NEW_MD5[$f]="$(md5sum "${TMP}/${f}" | cut -c1-32)"
done

echo "== 1. Kontroll av produktionens filer"
for f in config.py tasks/backup_tasks.py; do
  CUR="$(ssh hedburgaren "md5sum ${APP}/${f}" | cut -c1-32)"
  [[ "${CUR}" == "${OLD_MD5[$f]}" ]] || { echo "STOPP: ${f} är inte den väntade (${CUR}). Inget ändrat."; exit 1; }
done
if ssh hedburgaren "test -e ${APP}/services/quiet_hosts.py"; then
  echo "STOPP: services/quiet_hosts.py finns redan. Inget ändrat."; exit 1
fi
echo "ok"

echo "== 2. Backup"
for f in config.py tasks/backup_tasks.py; do
  ssh hedburgaren "cp -p ${APP}/${f} ${APP}/${f}.pre-quiet-hosts"
done

echo "== 3. Nya filer"
for f in "${FILES[@]}"; do
  scp -q "${TMP}/${f}" "hedburgaren:${APP}/${f}.new"
  REF="${APP}/config.py"
  ssh hedburgaren "chmod --reference=${REF} ${APP}/${f}.new && chown --reference=${REF} ${APP}/${f}.new 2>/dev/null; mv ${APP}/${f}.new ${APP}/${f}"
done

echo "== 4. Taggen intermittent på plastop"
ssh hedburgaren "docker exec -i vaultmaster-db psql -U vaultmaster -d vaultmaster -v ON_ERROR_STOP=1 -At" <<'SQL'
UPDATE server SET tags = array_append(coalesce(tags, '{}'), 'intermittent'), updated_at = now()
WHERE name = 'plastop' AND NOT ('intermittent' = ANY(coalesce(tags, '{}')))
RETURNING name, tags;
SELECT 'nu: ' || name || ' ' || coalesce(array_to_string(tags, ','), '') FROM server WHERE name = 'plastop';
SQL

echo "== 5. Omstart och kontroll"
ssh hedburgaren "docker restart vaultmaster-api vaultmaster-worker vaultmaster-beat >/dev/null && sleep 20 && curl -s -o /dev/null -w 'API: %{http_code}\n' http://127.0.0.1:8100/api/health"
OK=1
for f in "${FILES[@]}"; do
  AFTER="$(ssh hedburgaren "md5sum ${APP}/${f}" | cut -c1-32)"
  [[ "${AFTER}" == "${NEW_MD5[$f]}" ]] || { echo "FEL: md5 för ${f} stämmer inte (${AFTER})"; OK=0; }
done
ssh hedburgaren "docker logs --since 1m vaultmaster-worker 2>&1 | grep -iE 'error|traceback' | grep -v 'SSH connection test failed' | tail -5" || true
[[ "${OK}" == 1 ]] && echo "KLAR: VaultMaster kör VM.QUIET.01 och plastop är märkt."
