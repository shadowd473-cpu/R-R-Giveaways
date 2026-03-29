import discord
from discord import app_commands
import asyncio
import json
import os
import random
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Railway persistent storage
GIVEAWAYS_FILE = "/data/giveaways.json"

def load_giveaways():
    if os.path.exists(GIVEAWAYS_FILE):
        try:
            with open(GIVEAWAYS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_giveaways(data):
    os.makedirs(os.path.dirname(GIVEAWAYS_FILE), exist_ok=True)
    with open(GIVEAWAYS_FILE, "w") as f:
        json.dump(data, f, indent=4)

class GiveawayView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="Join Giveaway 🎉", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_giveaways()
        gw = data.get(str(self.message_id))
        if not gw:
            await interaction.response.send_message("❌ This giveaway has already ended.", ephemeral=True)
            return

        if gw.get("required_role") and gw["required_role"] not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("❌ You need the required role to enter!", ephemeral=True)
            return

        entrants = gw.setdefault("entrants", [])
        if interaction.user.id in entrants:
            entrants.remove(interaction.user.id)
            await interaction.response.send_message("✅ You left the giveaway.", ephemeral=True)
        else:
            entrants.append(interaction.user.id)
            await interaction.response.send_message("✅ You entered the giveaway!", ephemeral=True)

        save_giveaways(data)

async def end_giveaway(channel_id: int, message_id: int):
    await asyncio.sleep(2)  # small safety delay
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

        if len(entrants) == 0:
            embed = discord.Embed(title="🎉 GIVEAWAY ENDED", description="No one entered 😢", color=discord.Color.red())
            await msg.edit(embed=embed, view=None)
        else:
            winners = random.sample(entrants, k=min(winners_count, len(entrants)))
            winner_mentions = " ".join(f"<@{w}>" for w in winners)
            embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED 🎉",
                description=f"**Prize:** {gw['prize']}\n**Winners:** {winner_mentions}",
                color=discord.Color.red()
            )
            await msg.edit(embed=embed, view=None)
            await channel.send(f"🎉 **CONGRATULATIONS** {winner_mentions}! You won **{gw['prize']}**!")

        data.pop(str(message_id), None)
        save_giveaways(data)
    except:
        pass  # message already deleted or channel gone

@bot.event
async def on_ready():
    print(f"🚀 Super Advanced Giveaway Bot online as {bot.user}")
    await tree.sync()
    print("✅ Slash commands synced globally!")

@tree.command(name="giveaway", description="Create, end, or manage giveaways")
@app_commands.describe(
    action="start / end",
    duration="e.g. 1h, 30m, 2d (only for start)",
    prize="Prize name (only for start)",
    winners="Number of winners 1-10 (default 1)",
    role="Role required to enter (optional)"
)
@app_commands.default_permissions(manage_guild=True)
async def giveaway_cmd(
    interaction: discord.Interaction,
    action: str,
    duration: str = None,
    prize: str = None,
    winners: int = 1,
    role: discord.Role = None
):
    await interaction.response.defer(ephemeral=True)
    data = load_giveaways()

    if action.lower() == "start":
        if not duration or not prize:
            await interaction.followup.send("❌ Correct usage: `/giveaway action:start duration:1h prize:Nitro winners:1`", ephemeral=True)
            return

        # Parse time
        unit = duration[-1].lower()
        if unit not in "smhd" or not duration[:-1].isdigit():
            await interaction.followup.send("❌ Invalid duration! Use: 30s, 10m, 2h, 1d", ephemeral=True)
            return

        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        seconds = int(duration[:-1]) * multipliers[unit]
        end_time = datetime.utcnow() + timedelta(seconds=seconds)

        embed = discord.Embed(
            title="🎉 **NEW GIVEAWAY** 🎉",
            description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end_time.timestamp())}:R>",
            color=discord.Color.gold()
        )
        if role:
            embed.add_field(name="Required Role", value=role.mention)
        embed.set_footer(text=f"Hosted by {interaction.user.display_name}")

        view = GiveawayView(0)  # temp
        await interaction.followup.send(embed=embed, view=view)
        msg = await interaction.original_response()

        # Save data
        giveaway_data = {
            "prize": prize,
            "winners": max(1, min(10, winners)),
            "required_role": role.id if role else None,
            "host": interaction.user.id,
            "channel_id": interaction.channel.id,
            "end_time": end_time.timestamp(),
            "entrants": []
        }
        data[str(msg.id)] = giveaway_data
        save_giveaways(data)

        # Attach real view
        await msg.edit(view=GiveawayView(msg.id))

        # Schedule auto-end
        bot.loop.create_task(end_giveaway(interaction.channel.id, msg.id))

        await interaction.followup.send(f"✅ Giveaway started! Message ID: `{msg.id}`", ephemeral=True)

    elif action.lower() == "end":
        for mid in sorted(data.keys(), reverse=True):
            if data[mid]["channel_id"] == interaction.channel.id:
                await end_giveaway(interaction.channel.id, int(mid))
                await interaction.followup.send("✅ Giveaway ended early!", ephemeral=True)
                return
        await interaction.followup.send("❌ No active giveaway in this channel.", ephemeral=True)

@tree.command(name="greroll", description="Reroll any giveaway (give message ID)")
@app_commands.describe(message_id="The message ID of the ended giveaway")
@app_commands.default_permissions(manage_guild=True)
async def greroll(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    data = load_giveaways()
    gw = data.get(message_id)
    if not gw:
        await interaction.followup.send("❌ Giveaway not found or already cleaned up.", ephemeral=True)
        return

    entrants = gw.get("entrants", [])
    if not entrants:
        await interaction.followup.send("❌ No one entered to reroll.", ephemeral=True)
        return

    winners = random.sample(entrants, k=min(gw.get("winners", 1), len(entrants)))
    winner_mentions = " ".join(f"<@{w}>" for w in winners)

    await interaction.channel.send(f"🔄 **REROLL!** New winner(s): {winner_mentions} — **{gw['prize']}**")
    await interaction.followup.send("✅ Reroll done!", ephemeral=True)

bot.run(os.getenv("TOKEN"))
