# Laptop-incheckning (plastop)

plastop är en bärbar dator som inte alltid är på nätet. Därför hämtar servern
inte längre backuper från den på fasta klockslag. I stället anropar laptopen
servern när den är påslagen och har ett nät som inte är mobilt, och servern
köar de backuper som är försenade.

## Hur det fungerar

- En timer startar `vaultmaster-checkin.sh` två minuter efter uppstart och
  därefter var 15:e minut (`Persistent=true`: en missad körning tas igen).
- Skriptet gör ingenting om NetworkManager inte rapporterar full anslutning,
  om den primära anslutningen är mobil (gsm, cdma) eller bluetooth, eller om
  den är mätt (`yes` eller `yes (guessed)`).
- Annars gör det `POST /api/v1/servers/checkin` med headern `X-Checkin-Token`.
- Servern köar varje aktivt jobb på plastop vars senaste lyckade körning är
  äldre än `checkin_min_interval_hours` (standard 10 timmar) och som inte
  redan är köat eller körs. Svaret listar vad som köades och vad som hoppades
  över och varför. Körningarna går via kön `workstation`, så ingen annan
  backup kan fastna för att laptopen saknar nät.
- Skriptet loggar en rad i journalen och misslyckas aldrig högljutt när
  laptopen är offline.

Token ger ingenting annat än detta: den hör till en server och kan bara köa
den serverns jobb.

## Installation (görs av orkestratorn, inte av skriptet)

1. En admin genererar token en gång: `POST /api/v1/servers/<id>/checkin-token`
   (visas bara då; nytt anrop ersätter den gamla; `DELETE` återkallar den).
2. På laptopen:

```
mkdir -p ~/.config/vaultmaster ~/.local/bin ~/.config/systemd/user
install -m 600 /dev/null ~/.config/vaultmaster/checkin.env
```

   Fyll i filen (läge måste vara 600, annars vägrar skriptet):

```
VM_API=https://<vaultmaster-adress>/api/v1
VM_CHECKIN_TOKEN=<token>
```

3. Kopiera `vaultmaster-checkin.sh` till `~/.local/bin/` (körbar) och
   `vaultmaster-checkin.service` samt `.timer` till `~/.config/systemd/user/`.
4. `systemctl --user daemon-reload && systemctl --user enable --now vaultmaster-checkin.timer`
5. Efter driftsättning sätter operatören plastops jobb till schedule_cron
   null, så att bara incheckningen startar dem.

## Kontroll

- `systemctl --user list-timers vaultmaster-checkin.timer`
- `journalctl --user -u vaultmaster-checkin.service -n 20`
