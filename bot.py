import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
import datetime
import re

# ---- Load config ----
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["token"]
CATEGORY_PAYMENTS = config["ticket_category_payments"]
CATEGORY_GENERAL = config["ticket_category_general"]
CATEGORY_ORDERS = config["ticket_category_orders"]
CATEGORY_SUPPORT = config["ticket_category_support"]
STAFF_ROLE_ID = config["staff_role_id"]
LOG_CHANNEL_ID = config["log_channel_id"]
BLACKLISTED_USERS = set(config.get("blacklisted_user_ids", []))
BLACKLISTED_WORDS = [w.lower() for w in config.get("blacklisted_words", [])]

# GIF banner (optioneel)
GIF_BANNER = "https://i.imgur.com/abcd123.gif"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Helper: detect if channel is a ticket channel (naming convention)
def is_ticket_channel(channel: discord.TextChannel):
    return channel and channel.name.startswith("ticket-")

# --------------------
# /ticketpanel slash command (embed + category buttons)
# --------------------
class CategoryButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💳 Payments", style=discord.ButtonStyle.success, custom_id="ticket_payments")
    async def payments(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "Payments", CATEGORY_PAYMENTS)

    @discord.ui.button(label="🟧 General", style=discord.ButtonStyle.primary, custom_id="ticket_general")
    async def general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "General", CATEGORY_GENERAL)

    @discord.ui.button(label="📦 Orders", style=discord.ButtonStyle.secondary, custom_id="ticket_orders")
    async def orders(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "Orders", CATEGORY_ORDERS)

    @discord.ui.button(label="🛠️ Support", style=discord.ButtonStyle.secondary, custom_id="ticket_support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "Support", CATEGORY_SUPPORT)

@bot.tree.command(name="ticketpanel", description="Send the ticket panel (staff only)")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🟧 BloxxVault Support Tickets",
        description=(
            "**Select a category below:**\n\n"
            "💳 **Payments** – vragen over betalingen of transacties.\n"
            "🟧 **General** – algemene vragen of account hulp.\n"
            "📦 **Orders** – vragen over bestellingen / leveringen.\n"
            "🛠️ **Support** – technische support of problemen.\n\n"
            "Klik op één van de knoppen om een ticket te openen."
        ),
        color=0xF59E42
    )
    embed.set_image(url=GIF_BANNER)
    await interaction.response.send_message(embed=embed, view=CategoryButtons())

# --------------------
# Create ticket
# --------------------
async def create_ticket(interaction: discord.Interaction, category_name: str, category_id: int):
    guild = interaction.guild
    user = interaction.user

    # blacklist check
    if user.id in BLACKLISTED_USERS:
        return await interaction.response.send_message("Je staat op de blacklist en kunt geen ticket openen.", ephemeral=True)

    # prevent duplicates
    existing = discord.utils.get(guild.channels, name=f"ticket-{user.id}")
    if existing:
        return await interaction.response.send_message("Je hebt al een open ticket!", ephemeral=True)

    category = guild.get_channel(category_id)
    if category is None:
        return await interaction.response.send_message("Categorie niet gevonden. Vraag een admin om te controleren.", ephemeral=True)

    # create channel
    channel = await guild.create_text_channel(
        name=f"ticket-{user.id}",
        category=category,
        topic=f"{category_name} ticket van {user} | opener_id:{user.id}"
    )

    # permissions
    await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
    await channel.set_permissions(user, read_messages=True, send_messages=True)

    # ping staff in the new ticket
    staff_role = guild.get_role(STAFF_ROLE_ID)
    staff_ping = staff_role.mention if staff_role else "@staff"

    await interaction.response.send_message(f"🎫 Ticket geopend: {channel.mention}", ephemeral=True)

    # Welcome embed in ticket
    embed = discord.Embed(
        title=f"🎫 {category_name} Ticket",
        description=(
            f"Hello {user.mention}, thank you for opening a **{category_name}** ticket.\n"
            "Help will be with you shortly — please **don't tag staff**.\n"
            "Thank you for your patience!"
        ),
        color=0xF59E42,
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Category", value=category_name, inline=True)
    embed.add_field(name="Opener", value=f"{user.mention}", inline=True)
    embed.add_field(name="Tips", value="Beschrijf je probleem duidelijk. Vermijd het gebruik van verboden woorden.", inline=False)
    embed.set_image(url=GIF_BANNER)
    # Controls view (Claim / Close / Rename)
    await channel.send(content=f"{staff_ping} — nieuw ticket geopend.", embed=embed, view=TicketControls())

    # log creation to log_channel
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(title="🆕 Ticket created",
                                  description=f"Ticket {channel.mention} ({category_name}) geopend door {user.mention}",
                                  color=0xF59E42, timestamp=datetime.datetime.utcnow())
        await log_channel.send(embed=log_embed)

# --------------------
# Ticket Controls (Claim / Close)
# --------------------
class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            return await interaction.response.send_message("Alleen staff kan tickets claimen.", ephemeral=True)

        # find opener
        opener_id = None
        m = re.match(r"ticket-(\d+)", interaction.channel.name)
        if m:
            opener_id = int(m.group(1))
        opener = interaction.guild.get_member(opener_id) if opener_id else None

        # send claim confirmation
        await interaction.response.send_message(f"📌 Ticket claimed by {interaction.user.mention}", ephemeral=False)

        # claim message to channel (includes opener mention if available)
        opener_mention = opener.mention if opener else "the user"
        await interaction.channel.send(
            f"Hello {opener_mention}, I am **{interaction.user}** from the **{interaction.guild.name} Support Team**. "
            "I'll be helping you today — please describe your issue in detail."
        )

        # log claim
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            e = discord.Embed(title="✅ Ticket claimed",
                              description=f"{interaction.channel.mention} claimed by {interaction.user.mention}",
                              color=0x2ECC71, timestamp=datetime.datetime.utcnow())
            await log_channel.send(embed=e)

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            return await interaction.response.send_message("Alleen staff kan tickets sluiten.", ephemeral=True)

        await interaction.response.send_message("Sluit-proces gestart...", ephemeral=True)
        channel = interaction.channel

        # collect messages
        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            # sanitize: include attachments info
            attachments = ""
            if msg.attachments:
                attachments = " [ATTACHMENTS: " + ", ".join(a.url for a in msg.attachments) + "]"
            messages.append(f"[{time_str}] {msg.author} : {msg.content}{attachments}")

        transcript = "\n".join(messages)
        filename = f"{channel.name}_transcript.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(transcript)

        # send transcript to log channel
        guild = interaction.guild
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"📄 Transcript van {channel.name}", file=discord.File(filename))

        # attempt DM transcript to opener
        opener_id = None
        m = re.match(r"ticket-(\d+)", channel.name)
        if m:
            opener_id = int(m.group(1))
        opener = guild.get_member(opener_id) if opener_id else None
        if opener:
            try:
                await opener.send(f"Hier is de transcript van jouw ticket {channel.name}:", file=discord.File(filename))
            except Exception:
                # can't DM
                pass

        # cleanup file
        try:
            os.remove(filename)
        except Exception:
            pass

        # send closing log and delete channel
        await channel.send("Ticket gesloten door staff. Transcript wordt opgeslagen.")
        await asyncio.sleep(1.5)
        await channel.delete()

