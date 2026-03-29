import discord
from discord import app_commands
import asyncio
import json
import os
import random
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

GIVEAWAYS_FILE = "/data/giveaways.json"

def load_giveaways():
    if os.path.exists(GIVEAWAYS_FILE):
        try:
            with open(GIVEAWAYS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load giveaways: {e}")
            return {}
    return {}

def save_giveaways(data):
    os.makedirs(os.path.dirname(GIVEAWAYS_FILE), exist_ok=True)
    try:
        with open(GIVEAWAYS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save giveaways: {e}")

class GiveawayView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="Join Giveaway 🎉", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_giveaways()
        gw = data.get(str(self.message_id))
        if not gw:
            await interaction.response.send_message("❌ Giveaway already ended.", ephemeral=True)
            return
        if gw.get("required_role") and gw["required_role"] not in [r.id for r in interaction.user.roles]:
            await interaction.response.send_message("❌ You need the required role!", ephemeral=True)
            return

        entrants = gw.setdefault("entrants", [])
        if interaction.user.id in entrants:
            entrants.remove(interaction.user.id)
            msg = "✅ You have **left** the giveaway."
        else:
            entrants.append(interaction.user.id)
            msg = f"✅ You have **successfully entered** the giveaway! (Total entries: {len(entrants)})"

        save_giveaways(data)
        logging.info(f"User {interaction.user.id} joined/left giveaway {self.message_id}. Total entries now: {len(entrants)}")
        await interaction.response.send_message(msg, ephemeral=True)

async def end_giveaway(channel_id: int, message_id: int, force_end: bool = False):
    # Wait first
    if not force_end:
        data = load_giveaways()
        gw = data.get(str(message_id))
        if gw:
            remaining = gw["end_time"] - datetime.now(timezone.utc).timestamp()
            if remaining > 0:
                await asyncio.sleep(remaining)

    # Reload fresh data AFTER sleep (this fixes the "nobody entered" bug)
    data = load_giveaways()
    gw = data.get(str(message_id))
    if not gw:
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(message_id)
        entrants = gw.get("entrants", [])
        winners_count = gw.get("winners", 1)
        host = gw.get("host")

        # Edit original message
        if len(entrants) == 0:
            ended_embed = discord.Embed(title="🎉 GIVEAWAY ENDED", description="No one entered 😢", color=discord.Color.red())
        else:
            ended_embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED 🎉",
                description=f"**Prize:** {gw['prize']}\n**Winners:** {len(entrants)} entries",
                color=discord.Color.red()
            )
        await msg.edit(embed=ended_embed, view=None)

        # Winner embed
        if len(entrants) == 0:
            win_embed = discord.Embed(title="🎉 GIVEAWAY ENDED", description="No one entered the giveaway 😢", color=discord.Color.red())
        else:
            winners = random.sample(entrants, k=min(winners_count, len(entrants)))
            winner_mentions = " ".join(f"<@{w}>" for w in winners)
            win_embed = discord.Embed(title="🎉 **GIVEAWAY WINNER(S)!** 🎉", color=discord.Color.gold())
            win_embed.add_field(name="Prize", value=gw['prize'], inline=False)
            win_embed.add_field(name="Winner(s)", value=winner_mentions, inline=False)
            win_embed.add_field(name="Claim Your Prize", value=f"**Please DM the host <@{host}> to claim your prize!**", inline=False)
            win_embed.set_footer(text=f"Hosted by <@{host}> • {len(entrants)} total entries")
            await channel.send(f"🎉 **CONGRATULATIONS** {winner_mentions}!")

        await channel.send(embed=win_embed)

        data.pop(str(message_id), None)
        save_giveaways(data)

    except Exception as e:
        logging.error(f"Error ending giveaway {message_id}: {e}")

@bot.event
async def on_ready():
    print(f"🚀 Advanced Giveaway Bot online as {bot.user}")

    data = load_giveaways()
    for mid, gw in list(data.items()):
        channel = bot.get_channel(gw.get("channel_id"))
        if not channel:
            data.pop(mid, None)
            continue
        try:
            msg = await channel.fetch_message(int(mid))
            await msg.edit(view=GiveawayView(int(mid)))

            remaining = gw["end_time"] - datetime.now(timezone.utc).timestamp()
            if remaining > 0:
                bot.loop.create_task(end_giveaway(gw["channel_id"], int(mid), force_end=False))
            else:
                bot.loop.create_task(end_giveaway(gw["channel_id"], int(mid), force_end=True))
        except:
            data.pop(mid, None)

    save_giveaways(data)
    await tree.sync()
    print("✅ All slash commands synced & active giveaways restored!")

@tree.command(name="gstart", description="Start a new giveaway")
@app_commands.describe(
    duration="Time (e.g. 1h, 30m, 2d)",
    prize="What you're giving away",
    winners="Number of winners (1-10)",
    role="Role required to enter (optional)"
)
@app_commands.default_permissions(manage_guild=True)
async def gstart(interaction: discord.Interaction, duration: str, prize: str, winners: int = 1, role: discord.Role = None):
    unit = duration[-1].lower()
    if unit not in "smhd" or not duration[:-1].isdigit():
        await interaction.response.send_message("❌ Invalid duration! Examples: `30s`, `10m`, `2h`, `1d`", ephemeral=True)
        return

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = int(duration[:-1]) * multipliers[unit]
    end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    embed = discord.Embed(
        title="🎉 **NEW GIVEAWAY** 🎉",
        description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end_time.timestamp())}:R>",
        color=discord.Color.gold()
    )
    if role:
        embed.add_field(name="Required Role", value=role.mention)
    embed.set_footer(text=f"Hosted by {interaction.user.display_name} • Message ID: {interaction.id} (copy for reroll)")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()

    data = load_giveaways()
    data[str(msg.id)] = {
        "prize": prize,
        "winners": max(1, min(10, winners)),
        "required_role": role.id if role else None,
        "host": interaction.user.id,
        "channel_id": interaction.channel.id,
        "end_time": end_time.timestamp(),
        "entrants": []
    }
    save_giveaways(data)

    await msg.edit(view=GiveawayView(msg.id))
    bot.loop.create_task(end_giveaway(interaction.channel.id, msg.id, force_end=False))

    await interaction.followup.send(f"✅ Giveaway started! Message ID: `{msg.id}`", ephemeral=True)

