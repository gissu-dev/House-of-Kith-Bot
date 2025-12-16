import os
import asyncio
import random
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

# =========================
# ENV / CONFIG
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Put it in your .env file.")
if not OPENAI_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing. Put it in your .env file.")

client = OpenAI(api_key=OPENAI_KEY)

GUILD_ID = 1396177343617171598
ARCHIVE_CHANNEL_ID = 1447590881665224845
ARCHIVE_EMOJI = "\U0001F56F\uFE0F"  # candle

AI_VOICE_DIR = Path("sounds/ai_voice")
AI_VOICE_DIR.mkdir(parents=True, exist_ok=True)

CREEPY_LINES = [
    "Not every silence in this house is empty.",
    "Something in these walls remembers you better than you remember yourself.",
    "The House of Kith does not sleep. It only pretends to.",
    "Some footsteps here belong to people who never left.",
    "If you feel watched, it's only because you are.",
    "Tonight, the quiet is only pretending to be kind.",
    "The walls know more about you than any of us do.",
    "You are not the first soul this house has tried to keep.",
]

SOCIAL_ROLES = [
    "DMs Open",
    "DMs Selective",
    "DMs Closed",
    "Slow to Reply",
    "Talkative",
    "Quiet but Friendly",
]

PERSONALITY_ROLES = [
    "Soft-Spoken",
    "Overthinker",
    "Introvert",
    "Extrovert",
    "Ambivert",
    "Emotionally Unavailable",
    "Hopeless Romantic",
    "Chaotic Good",
    "Calm Presence",
    "Unhinged but Polite",
]

GAMING_ROLES = [
    "Looking for Duo",
    "Casual Player",
    "Competitive",
    "Queue Anxiety",
    "Controller Demon",
    "Keyboard Goblin",
    "AFK Most of the Time",
]

MUSIC_ROLES = [
    "Music Lover",
    "Playlist Maker",
    "Playlist Collector",
    "Rock Listener",
    "Rap / Hip-Hop Listener",
    "EDM Listener",
    "Chill / Lo-Fi Listener",
    "Emo Enjoyer",
    "Pop Listener",
]

# =========================
# DISCORD BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True


class RoleButton(discord.ui.Button):
    def __init__(self, base_name: str):
        super().__init__(
            label=base_name,
            style=discord.ButtonStyle.secondary,
            custom_id=f"role_button:{base_name}",
        )
        self.base_name = base_name

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Server-only.", ephemeral=True)

        role = discord.utils.find(
            lambda r: r.name == self.base_name or r.name.startswith(self.base_name + " "),
            guild.roles,
        )
        if role is None:
            return await interaction.response.send_message(
                f"Role matching `{self.base_name}` not found.", ephemeral=True
            )

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Self-role panel toggle")
                action = "Removed"
            else:
                await member.add_roles(role, reason="Self-role panel toggle")
                action = "Added"
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I can't edit that role.\nMove my highest role ABOVE the self-roles and enable Manage Roles.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"Discord error: `{e}`", ephemeral=True)

        await interaction.response.send_message(f"{action} **{role.name}**.", ephemeral=True)


class RoleView(discord.ui.View):
    def __init__(self, role_base_names: list[str]):
        super().__init__(timeout=None)
        for name in role_base_names:
            self.add_item(RoleButton(name))


class HouseBot(commands.Bot):
    async def setup_hook(self):
        # Load ghost game (slash + message-driven)
        await self.load_extension("cogs.ghost_game")

        # Persistent role views
        self.add_view(RoleView(SOCIAL_ROLES))
        self.add_view(RoleView(PERSONALITY_ROLES))
        self.add_view(RoleView(GAMING_ROLES))
        self.add_view(RoleView(MUSIC_ROLES))

        # Sync slash commands
        try:
            guild_obj = discord.Object(GUILD_ID)
            # Copy commands to the guild and sync (guild-only to avoid duplicates).
            self.tree.copy_global_to(guild=guild_obj)
            guild_synced = await self.tree.sync(guild=guild_obj)
            print(f"Synced {len(guild_synced)} guild slash commands.")
        except Exception as e:
            print("Slash sync failed:", e)


bot = HouseBot(command_prefix="!", intents=intents)

