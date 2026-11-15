#!/usr/bin/env bash
# VaultMaster check-in: bär laptopen anropar servern när den är på och har ett
# nät som inte är mobilt, så att servern kan köa de backuper som är försenade.
#
# Läser VM_API och VM_CHECKIN_TOKEN från ~/.config/vaultmaster/checkin.env
# (måste ha läge 600). Gör ingenting om nätet saknas, är mobilt eller mätt.
# Misslyckas aldrig högljutt: en rad i journalen, avslutskod 0 om inget fel i
# konfigurationen, annars 1 (så att systemd visar att något är fel inställt).
set -u

ENV_FILE="${VM_CHECKIN_ENV:-$HOME/.config/vaultmaster/checkin.env}"

log() { echo "vaultmaster-checkin: $*"; }

if [ ! -f "$ENV_FILE" ]; then
  log "config saknas: $ENV_FILE"
  exit 1
fi
mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo "")
if [ "$mode" != "600" ]; then
  log "vägrar: $ENV_FILE har läge ${mode:-okänt}, ska vara 600"
  exit 1
fi

VM_API=""
VM_CHECKIN_TOKEN=""
# shellcheck disable=SC1090
. "$ENV_FILE"
if [ -z "${VM_API:-}" ] || [ -z "${VM_CHECKIN_TOKEN:-}" ]; then
  log "VM_API eller VM_CHECKIN_TOKEN saknas i $ENV_FILE"
  exit 1
fi

# Nät: NetworkManager måste rapportera full anslutning.
if ! command -v nmcli >/dev/null 2>&1; then
  log "nmcli saknas, hoppar över"
  exit 0
fi
connectivity=$(nmcli -t -g CONNECTIVITY general 2>/dev/null || echo "")
if [ "$connectivity" != "full" ]; then
  log "inget fullt nät (connectivity=${connectivity:-okänd}), hoppar över"
  exit 0
fi

# Den primära aktiva anslutningen får inte vara mobil och inte mätt.
# Primär = den som bär default route.
dev=$(ip -o route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
if [ -z "$dev" ]; then
  log "ingen default route, hoppar över"
  exit 0
fi
ctype=$(nmcli -t -g GENERAL.TYPE device show "$dev" 2>/dev/null | head -n 1)
conn=$(nmcli -t -g GENERAL.CONNECTION device show "$dev" 2>/dev/null | head -n 1)
conn_type=$(nmcli -t -g connection.type connection show "$conn" 2>/dev/null | head -n 1)
case "${ctype:-}:${conn_type:-}" in
  *gsm*|*cdma*|*bluetooth*)
    log "primär anslutning är mobil eller bluetooth (${ctype}/${conn_type}), hoppar över"
    exit 0 ;;
esac
metered=$(nmcli -t -g GENERAL.METERED device show "$dev" 2>/dev/null | head -n 1)
case "${metered:-}" in
  yes|"yes (guessed)")
    log "anslutningen är mätt (${metered}), hoppar över"
    exit 0 ;;
esac

# Anropet. Token går i header, aldrig i URL eller logg.
body=$(mktemp)
trap 'rm -f "$body"' EXIT
code=$(curl -sS -o "$body" -w '%{http_code}' \
  --connect-timeout 10 --max-time 30 \
  -X POST -H "X-Checkin-Token: ${VM_CHECKIN_TOKEN}" \
  "${VM_API%/}/servers/checkin" 2>/dev/null) || code="000"

if [ "$code" = "200" ]; then
  summary=$(tr -d '\n' < "$body" | cut -c1-300)
  log "ok http=200 $summary"
else
  log "ingen incheckning http=$code (servern nåddes inte eller avvisade)"
fi
exit 0