# (glist, gend, greroll are unchanged – just copy them from your previous file if you want, they are the same)

@tree.command(name="glist", description="List all active giveaways")
@app_commands.default_permissions(manage_guild=True)
async def glist(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_giveaways()
    if not data:
        await interaction.followup.send("No active giveaways right now.", ephemeral=True)
        return

    lines = []
    now = datetime.now(timezone.utc).timestamp()
    for mid, gw in data.items():
        remaining = gw["end_time"] - now
        if remaining < 0:
            continue
        time_left = f"<t:{int(gw['end_time'])}:R>"
        lines.append(f"**ID:** `{mid}`\n**Prize:** {gw['prize']}\n**Ends:** {time_left}\n**Entries:** {len(gw.get('entrants', []))}\n")

    embed = discord.Embed(title="🎉 Active Giveaways", description="\n".join(lines) or "None", color=discord.Color.gold())
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="gend", description="End a giveaway early")
@app_commands.describe(message_id="Message ID of the giveaway")
@app_commands.default_permissions(manage_guild=True)
async def gend(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    data = load_giveaways()
    if message_id not in data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return
    await end_giveaway(interaction.channel.id, int(message_id), force_end=True)
    await interaction.followup.send("✅ Giveaway ended early!", ephemeral=True)

@tree.command(name="greroll", description="Reroll a finished giveaway")
@app_commands.describe(message_id="Message ID of the ended giveaway")
@app_commands.default_permissions(manage_guild=True)
async def greroll(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    data = load_giveaways()
    gw = data.get(message_id)
    if not gw:
        await interaction.followup.send("❌ Giveaway not found or already cleaned.", ephemeral=True)
        return
    entrants = gw.get("entrants", [])
    if not entrants:
        await interaction.followup.send("❌ No entries to reroll.", ephemeral=True)
        return
    winners = random.sample(entrants, k=min(gw.get("winners", 1), len(entrants)))
    mentions = " ".join(f"<@{w}>" for w in winners)
    await interaction.channel.send(f"🔄 **REROLL!** New winner(s): {mentions} — **{gw['prize']}**")
    await interaction.followup.send("✅ Reroll complete!", ephemeral=True)

token = os.getenv("TOKEN")
if not token:
    print("❌ TOKEN environment variable missing!")
    exit(1)
bot.run(token)
