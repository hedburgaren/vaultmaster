#!/usr/bin/env bash
# Installerar laptop-incheckningen på plastop. Körs från plastdesk när plastop är på:
#   bash /home/chrille/dev/projects/vaultmaster-backup-flow/laptop/install-on-plastop.sh
# Kräver att scripts/vm_flow_setup.py har körts (token i ~/.config/vaultmaster/plastop-checkin.env).
# Efter lyckad installation och en lyckad incheckning tas tokenfilen bort från plastdesk.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TOKEN_FILE="$HOME/.config/vaultmaster/plastop-checkin.env"
[ "$(hostname)" = "PlastDesk" ] || { echo "STOPP: körs från plastdesk"; exit 1; }
[ -f "$TOKEN_FILE" ] || { echo "STOPP: $TOKEN_FILE saknas, kör scripts/vm_flow_setup.py först"; exit 1; }
[ "$(stat -c %a "$TOKEN_FILE")" = 600 ] || { echo "STOPP: $TOKEN_FILE har fel läge"; exit 1; }
ssh -o ConnectTimeout=15 plastop true || { echo "STOPP: plastop svarar inte"; exit 1; }

echo "== filer till plastop"
ssh plastop 'mkdir -p ~/.config/vaultmaster ~/.local/bin ~/.config/systemd/user'
scp -q "$HERE/vaultmaster-checkin.sh" plastop:.local/bin/vaultmaster-checkin.sh
scp -q "$HERE/vaultmaster-checkin.service" "$HERE/vaultmaster-checkin.timer" plastop:.config/systemd/user/
ssh plastop 'chmod 755 ~/.local/bin/vaultmaster-checkin.sh && install -m 600 /dev/null ~/.config/vaultmaster/checkin.env'
ssh plastop 'cat > ~/.config/vaultmaster/checkin.env' < "$TOKEN_FILE"
ssh plastop 'chmod 600 ~/.config/vaultmaster/checkin.env'

echo "== timer"
ssh plastop 'systemctl --user daemon-reload && systemctl --user enable --now vaultmaster-checkin.timer && systemctl --user list-timers vaultmaster-checkin.timer --no-pager | head -3'

echo "== första incheckningen"
ssh plastop 'systemctl --user start vaultmaster-checkin.service; sleep 3; journalctl --user -u vaultmaster-checkin.service -n 5 --no-pager'
if ssh plastop 'journalctl --user -u vaultmaster-checkin.service -n 5 --no-pager' | grep -q 'ok http=200'; then
  rm -f "$TOKEN_FILE" && echo "tokenfilen borttagen från plastdesk"
  echo "KLART: plastop checkar in själv vid start och var 15:e minut."
else
  echo "STOPP: incheckningen gav inget svar från servern. Tokenfilen ligger kvar på plastdesk. Skicka utdata till Klådan."
  exit 1
fi
