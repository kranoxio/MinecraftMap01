"""
Whitelist-Bot fuer das 1oder0 NETWORK (Kanton Bern in Minecraft).

Ablauf:
  1. Ein Admin gibt einem Mitglied die Discord-Rolle "Spieler".
  2. Der Bot schreibt dem Mitglied eine Privatnachricht mit einem Knopf.
     (Sind Privatnachrichten gesperrt, erscheint der Knopf im Ersatz-Kanal.)
  3. Das Mitglied traegt seinen Minecraft-Namen ein, der Bot prueft ihn bei Mojang
     und setzt ihn per RCON auf die Whitelist.
  4. Verliert jemand die Rolle oder verlaesst den Discord, wird er wieder entfernt.

Alle Einstellungen kommen aus Umgebungsvariablen (siehe bot.env.example).
"""

import asyncio
import json
import logging
import os
import re
import struct

import aiohttp
import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
SPIELER_ROLE_ID = int(os.environ["SPIELER_ROLE_ID"])
FALLBACK_CHANNEL_ID = int(os.environ.get("FALLBACK_CHANNEL_ID") or 0)
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID") or 0)
RCON_HOST = os.environ["RCON_HOST"]
RCON_PORT = int(os.environ.get("RCON_PORT") or 25575)
RCON_PASSWORD = os.environ["RCON_PASSWORD"]
SERVER_ADDRESS = os.environ.get("SERVER_ADDRESS", "")
DATA_FILE = os.environ.get("DATA_FILE", "/data/spieler.json")

NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whitelist-bot")
data_lock = asyncio.Lock()


# --- Speicher: Discord-ID -> Minecraft-Name ---

def load_data():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


# --- RCON (Minecraft-Fernsteuerung) ---

async def rcon(command):
    reader, writer = await asyncio.wait_for(asyncio.open_connection(RCON_HOST, RCON_PORT), 10)
    try:
        async def send(request_id, packet_type, body):
            payload = body.encode("utf-8") + b"\x00\x00"
            writer.write(struct.pack("<iii", len(payload) + 8, request_id, packet_type) + payload)
            await writer.drain()

        async def receive():
            size = struct.unpack("<i", await reader.readexactly(4))[0]
            packet = await reader.readexactly(size)
            request_id, _ = struct.unpack("<ii", packet[:8])
            return request_id, packet[8:-2].decode("utf-8", errors="replace")

        await send(1, 3, RCON_PASSWORD)  # 3 = Login
        request_id, _ = await asyncio.wait_for(receive(), 10)
        if request_id == -1:
            raise RuntimeError("RCON-Passwort ist falsch")
        await send(2, 2, command)  # 2 = Befehl
        _, output = await asyncio.wait_for(receive(), 10)
        log.info("RCON '%s' -> %s", command, output)
        return output
    finally:
        writer.close()


# --- Mojang: existiert der Name, und wie ist er genau geschrieben? ---

async def mojang_name(name):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{name}") as resp:
            if resp.status == 200:
                return (await resp.json())["name"]
            if resp.status in (204, 404):
                return None
            raise RuntimeError(f"Mojang-API antwortet mit Fehler {resp.status}")


# --- Bot ---

class WhitelistBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(NameButtonView())  # Knoepfe funktionieren auch nach einem Neustart
        self.add_dynamic_items(ApproveButton, RejectButton)
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        log.info("Eingeloggt als %s", self.user)


bot = WhitelistBot()


async def send_log(text):
    if not LOG_CHANNEL_ID:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("Log-Nachricht fehlgeschlagen: %s", e)


async def get_member(user_id):
    guild = bot.get_guild(GUILD_ID)
    try:
        return guild.get_member(user_id) or await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


def has_spieler_role(member):
    return member is not None and any(r.id == SPIELER_ROLE_ID for r in member.roles)