# --------------------
# /rename command (slash)
# --------------------
@bot.tree.command(name="rename", description="Rename the current ticket channel (staff only)")
@app_commands.describe(new_name="Nieuwe kanaalnaam (zonder spaties)")
async def rename(interaction: discord.Interaction, new_name: str):
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in interaction.user.roles:
        return await interaction.response.send_message("Alleen staff kan tickets hernoemen.", ephemeral=True)

    channel = interaction.channel
    if not is_ticket_channel(channel):
        return await interaction.response.send_message("Dit commando werkt alleen in ticket-kanalen.", ephemeral=True)

    # sanitize name
    sanitized = re.sub(r"\s+", "-", new_name.lower())
    await channel.edit(name=sanitized)
    await interaction.response.send_message(f"Kanaal hernoemd naar `{sanitized}`", ephemeral=True)

    # log rename
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"✏️ {interaction.user.mention} renamed a ticket to `{sanitized}`")

# --------------------
# Anti-tag / Anti-spam-tag & blacklist words detection
# --------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    guild = message.guild
    if not guild:
        return

    staff_role = guild.get_role(STAFF_ROLE_ID)

    # If a blacklisted user tries to start typing in guild -> optional warning (only matters on create ticket)
    # Detect staff role mentions and everyone/here
    mentions_staff = False
    if message.role_mentions:
        mentions = [r.id for r in message.role_mentions]
        if STAFF_ROLE_ID in mentions:
            mentions_staff = True

    if mentions_staff or "@everyone" in message.content or "@here" in message.content:
        try:
            await message.delete()
        except Exception:
            pass
        await message.channel.send(f"⚠️ {message.author.mention} please don't tag staff or use everyone/here. They will respond when available.")
        return

    # Blacklisted words detection
    lower = message.content.lower()
    for bad in BLACKLISTED_WORDS:
        if bad in lower:
            try:
                await message.delete()
            except Exception:
                pass
            # alert staff
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                e = discord.Embed(title="🚨 Blacklisted word detected",
                                  description=f"User {message.author.mention} used a blacklisted word in {message.channel.mention}.\nWord: `{bad}`\nMessage: {message.content}",
                                  color=0xE74C3C, timestamp=datetime.datetime.utcnow())
                await log_channel.send(embed=e)
            await message.channel.send(f"⚠️ {message.author.mention} your message contained a forbidden word and was removed.")
            return

    await bot.process_commands(message)

# --------------------
# Sync tree and ready
# --------------------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
    except Exception:
        pass
    print(f"Ticket bot ingelogd als {bot.user} (tickets ready)")

bot.run(TOKEN)
