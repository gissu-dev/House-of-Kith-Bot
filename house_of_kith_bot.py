import os
import sys
import subprocess
import asyncio
import random
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone

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
BOT_DEVELOPER = os.getenv("BOT_DEVELOPER", "Airex")
BOT_CREATED_ON = os.getenv("BOT_CREATED_ON", "Unknown")
BOT_VERSION = os.getenv("BOT_VERSION", "1.0.0")
BOT_STATUS_CHANNEL_ID = int(os.getenv("BOT_STATUS_CHANNEL_ID", "0"))
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

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
BASE_DIR = Path(__file__).resolve().parent
STATUS_MESSAGE_ID_FILE = BASE_DIR / "data" / "bot_status_message_id.txt"
FOLLOWUP_WINDOW_SECONDS = 30.0
ai_followup_windows: dict[tuple[int, int, int], float] = {}

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
        # Load tarot readings
        await self.load_extension("cogs.tarot")
        # Keep these cogs in the repo, but do not load them.
        print("Skipping cogs.ghost_game by config.")
        print("Skipping cogs.megamind by config.")
        # Load Valorant stats/party tracker only if API key is present
        if os.getenv("VAL_API_KEY"):
            await self.load_extension("cogs.valorant")
        else:
            print("Skipping Valorant cog: VAL_API_KEY not set.")

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

    async def close(self):
        # Best-effort offline mark during graceful shutdown.
        try:
            await update_status_message(is_online=False)
        except Exception as e:
            print(f"Offline status update failed: {e}")
        await super().close()


bot = HouseBot(command_prefix="!", intents=intents)

STATUS_ON = "\U0001F7E2"   # green circle
STATUS_OFF = "\U0001F534"  # red circle


def _status_message_text(is_online: bool) -> str:
    state_emoji = STATUS_ON if is_online else STATUS_OFF
    state_text = "ONLINE" if is_online else "OFFLINE"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"**Bot Status:** {state_emoji} `{state_text}`\nLast updated: `{now_utc}`"