async def register(user_id, raw_name):
    member = await get_member(user_id)
    if not has_spieler_role(member):
        return "❌ Du brauchst zuerst die Rolle **Spieler** auf dem Discord. Frag einen Admin."
    if not NAME_RE.match(raw_name):
        return ("❌ Das ist kein gültiger Minecraft-Name. Erlaubt sind 3–16 Zeichen: "
                "Buchstaben, Zahlen und `_`.")
    real_name = await mojang_name(raw_name)
    if real_name is None:
        return (f"❌ Einen Minecraft-Account **{raw_name}** gibt es nicht. "
                "Prüf die Schreibweise (Java Edition, nicht Bedrock).")

    async with data_lock:
        data = load_data()
        for uid, name in data.items():
            if name.lower() == real_name.lower() and uid != str(user_id):
                return "❌ Dieser Minecraft-Name ist schon mit einem anderen Discord-Account verknüpft."
        old_name = data.get(str(user_id))
        if old_name and old_name.lower() != real_name.lower():
            await rcon(f"whitelist remove {old_name}")
        await rcon(f"whitelist add {real_name}")
        data[str(user_id)] = real_name
        save_data(data)

    changed = f" (vorher: {old_name})" if old_name and old_name.lower() != real_name.lower() else ""
    await send_log(f"✅ {member.mention} hat **{real_name}** auf die Whitelist gesetzt{changed}.")
    address = f"\nServer-Adresse: `{SERVER_ADDRESS}`" if SERVER_ADDRESS else ""
    return f"✅ **{real_name}** ist jetzt auf der Whitelist. Viel Spass im Kanton Bern! 🏔️{address}"


async def unregister(user_id, reason):
    async with data_lock:
        data = load_data()
        name = data.pop(str(user_id), None)
        if name is None:
            return
        try:
            await rcon(f"whitelist remove {name}")
        except Exception as e:
            log.error("Konnte %s nicht von der Whitelist entfernen: %s", name, e)
            await send_log(f"⚠️ **{name}** konnte nicht entfernt werden ({e}). Bitte manuell: `whitelist remove {name}`")
            return
        save_data(data)
    await send_log(f"➖ **{name}** wurde von der Whitelist entfernt ({reason}).")


class NameModal(discord.ui.Modal, title="Minecraft-Namen eintragen"):
    name = discord.ui.TextInput(label="Dein Minecraft-Name (Java Edition)",
                                placeholder="z. B. Steve", min_length=3, max_length=16)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await register(interaction.user.id, str(self.name.value).strip())
        except Exception as e:
            log.exception("Fehler bei der Registrierung")
            message = ("⚠️ Der Minecraft-Server ist gerade nicht erreichbar. "
                       "Versuch es später nochmal oder melde dich bei einem Admin.")
            await send_log(f"⚠️ Registrierung von {interaction.user.mention} fehlgeschlagen: `{e}`")
        await interaction.followup.send(message, ephemeral=True)


class NameButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Minecraft-Namen eintragen", emoji="⛏️",
                       style=discord.ButtonStyle.success, custom_id="bern:mcname")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NameModal())


PROMPT_TEXT = ("# 🏔️ Willkommen im Kanton Bern!\n"
               "Du hast die Rolle **Spieler** bekommen. Damit du auf den Minecraft-Server kommst, "
               "trag hier deinen **Minecraft-Namen** ein – du wirst dann automatisch freigeschaltet.")


async def prompt_member(member):
    try:
        await member.send(PROMPT_TEXT, view=NameButtonView())
        log.info("Privatnachricht an %s gesendet", member)
        return
    except discord.Forbidden:
        log.info("%s hat Privatnachrichten gesperrt, nutze Ersatz-Kanal", member)
    channel = bot.get_channel(FALLBACK_CHANNEL_ID) if FALLBACK_CHANNEL_ID else None
    if channel:
        await channel.send(f"{member.mention}\n{PROMPT_TEXT}", view=NameButtonView())


# --- Freischaltung neuer Mitglieder durch das Team ---

async def check_team_permission(interaction):
    if interaction.user.guild_permissions.manage_roles:
        return True
    await interaction.response.send_message("❌ Nur Admins und Moderatoren dürfen das.", ephemeral=True)
    return False


class ApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bern:approve:(?P<uid>\d+)"):
    def __init__(self, user_id: int):
        super().__init__(discord.ui.Button(label="Freischalten", emoji="✅", style=discord.ButtonStyle.success,
                                           custom_id=f"bern:approve:{user_id}"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        if not await check_team_permission(interaction):
            return
        member = await get_member(self.user_id)
        if member is None:
            await interaction.response.edit_message(content=f"ℹ️ <@{self.user_id}> ist nicht mehr auf dem Discord.", view=None)
            return
        try:
            await member.add_roles(discord.Object(id=SPIELER_ROLE_ID), reason=f"Freigeschaltet von {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Mir fehlt das Recht **Rollen verwalten**, oder meine Rolle steht unter **⛏️ Spieler**.", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"✅ {member.mention} wurde von {interaction.user.mention} freigeschaltet.", view=None)


class RejectButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bern:reject:(?P<uid>\d+)"):
    def __init__(self, user_id: int):
        super().__init__(discord.ui.Button(label="Ablehnen (kicken)", emoji="❌", style=discord.ButtonStyle.danger,
                                           custom_id=f"bern:reject:{user_id}"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        if not await check_team_permission(interaction):
            return
        member = await get_member(self.user_id)
        if member is not None:
            try:
                await member.kick(reason=f"Abgelehnt von {interaction.user}")
            except discord.Forbidden:
                await interaction.response.send_message("❌ Mir fehlt das Recht **Mitglieder kicken**.", ephemeral=True)
                return
        await interaction.response.edit_message(
            content=f"❌ <@{self.user_id}> wurde von {interaction.user.mention} abgelehnt.", view=None)


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != GUILD_ID or member.bot:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
    if channel is None:
        return
    view = discord.ui.View(timeout=None)
    view.add_item(ApproveButton(member.id))
    view.add_item(RejectButton(member.id))
    created = int(member.created_at.timestamp())
    await channel.send(f"👋 **Neues Mitglied:** {member.mention} (`{member.name}`)\n"
                       f"Discord-Account erstellt <t:{created}:R>. Freischalten?",
                       view=view, allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id != GUILD_ID or after.bot:
        return
    had, has = has_spieler_role(before), has_spieler_role(after)
    if has and not had:
        await prompt_member(after)
    elif had and not has:
        await unregister(after.id, "Rolle Spieler entfernt")


@bot.event
async def on_raw_member_remove(payload: discord.RawMemberRemoveEvent):
    if payload.guild_id == GUILD_ID:
        await unregister(payload.user.id, "hat den Discord verlassen")


@bot.tree.command(name="minecraft", description="Minecraft-Namen für die Whitelist eintragen oder ändern")
async def minecraft_command(interaction: discord.Interaction):
    await interaction.response.send_modal(NameModal())


@bot.tree.command(name="whitelist-knopf", description="Postet den Knopf zum Eintragen des Minecraft-Namens")
@app_commands.default_permissions(manage_guild=True)
async def post_button(interaction: discord.Interaction):
    await interaction.channel.send("⛏️ **Neu hier?** Trag deinen Minecraft-Namen ein, um auf den Server zu kommen:",
                                   view=NameButtonView())
    await interaction.response.send_message("Knopf gepostet.", ephemeral=True)


@bot.tree.command(name="spielerliste", description="Zeigt, welcher Discord-Account zu welchem Minecraft-Namen gehört")
@app_commands.default_permissions(manage_roles=True)
async def player_list(interaction: discord.Interaction):
    data = load_data()
    if not data:
        await interaction.response.send_message("Noch niemand eingetragen.", ephemeral=True)
        return
    lines = [f"• <@{uid}> → **{name}**" for uid, name in sorted(data.items(), key=lambda x: x[1].lower())]
    text = f"**{len(lines)} Spieler eingetragen:**\n" + "\n".join(lines)
    await interaction.response.send_message(text[:2000], ephemeral=True)


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
