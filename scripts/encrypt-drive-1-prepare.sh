#!/usr/bin/env bash
# Steg 1 av 2 för krypteringen av gamla klartextkopior på Google Drive (Chrille 2026-11-15:
# "Ja, kryptera de på drive"). Ändrar INGENTING på Drive. Körs från plastdesk med bypass:
#   bash /home/chrille/dev/projects/vaultmaster-backup-flow/scripts/encrypt-drive-1-prepare.sh
#   1. Kontroller: grenen ren, produktionen står på origin/main och är ren.
#   2. main = backup-flow (fast-forward), push. git pull i produktionen, bara väntade filer.
#      Bara nya filer under api/maintenance och tester ändras, så ingen omstart behövs.
#   3. Verktygets tester i produktionens image.
#   4. Torrkörning i vaultmaster-worker: lista vad som skulle krypteras (sparas i loggen).
#   5. --check-one: en redan krypterad fil från Drive går inte att läsa utan nyckeln.
set -euo pipefail
shopt -s inherit_errexit
WT=/home/chrille/dev/projects/vaultmaster-backup-flow
MAIN=/home/chrille/dev/projects/vaultmaster
PROD=/srv/containers/vm.hedburgaren.se
IMAGE=vmhedburgarense-worker:latest
LOG=/tmp/encrypt-drive-1-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1
fail() { echo; echo "STOPP: $*"; echo "Logg: $LOG"; exit 1; }
trap 'fail "oväntat fel på rad $LINENO"' ERR

echo "== 1. Kontroller"
[ "$(hostname)" = "PlastDesk" ] || fail "körs från plastdesk"
[ -z "$(git -C "$WT" status --porcelain)" ] || fail "arbetskopian har ocommittade ändringar"
git -C "$MAIN" fetch -q origin
ORIGIN=$(git -C "$MAIN" rev-parse origin/main)
NEW=$(git -C "$WT" rev-parse HEAD)
CUR=$(ssh hedburgaren "git -C $PROD rev-parse HEAD")
[ -z "$(ssh hedburgaren "git -C $PROD status --porcelain --untracked-files=no")" ] || fail "spårade filer ändrade i produktionen"
if [ "$CUR" = "$NEW" ]; then
  echo "produktionen står redan på ${NEW:0:7}"
else
  [ "$CUR" = "$ORIGIN" ] || fail "produktionen (${CUR:0:7}) står inte på origin/main (${ORIGIN:0:7})"
  git -C "$WT" merge-base --is-ancestor "$ORIGIN" "$NEW" || fail "grenen bygger inte på origin/main"
  EXPECTED=$(git -C "$WT" diff --name-only "$ORIGIN" "$NEW" | sort)
  grep -vqE '^(api/maintenance/|tests/|scripts/|CHANGELOG.md$)' <<<"$EXPECTED" && fail "ändringen rör mer än verktyget: $EXPECTED"

  echo "== 2. main, push och pull"
  git -C "$MAIN" merge -q --ff-only backup-flow
  git -C "$MAIN" push -q origin main
  [ "$(git -C "$MAIN" rev-parse origin/main)" = "$NEW" ] || fail "pushen gick inte fram"
  ssh hedburgaren "git -C $PROD pull --ff-only -q"
  CHANGED=$(ssh hedburgaren "git -C $PROD diff --name-only ${CUR:0:7} HEAD" | sort)
  [ "$CHANGED" = "$EXPECTED" ] || { ssh hedburgaren "git -C $PROD reset -q --hard $CUR"; fail "oväntade filer i pullen, återställt"; }
  echo "ok: produktionen på ${NEW:0:7}"
fi

echo "== 3. Tester i produktionens image"
ssh hedburgaren "docker run --rm -v $PROD:/app:ro -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python $IMAGE -m tests.test_encrypt_legacy_drive" > /tmp/encrypt-drive-test.log 2>&1 \
  || fail "testet gick inte igenom i produktionens image (/tmp/encrypt-drive-test.log)"
echo "ok: $(tail -1 /tmp/encrypt-drive-test.log)"

echo "== 4. Torrkörning"
ssh hedburgaren "docker exec -w /app -e PYTHONPATH=/app vaultmaster-worker python -m api.maintenance.encrypt_legacy_drive"

echo "== 5. En krypterad fil är oläsbar utan nyckeln"
ssh hedburgaren "docker exec -w /app -e PYTHONPATH=/app vaultmaster-worker python -m api.maintenance.encrypt_legacy_drive --check-one"
trap - ERR
echo
echo "KLART MED STEG 1. Ingenting är ändrat på Drive. Logg: $LOG"
