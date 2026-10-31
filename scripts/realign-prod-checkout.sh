#!/usr/bin/env bash
# realign-prod-checkout.sh: gör VaultMasters driftkopia på hedburgaren till en ren kopia av
# GitHubs main igen, så att en vanlig git pull fungerar. Körs av Chrille från plastdesk.
#
# Läget 2026-10-31: deploy-quiet-hosts.sh skrev tre filer för hand (config.py,
# tasks/backup_tasks.py, services/quiet_hosts.py). Samma innehåll ligger nu på GitHubs main
# (f4dfdc9), men git ser dem som lokala ändringar, och main saknar uppströmsgren.
#
#   1. Hämtar från GitHub.
#   2. Kontroll: exakt de två väntade filerna är ändrade, och alla tre har exakt samma
#      innehåll som origin/main. Annars STOPP, inget ändrat.
#   3. Kopia av de tre filerna till /var/tmp/vm-realign-<stämpel>/.
#   4. Återställer de två filerna, flyttar undan quiet_hosts.py, spolar fram main till
#      origin/main (bara fast-forward) och sätter origin/main som uppström.
#   5. Kontroll: filerna har samma md5 som före (koden som körs är oförändrad, därför ingen
#      omstart), och git status visar inga ändrade spårade filer.
# Mellan steg 4:s återställning och framspolningen ligger gamla filer på disk i någon
# sekund; containrarna läser koden bara vid start, så det som körs påverkas inte.
set -euo pipefail
ssh hedburgaren 'bash -s' <<'REMOTE'
set -euo pipefail
R=/srv/containers/vm.hedburgaren.se
cd "$R"
FILES="api/config.py api/tasks/backup_tasks.py api/services/quiet_hosts.py"

echo "== 1. Hämtar"
git fetch -q origin
echo "origin/main: $(git log --oneline -1 origin/main)"

echo "== 2. Kontroll"
CHANGED="$(git diff --name-only | sort | tr '\n' ' ')"
[[ "$CHANGED" == "api/config.py api/tasks/backup_tasks.py " ]] || { echo "STOPP: oväntade ändrade filer: $CHANGED"; exit 1; }
git merge-base --is-ancestor HEAD origin/main || { echo "STOPP: main går inte att spola fram till origin/main"; exit 1; }
for f in $FILES; do
  [[ "$(git hash-object "$f")" == "$(git rev-parse "origin/main:$f")" ]] || { echo "STOPP: $f skiljer sig från origin/main"; exit 1; }
done
BEFORE="$(md5sum $FILES)"
echo "ok, filerna är identiska med origin/main"

echo "== 3. Kopia"
B="/var/tmp/vm-realign-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$B"
for f in $FILES; do cp -p --parents "$f" "$B/"; done
echo "kopia i $B"

echo "== 4. Ren kopia av main"
git checkout -q -- api/config.py api/tasks/backup_tasks.py
mv api/services/quiet_hosts.py "$B/quiet_hosts.py.moved"
git merge -q --ff-only origin/main
git branch -q --set-upstream-to=origin/main main

echo "== 5. Kontroll"
AFTER="$(md5sum $FILES)"
[[ "$BEFORE" == "$AFTER" ]] && echo "ok: koden på disk är densamma som före" || { echo "FEL: md5 skiljer sig"; echo "$AFTER"; exit 1; }
git status --short --branch | head -3
[[ -z "$(git status --porcelain --untracked-files=no)" ]] && echo "KLAR: driftkopian är ren, git pull fungerar igen." || echo "FEL: spårade filer är fortfarande ändrade"
REMOTE
