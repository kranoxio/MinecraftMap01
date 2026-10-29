# Whitelist-Bot

Bekommt jemand auf Discord die Rolle **⛏️ Spieler**, schreibt ihm dieser Bot eine Privatnachricht
mit einem Knopf. Dort trägt er seinen Minecraft-Namen ein – der Bot prüft ihn bei Mojang und setzt
ihn per RCON auf die Whitelist. Wird die Rolle entfernt oder verlässt jemand den Discord, fliegt
er automatisch wieder von der Whitelist.

| Befehl | Wer | Was |
|---|---|---|
| `/minecraft` | Spieler | Minecraft-Namen eintragen oder ändern |
| `/whitelist-knopf` | Admins | Postet den Eintragen-Knopf im aktuellen Kanal |

## Installation (Docker, z. B. UGREEN NAS)

1. Diesen Ordner aufs NAS kopieren
2. `bot.env.example` zu `bot.env` kopieren und ausfüllen
3. In der `server.properties` RCON einschalten (`enable-rcon=true`, `rcon.password=...`) –
   Port 25575 **nicht** im Router freigeben
4. `docker compose up -d` (oder in der Docker-App als Projekt anlegen)

Gespeicherte Zuordnungen (Discord ↔ Minecraft) liegen in `data/spieler.json`.