def _load_status_message_id() -> int:
    try:
        if STATUS_MESSAGE_ID_FILE.exists():
            return int(STATUS_MESSAGE_ID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    return 0


def _save_status_message_id(message_id: int) -> None:
    STATUS_MESSAGE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_MESSAGE_ID_FILE.write_text(str(message_id), encoding="utf-8")


async def update_status_message(is_online: bool) -> None:
    if not BOT_STATUS_CHANNEL_ID:
        return

    channel = bot.get_channel(BOT_STATUS_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(BOT_STATUS_CHANNEL_ID)
        except Exception:
            print(f"Status update skipped: cannot access channel {BOT_STATUS_CHANNEL_ID}.")
            return

    if not isinstance(channel, discord.TextChannel):
        print(f"Status update skipped: channel {BOT_STATUS_CHANNEL_ID} is not a text channel.")
        return

    content = _status_message_text(is_online)
    message_id = _load_status_message_id()
    if message_id:
        try:
            # Edit by id directly so we do not rely on message-history fetch.
            msg = channel.get_partial_message(message_id)
            await msg.edit(content=content)
            return
        except Exception:
            pass

    try:
        msg = await channel.send(content)
        _save_status_message_id(msg.id)
    except Exception as e:
        print(f"Status message send failed: {e}")

def _followup_key(guild_id: int, channel_id: int, user_id: int) -> tuple[int, int, int]:
    return (guild_id, channel_id, user_id)


def _open_followup_window(guild_id: int, channel_id: int, user_id: int) -> None:
    key = _followup_key(guild_id, channel_id, user_id)
    ai_followup_windows[key] = time.monotonic() + FOLLOWUP_WINDOW_SECONDS


def _has_followup_window(guild_id: int, channel_id: int, user_id: int) -> bool:
    key = _followup_key(guild_id, channel_id, user_id)
    expires_at = ai_followup_windows.get(key)
    if expires_at is None:
        return False
    if time.monotonic() > expires_at:
        ai_followup_windows.pop(key, None)
        return False
    return True


async def answer_bot_question(question: str) -> str:
    def _generate() -> str:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are the House of Kith Discord bot assistant. "
                        "Answer only questions about this bot: its commands, setup, features, status, behavior, and internal code. "
                        "You may discuss implementation details, architecture, functions, files, and logic for the bot itself. "
                        "If the user asks about anything else, say you only answer House of Kith bot questions."
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_output_tokens=180,
        )
        text = (response.output_text or "").strip()
        if not text:
            return "I can only answer questions about the House of Kith bot."
        return text

    try:
        return await asyncio.to_thread(_generate)
    except Exception:
        return "I can only answer questions about the House of Kith bot right now."


def runtime_status_answer(question: str) -> str | None:
    q = question.lower()
    status_triggers = (
        "which cogs",
        "what cogs",
        "which commands",
        "what commands",
        "what works",
        "working",
        "will it work",
        "can i use",
    )
    if not any(trigger in q for trigger in status_triggers):
        return None

    loaded_cogs = sorted(name.removeprefix("cogs.") for name in bot.extensions.keys())
    prefix_commands = sorted(c.name for c in bot.commands)
    slash_commands = sorted(cmd.qualified_name for cmd in bot.tree.get_commands())

    cogs_text = ", ".join(loaded_cogs) if loaded_cogs else "none"
    prefix_text = ", ".join(f"!{name}" for name in prefix_commands) if prefix_commands else "none"
    slash_text = ", ".join(f"/{name}" for name in slash_commands) if slash_commands else "none"

    return (
        "Current runtime status:\n"
        f"- Loaded cogs: {cogs_text}\n"
        f"- Prefix commands: {prefix_text}\n"
        f"- Slash commands: {slash_text}\n"
        "Ghost Game and Megamind are currently not loaded, so their commands are disabled."
    )

# =========================
# COMMAND: !kith wake up
# =========================
def _diag_line(ok: bool, label: str, detail: str) -> str:
    icon = "\u2705" if ok else "\u26A0\uFE0F"
    return f"{icon} **{label}:** {detail}"


@bot.command(name="kith")
async def kith(ctx: commands.Context, *, phrase: str | None = None):
    normalized = (phrase or "").strip().lower()
    if normalized != "wake up":
        await ctx.send("Use `!kith wake up` to run diagnostics.")
        return

    guild = ctx.guild
    current_channel = ctx.channel

    checks: list[str] = []
    checks.append(_diag_line(bool(bot.user), "Login", f"Online as `{bot.user}`" if bot.user else "Not logged in"))
    checks.append(_diag_line(bot.is_ready(), "Ready State", "Bot is ready" if bot.is_ready() else "Still starting"))
    checks.append(_diag_line(bot.latency < 1.0, "Gateway Ping", f"{round(bot.latency * 1000)} ms"))

    checks.append(_diag_line(bool(TOKEN), "DISCORD_TOKEN", "Loaded from .env" if TOKEN else "Missing"))
    checks.append(_diag_line(bool(OPENAI_KEY), "OPENAI_API_KEY", "Loaded from .env" if OPENAI_KEY else "Missing"))

    checks.append(_diag_line(intents.members, "Members Intent", "Enabled in code" if intents.members else "Disabled in code"))
    checks.append(
        _diag_line(
            intents.message_content,
            "Message Content Intent",
            "Enabled in code" if intents.message_content else "Disabled in code",
        )
    )

    target_guild = bot.get_guild(GUILD_ID)
    checks.append(
        _diag_line(
            target_guild is not None,
            "Configured Guild",
            f"Found `{target_guild.name}`" if target_guild else f"Cannot access guild `{GUILD_ID}`",
        )
    )

    target_archive = bot.get_channel(ARCHIVE_CHANNEL_ID)
    checks.append(
        _diag_line(
            target_archive is not None,
            "Archive Channel",
            f"Found `<#{ARCHIVE_CHANNEL_ID}>`" if target_archive else f"Cannot access channel `{ARCHIVE_CHANNEL_ID}`",
        )
    )

    if guild and isinstance(current_channel, discord.abc.GuildChannel):
        me = guild.me
        perms = current_channel.permissions_for(me) if me else None
        can_send = bool(perms and perms.send_messages)
        can_embed = bool(perms and perms.embed_links)
        checks.append(_diag_line(can_send, "Send Messages", "Allowed here" if can_send else "Missing permission in this channel"))
        checks.append(_diag_line(can_embed, "Embed Links", "Allowed here" if can_embed else "Missing permission in this channel"))

    loaded_cogs = sorted(bot.extensions.keys())
    required_cogs = ["cogs.tarot"]
    missing_required = [name for name in required_cogs if name not in loaded_cogs]
    checks.append(
        _diag_line(
            not missing_required,
            "Required Cogs",
            "All loaded" if not missing_required else f"Missing: {', '.join(missing_required)}",
        )
    )

    valorant_expected = bool(os.getenv("VAL_API_KEY"))
    valorant_loaded = "cogs.valorant" in loaded_cogs
    if valorant_expected:
        checks.append(_diag_line(valorant_loaded, "Valorant Cog", "Loaded" if valorant_loaded else "Expected but not loaded"))
    else:
        checks.append(_diag_line(True, "Valorant Cog", "Skipped (VAL_API_KEY not set)"))

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    feature_checks: list[str] = []
    feature_checks.append(_diag_line("kith" in bot.all_commands, "Diagnostics", "Command `!kith wake up` is available"))
    feature_checks.append(_diag_line("about" in bot.all_commands, "About", "Command `!about` is available"))
    feature_checks.append(_diag_line("restart" in bot.all_commands and BOT_OWNER_ID > 0, "Restart", "Owner-only `!restart` is enabled"))
    feature_checks.append(
        _diag_line(
            bool(OPENAI_KEY),
            "AI Assistant",
            f"Available for {int(FOLLOWUP_WINDOW_SECONDS)}s follow-up window" if OPENAI_KEY else "Missing OPENAI_API_KEY",
        )
    )
    feature_checks.append(_diag_line("omen" in bot.all_commands and ffmpeg_ok, "Voice Omen", "Ready" if ffmpeg_ok else "FFmpeg not found"))
    feature_checks.append(_diag_line("setup_roles" in bot.all_commands, "Role Panels", "Setup command is available"))
    feature_checks.append(_diag_line(target_archive is not None, "Archive Reaction", "Ready" if target_archive else "Archive channel unavailable"))
    feature_checks.append(_diag_line("cogs.tarot" in loaded_cogs, "Tarot", "Loaded"))
    feature_checks.append(
        _diag_line(
            not valorant_expected or valorant_loaded,
            "Valorant",
            "Loaded" if valorant_loaded else ("Disabled (no VAL_API_KEY)" if not valorant_expected else "Expected but not loaded"),
        )
    )
    feature_checks.append(_diag_line(False, "Ghost Game", "Disabled by config"))
    feature_checks.append(_diag_line(False, "Megamind", "Disabled by config"))

    embed = discord.Embed(
        title="House of Kith Diagnostics",
        description="\n".join(checks),
        color=discord.Color.from_str("#2ECC71"),
    )
    embed.add_field(name="Feature Status", value="\n".join(feature_checks), inline=False)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.send(embed=embed)
    guild_id = ctx.guild.id if ctx.guild else 0
    _open_followup_window(guild_id, ctx.channel.id, ctx.author.id)
    await ctx.send(
        f"Ask me bot questions in this channel for the next {int(FOLLOWUP_WINDOW_SECONDS)} seconds."
    )

# =========================
# COMMAND: !about
# =========================
@bot.command(name="about")
async def about(ctx: commands.Context):
    uptime = "unknown"
    if bot.user:
        uptime = "online"

    embed = discord.Embed(
        title="About House of Kith Bot",
        color=discord.Color.from_str("#3498DB"),
    )
    embed.add_field(name="Developer", value=BOT_DEVELOPER, inline=False)
    embed.add_field(name="Created On", value=BOT_CREATED_ON, inline=False)
    embed.add_field(name="Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Status", value=uptime, inline=True)
    embed.add_field(name="Library", value=f"discord.py {discord.__version__}", inline=True)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.send(embed=embed)


# =========================
# COMMAND: !restart (owner only)
# =========================
@bot.command(name="restart")
async def restart(ctx: commands.Context):
    if not BOT_OWNER_ID:
        await ctx.send("`BOT_OWNER_ID` is not set in .env.")
        return
    if ctx.author.id != BOT_OWNER_ID:
        await ctx.send("You are not allowed to use this command.")
        return

    await ctx.send("Restart requested. Step 1/3: authorized.")
    await asyncio.sleep(0.3)

    await ctx.send("Step 2/3: launching replacement process...")
    script_path = str(Path(__file__).resolve())
    argv = [sys.executable, script_path, *sys.argv[1:]]
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )

        new_proc = subprocess.Popen(
            argv,
            cwd=str(BASE_DIR),
            creationflags=creationflags,
        )
        await ctx.send(f"Step 3/3: replacement started (PID {new_proc.pid}). Shutting this instance down...")
        await asyncio.sleep(0.5)
        await bot.close()
        os._exit(0)
    except Exception as e:
        await ctx.send(f"Restart failed: `{e}`")

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
    try:
        import nacl  # noqa: F401  # required by discord voice
    except Exception:
        await ctx.send("`!omen` is unavailable: PyNaCl is missing. Install dependencies and restart the bot.")
        return
    if shutil.which("ffmpeg") is None:
        await ctx.send("`!omen` is unavailable: FFmpeg is not installed or not on PATH.")
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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if message.content.startswith(str(bot.command_prefix)):
        return

    guild_id = message.guild.id if message.guild else 0
    if not _has_followup_window(guild_id, message.channel.id, message.author.id):
        return

    question = message.content.strip()
    if not question:
        return

    status_reply = runtime_status_answer(question)
    if status_reply:
        _open_followup_window(guild_id, message.channel.id, message.author.id)
        await message.channel.send(status_reply)
        return

    answer = await answer_bot_question(question)
    _open_followup_window(guild_id, message.channel.id, message.author.id)
    await message.channel.send(answer)
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
    await update_status_message(is_online=True)


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
