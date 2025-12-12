import discord
from discord.ext import commands
import json
import os

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
CATEGORY_ID = config["ticket_category_id"]
STAFF_ROLE_ID = config["staff_role_id"]
LOG_CHANNEL_ID = config["log_channel_id"]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# Panel command (create ticket button)
@bot.command()
@commands.has_permissions(administrator=True)
async def ticketpanel(ctx):
    embed = discord.Embed(
        title="🟧 BloxxVault Support",
        description="Klik op de knop hieronder om een ticket te openen.",
        color=0xf59e42
    )

    view = TicketButton()
    await ctx.send(embed=embed, view=view)


# Ticket button class
class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_ID)

        # Check if user already has a ticket
        existing = discord.utils.get(guild.channels, name=f"ticket-{interaction.user.id}")
        if existing:
            return await interaction.response.send_message(
                "Je hebt al een open ticket!", ephemeral=True
            )

        # Create channel
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.id}",
            category=category,
            topic=f"Ticket van {interaction.user}"
        )

        await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        await channel.set_permissions(guild.default_role, read_messages=False)

        await interaction.response.send_message(
            f"🎫 Ticket geopend: {channel.mention}", ephemeral=True
        )

        embed = discord.Embed(
            title="🎫 Ticket geopend",
            description="Onze staff helpt je zo snel mogelijk verder.\n\n"
                        "**Gebruik de knoppen hieronder om het ticket te beheren.**",
            color=0xf59e42
        )

        await channel.send(
            content=f"{interaction.user.mention} welkom!",
            embed=embed,
            view=ManageTicket()
        )


# Management buttons
class ManageTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Sluiten", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            return await interaction.response.send_message(
                "Alleen staff kan tickets sluiten.", ephemeral=True
            )

        # Make transcript
        messages = []
        channel = interaction.channel

        async for msg in channel.history(limit=None, oldest_first=True):
            messages.append(f"{msg.author}: {msg.content}")

        transcript = "\n".join(messages)

        # Save file
        file_name = f"transcript_{channel.name}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(transcript)

        # Send to log channel
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        await log_channel.send(
            f"📄 Transcript van {channel.name}",
            file=discord.File(file_name)
        )

        os.remove(file_name)

        await interaction.response.send_message("Ticket wordt gesloten...")
        await channel.delete()


# Bot ready event
@bot.event
async def on_ready():
    print(f"Bot ingelogd als {bot.user}")


bot.run(TOKEN)
