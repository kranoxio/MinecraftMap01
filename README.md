# Bern Map Optimiert – Modpack

Modpack für den Minecraft-Server **„Dr ganz Kanton BERN in MC!“** (1oder0 NETWORK).
Minecraft **26.2** · Fabric Loader **0.19.5** · verwaltet mit [packwiz](https://packwiz.infra.link/).

## Für Spieler (Prism Launcher)

1. [Prism Launcher](https://prismlauncher.org/) installieren
2. Die Instanz-ZIP aus dem Discord in Prism hineinziehen
3. Starten – der Modpack lädt und aktualisiert sich bei jedem Start automatisch

## So funktioniert das Auto-Update

In der Prism-Instanz ist folgender **Pre-launch command** eingetragen
(`packwiz-installer-bootstrap.jar` liegt im Ordner `minecraft/` der Instanz):

```
"$INST_JAVA" -jar packwiz-installer-bootstrap.jar https://raw.githubusercontent.com/kranoxio/MinecraftMap01/master/pack.toml
```

## Aufbau

| Ordner / Datei | Inhalt |
|---|---|
| `pack.toml` | Name, Version, Minecraft- und Fabric-Version |
| `index.toml` | Liste aller Dateien (wird mit `packwiz refresh` erzeugt) |
| `mods/` | Eine `.pw.toml` pro Mod (Download-Link + Prüfsumme) |
| `resourcepacks/` | Eine `.pw.toml` pro Resourcepack |

Nach jeder Änderung an `mods/` oder `resourcepacks/` muss `packwiz refresh` laufen,
sonst sehen die Clients die Änderung nicht.
