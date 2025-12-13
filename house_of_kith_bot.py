import os
import asyncio
from pathlib import Path

import discord
from discord.ext import commands
from openai import OpenAI


# ========== OPENAI CLIENT ==========

# Put your real OpenAI key here
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


# ========== CONFIG ==========

# Put your real Discord bot token here
TOKEN = os.environ["DISCORD_TOKEN"]

# Your real IDs (keep as-is unless your server/channel changed)
GUILD_ID = 1396177343617171598           # your server ID
ARCHIVE_CHANNEL_ID = 1447590881665224845 # your archive / lore channel ID

# Emoji that activates archive saving
ARCHIVE_EMOJI = "🕯️"

# Folder for AI voice audio files
AI_VOICE_DIR = Path("sounds/ai_voice")
AI_VOICE_DIR.mkdir(parents=True, exist_ok=True)

# Creepy lines for !omen command
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


# ========== SELF-ROLE CONFIG (BASE ROLE NAMES) ==========

# IMPORTANT:
# These are the *base names*. If your real Discord role is "DMs Open 💬",
# leave this as "DMs Open" and the bot will still find it.

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


# ========== DISCORD BOT SETUP ==========

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ========== UI: BUTTONS & VIEWS FOR SELF-ROLES ==========

class RoleButton(discord.ui.Button):
    def __init__(self, base_name: str):
        super().__init__(
            label=base_name,
            style=discord.ButtonStyle.secondary,
            custom_id=f"role_button:{base_name}"  # needed for persistent views
        )
        self.base_name = base_name

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This only works inside a server.", ephemeral=True
            )
            return

        # Find the matching role
        role = discord.utils.find(
            lambda r: r.name == self.base_name or r.name.startswith(self.base_name + " "),
            guild.roles
        )

        if role is None:
            await interaction.response.send_message(
                f"Role matching `{self.base_name}` not found.",
                ephemeral=True,
            )
            return

        member = interaction.user

        try:
            # Toggle the role
            if role in member.roles:
                await member.remove_roles(role, reason="Self-role panel toggle")
                action = "removed"
            else:
                await member.add_roles(role, reason="Self-role panel toggle")
                action = "added"

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I do not have permission to edit this role.\n"
                "Move my highest role ABOVE all self-roles and enable **Manage Roles**.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Discord error while editing your roles: `{e}`",
                ephemeral=True,
            )
            return

        # Success message
        await interaction.response.send_message(
            f"{action.title()} **{role.name}**.",
            ephemeral=True
        )


class RoleView(discord.ui.View):
    def __init__(self, role_base_names: list[str]):
        super().__init__(timeout=None)  # stays active until bot restarts
        for name in role_base_names:
            self.add_item(RoleButton(name))


# ========== AI VOICE HELPER ==========

async def generate_ai_voice_line(text: str, filename: str = "omen.wav") -> Path:
    output_path = AI_VOICE_DIR / filename

    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="onyx",
        input=text,
        response_format="wav",
        instructions=(
            "Read this like a slow, chilling horror audiobook narrator. "
            "Speak in a low, calm, unsettling tone with longer pauses, "
            "like you're telling a ghost story in a dark room."
        ),
    )

    response.stream_to_file(str(output_path))
    return output_path


# ========== COMMAND: !omen (random OR custom) ==========

@bot.command(name="omen")
async def omen(ctx, *, text: str = None):
    """
    If no text is provided: speaks a RANDOM creepy line.
    If text IS provided: speaks your CUSTOM text.

    Usage:
      !omen
      !omen something spooky
    """
    import random

    # Must be in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You must stand in the dark with me first. Join a voice channel. 🕯️")
        return

    voice_channel = ctx.author.voice.channel

    # Decide what to say
    if text is None:
        line = random.choice(CREEPY_LINES)
        await ctx.send("🕯️ Summoning a voice from the House...")
    else:
        line = text
        await ctx.send("🕯️ Giving voice to your words...")

    # Generate the AI narrator voice
    try:
        audio_path = await generate_ai_voice_line(
            line,
            filename=f"omen_{ctx.author.id}.wav"
        )
    except Exception as e:
        await ctx.send(f"Something went wrong calling the voice in the walls: `{e}`")
        return

    # Connect or move bot to voice
    vc: discord.VoiceClient = ctx.voice_client
    if vc and vc.channel != voice_channel:
        await vc.move_to(voice_channel)
    elif not vc:
        vc = await voice_channel.connect()

    # Play the audio
    if vc.is_playing():
        vc.stop()

    source = discord.FFmpegPCMAudio(str(audio_path))
    vc.play(source)

    # Send what was spoken in chat
    await ctx.send(f"📖 *The House whispers:* `{line}`")

    # Disconnect after speaking
    while vc.is_playing():
        await asyncio.sleep(1)

    await vc.disconnect()


