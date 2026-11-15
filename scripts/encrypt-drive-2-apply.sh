#!/usr/bin/env bash
# Steg 2 av 2: krypterar de gamla klartextkopiorna på Google Drive på plats (Chrille 2026-11-15).
# Körs från plastdesk med bypass, först efter att steg 1 har visat rätt urval:
#   bash /home/chrille/dev/projects/vaultmaster-backup-flow/scripts/encrypt-drive-2-apply.sh
# Per fil: hämta, kryptera, ladda upp, hämta tillbaka och dekryptera, jämför, uppdatera registret,
# och först då ta bort klartextfilen. Ett fel lämnar klartexten och registret orörda.
#   1. Kontroll: produktionen har verktyget.
#   2. Kryptering (--apply), tar ungefär en timme för 11,8 GB.
#   3. Ny torrkörning: inget kvar att kryptera.
#   4. Städning: databasdumpen från första driftsättningsförsöket tas bort.
set -euo pipefail
shopt -s inherit_errexit
PROD=/srv/containers/vm.hedburgaren.se
LOG=/tmp/encrypt-drive-2-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1
fail() { echo; echo "STOPP: $*"; echo "Klartextfiler som inte hann krypteras ligger kvar orörda. Logg: $LOG"; exit 1; }
trap 'fail "oväntat fel på rad $LINENO"' ERR

echo "== 1. Kontroll"
[ "$(hostname)" = "PlastDesk" ] || fail "körs från plastdesk"
ssh hedburgaren "test -f $PROD/api/maintenance/encrypt_legacy_drive.py" || fail "verktyget finns inte i produktionen, kör steg 1 först"

echo "== 2. Kryptering"
ssh hedburgaren "docker exec -w /app -e PYTHONPATH=/app vaultmaster-worker python -m api.maintenance.encrypt_legacy_drive --apply" \
  || fail "minst en fil kunde inte krypteras (se sammanfattningen ovan)"

echo "== 3. Kontroll efteråt"
ssh hedburgaren "docker exec -w /app -e PYTHONPATH=/app vaultmaster-worker python -m api.maintenance.encrypt_legacy_drive" | tee /tmp/encrypt-drive-after.txt

echo "== 4. Städning"
ssh hedburgaren "rm -f /tmp/vm-pre-0011-20261115-185748.dump" && echo "gammal databasdump borttagen"
trap - ERR
echo
echo "KLART. Logg: $LOG"