# =========================
# AI VOICE HELPER
# =========================
async def generate_ai_voice_line(text: str, filename: str) -> Path:
    output_path = AI_VOICE_DIR / filename

    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="onyx",
        input=text,
        response_format="wav",
        instructions=(
            "Read this like a slow, chilling horror audiobook narrator. "
            "Speak in a low, calm, unsettling tone with longer pauses."
        ),
    )
    response.stream_to_file(str(output_path))
    return output_path

# =========================
# COMMAND: !omen
# =========================
@bot.command(name="omen")
async def omen(ctx, *, text: str = None):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You must stand in the dark with me first. Join a voice channel.")
        return

    voice_channel = ctx.author.voice.channel
    line = random.choice(CREEPY_LINES) if text is None else text

    await ctx.send("\U0001F56F Giving voice to your words...")

    try:
        audio_path = await generate_ai_voice_line(line, filename=f"omen_{ctx.author.id}.wav")
    except Exception as e:
        await ctx.send(f"Voice generation failed: `{e}`")
        return

    vc: discord.VoiceClient = ctx.voice_client
    if vc and vc.channel != voice_channel:
        await vc.move_to(voice_channel)
    elif not vc:
        vc = await voice_channel.connect()

    if vc.is_playing():
        vc.stop()

    source = discord.FFmpegPCMAudio(str(audio_path))
    vc.play(source)

    await ctx.send(f"\U0001F4D6 *The House whispers:* `{line}`")

    while vc.is_playing():
        await asyncio.sleep(0.5)

    await vc.disconnect()

# =========================
# ARCHIVE REACTION HANDLER
# =========================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    if str(payload.emoji) != ARCHIVE_EMOJI:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    channel = guild.get_channel(payload.channel_id)
    if channel is None:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    if message.author.bot:
        return

    archive_channel = guild.get_channel(ARCHIVE_CHANNEL_ID)
    if archive_channel is None:
        return

    saver_member = payload.member

    embed = discord.Embed(
        description=message.content or "*[no text - maybe an image/attachment/embed]*",
        color=discord.Color.dark_theme(),
    )
    embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Original Message", value=f"[Jump to message]({message.jump_url})", inline=False)
    embed.set_footer(text=f"Saved by {saver_member.display_name}" if saver_member else "Saved to the House archive")
    embed.timestamp = message.created_at

    await archive_channel.send(embed=embed)

# =========================
# COMMAND: !setup_roles
# =========================
@bot.command(name="setup_roles")
@commands.has_permissions(manage_roles=True)
async def setup_roles(ctx: commands.Context):
    await ctx.send("**House of Kith** - choose your roles below.")

    social_embed = discord.Embed(
        title="Social Roles",
        description="**Available roles:**\n" + "\n".join(f"- {n}" for n in SOCIAL_ROLES),
        color=discord.Color.from_str("#E91E63"),
    )
    await ctx.send(embed=social_embed, view=RoleView(SOCIAL_ROLES))

    personality_embed = discord.Embed(
        title="Personality Roles",
        description="**Available roles:**\n" + "\n".join(f"- {n}" for n in PERSONALITY_ROLES),
        color=discord.Color.from_str("#F1C40F"),
    )
    await ctx.send(embed=personality_embed, view=RoleView(PERSONALITY_ROLES))

    gaming_embed = discord.Embed(
        title="Gaming Roles",
        description="**Available roles:**\n" + "\n".join(f"- {n}" for n in GAMING_ROLES),
        color=discord.Color.from_str("#71368A"),
    )
    await ctx.send(embed=gaming_embed, view=RoleView(GAMING_ROLES))

    music_embed = discord.Embed(
        title="Music Roles",
        description="**Available roles:**\n" + "\n".join(f"- {n}" for n in MUSIC_ROLES),
        color=discord.Color.from_str("#3498DB"),
    )
    await ctx.send(embed=music_embed, view=RoleView(MUSIC_ROLES))

    await ctx.send("Self-role panels created.")

@setup_roles.error
async def setup_roles_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need Manage Roles to use this.")

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"House of Kith bot logged in as {bot.user} (ID: {bot.user.id})")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print(
            "Login failed: enable the privileged intents your bot requests in the Discord Developer Portal "
            "(Server Members, Message Content), or disable them in code."
        )
    except discord.errors.LoginFailure:
        print("Login failed: invalid DISCORD_TOKEN (check .env).")