# ========== ARCHIVE REACTION HANDLER (🕯️) ==========

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """
    Archive a message when someone reacts with ARCHIVE_EMOJI in your server.
    """

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
        description=message.content or "*[no text – maybe an image, attachment, or embed]*",
        color=discord.Color.dark_theme()
    )

    embed.set_author(
        name=str(message.author),
        icon_url=message.author.display_avatar.url
    )

    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(
        name="Original Message",
        value=f"[Jump to message]({message.jump_url})",
        inline=False
    )

    footer_text = (
        f"Saved by {saver_member.display_name}"
        if saver_member else "Saved to the House archive"
    )

    embed.set_footer(text=footer_text)
    embed.timestamp = message.created_at

    await archive_channel.send(embed=embed)


# ========== SELF-ROLE PANELS COMMAND ==========

@bot.command(name="setup_roles")
@commands.has_permissions(manage_roles=True)
async def setup_roles(ctx: commands.Context):
    """Send the intro and all self-role panels (one message per section)."""

    # 1) Intro message (no buttons)
    intro_text = (
        "🖤 **House of Kith**\n"
        "Welcome to your corner of the House.\n"
        "Here, you shape how you’re seen, your vibe, your voice, and the energy you bring.\n"
        "Take your time, explore, and pick whatever feels like you.\n\n"
        "Nothing dramatic, nothing over-the-top.\n"
        "Just clean, comfortable identity tags for the people who live here."
    )
    await ctx.send(intro_text)

    # 2) Social Roles (color: #E91E63)
    social_embed = discord.Embed(
        title="💬 Social Roles",
        description=(
            "How do you like to interact with people here?\n"
            "These roles help others know what kind of contact you’re okay with "
            "and how you tend to respond.\n\n"
            "**Available roles:**\n"
            + "\n".join(f"• {name}" for name in SOCIAL_ROLES)
        ),
        color=discord.Color.from_str("#E91E63"),
    )
    await ctx.send(embed=social_embed, view=RoleView(SOCIAL_ROLES))

    # 3) Personality Roles (color: #F1C40F)
    personality_embed = discord.Embed(
        title="🌙 Personality Roles",
        description=(
            "The way you move through conversations, spaces, and moods.\n"
            "Pick whatever feels natural; you don’t have to fit into just one box.\n\n"
            "**Available roles:**\n"
            + "\n".join(f"• {name}" for name in PERSONALITY_ROLES)
        ),
        color=discord.Color.from_str("#F1C40F"),
    )
    await ctx.send(embed=personality_embed, view=RoleView(PERSONALITY_ROLES))

    # 4) Gaming Roles (color: #71368A)
    gaming_embed = discord.Embed(
        title="🎮 Gaming Roles",
        description=(
            "How you play, what you’re looking for, and how serious you are about the grind.\n"
            "These make it easier to find your kind of lobbies.\n\n"
            "**Available roles:**\n"
            + "\n".join(f"• {name}" for name in GAMING_ROLES)
        ),
        color=discord.Color.from_str("#71368A"),
    )
    await ctx.send(embed=gaming_embed, view=RoleView(GAMING_ROLES))

    # 5) Music Roles (color: #3498DB)
    music_embed = discord.Embed(
        title="🎧 Music Roles",
        description=(
            "The sounds that live in your headphones most of the time.\n"
            "Choose as many as you like — people will know what to send you.\n\n"
            "**Available roles:**\n"
            + "\n".join(f"• {name}" for name in MUSIC_ROLES)
        ),
        color=discord.Color.from_str("#3498DB"),
    )
    await ctx.send(embed=music_embed, view=RoleView(MUSIC_ROLES))

    await ctx.send("✅ Self-role panels created.")


@setup_roles.error
async def setup_roles_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need the **Manage Roles** permission to use this command.")


# ========== READY EVENT ==========

@bot.event
async def on_ready():
    print(f"House of Kith bot logged in as {bot.user} (ID: {bot.user.id})")

    # Register persistent views once so buttons keep working after restarts
    if not hasattr(bot, "persistent_views_added"):
        bot.add_view(RoleView(SOCIAL_ROLES))
        bot.add_view(RoleView(PERSONALITY_ROLES))
        bot.add_view(RoleView(GAMING_ROLES))
        bot.add_view(RoleView(MUSIC_ROLES))
        bot.persistent_views_added = True

    print("------")


# ========== RUN THE BOT ==========

if __name__ == "__main__":
    bot.run(TOKEN)
