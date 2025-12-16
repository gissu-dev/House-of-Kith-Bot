import asyncio
import os
import random
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI

AI_VOICE_DIR = Path("sounds/ai_voice")
AI_VOICE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_PATH = DATA_DIR / "stats.json"

VOICE_MODEL = "gpt-4o-mini-tts"
VOICE_NAME = "onyx"
VOICE_NAME_FEMALE = "alloy"
# Keep flair to a small, known-good set to avoid API failures.
VOICE_STYLES = {
    "onyx": "Grave voice",
    "alloy": "Eerie whisper",
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =========================
# ENUMS / OPTIONS
# =========================
class Difficulty(str, Enum):
    RANDOM = "RANDOM"
    AMATEUR = "AMATEUR"
    INTERMEDIATE = "INTERMEDIATE"
    PROFESSIONAL = "PROFESSIONAL"
    NIGHTMARE = "NIGHTMARE"


class VoiceConsent(str, Enum):
    OFF = "Off"
    SFX_ONLY = "SFX only"
    GHOST_VOICE = "Ghost voice"
    GHOST_VOICE_DEATH = "Ghost voice (death scenes)"


class Phase(str, Enum):
    INVESTIGATION = "INVESTIGATION"
    HUNT = "HUNT"
    ENDED = "ENDED"


DIFFICULTY_POOL = ["AMATEUR", "INTERMEDIATE", "PROFESSIONAL", "NIGHTMARE"]
HUNT_ACTIONS = {"HIDE", "MOVE", "FREEZE"}
EVIDENCE = {"EMF", "SPIRITBOX", "FREEZING", "DOTS", "UV"}

# Difficulty tuning (pressure = how fast hunts start)
DIFF_SETTINGS = {
    "AMATEUR": {
        "hunt_timer": 17,
        "survive_chance": 0.78,
        "pressure_gain": 1,
        "hunt_threshold": 5,
    },
    "INTERMEDIATE": {
        "hunt_timer": 15,
        "survive_chance": 0.65,
        "pressure_gain": 1,
        "hunt_threshold": 5,
    },
    "PROFESSIONAL": {
        "hunt_timer": 14,
        "survive_chance": 0.55,
        "pressure_gain": 2,
        "hunt_threshold": 4,
    },
    "NIGHTMARE": {
        "hunt_timer": 12,
        "survive_chance": 0.47,
        "pressure_gain": 2,
        "hunt_threshold": 4,
    },
}

GHOST_ACTION_CLUES = {
    "SEARCH": [
        "Heavy footsteps scrape from room to room.",
        "Floorboards creak in a slow sweep across the hall.",
        "Drawers rattle open and shut nearby.",
        "A door opens, then another - methodical searching.",
        "Something brushes past furniture as if checking hiding spots.",
        "Cabinets bang one by one, like it's looking for you.",
        "A lantern glow prowls the doorway gaps.",
        "You hear slow pacing, circling the area.",
    ],
    "LISTEN": [
        "The house goes still; you hear only your own breathing.",
        "A hush falls... like it's waiting for a sound.",
        "The ghost pauses; you feel it listening through the walls.",
        "Silence presses in, as if ears are everywhere.",
        "No footsteps... just the weight of a presence, listening.",
        "Boards stop creaking; the air strains for a whisper.",
        "You hear faint breaths, as if it's holding still to catch yours.",
    ],
    "CHASE": [
        "Fast footsteps slam toward you.",
        "A sprinting rush barrels down the hall.",
        "Claws drag quick and close; it's coming in hot.",
        "A loud rush of air - it's charging.",
        "You hear a frantic pounding, gaining fast.",
        "Footfalls break into a run; no more hiding.",
        "A low growl rises as it lunges closer.",
    ],
}

DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Random (shuffle)", value="RANDOM"),
    app_commands.Choice(name="Amateur (cozy)", value="AMATEUR"),
    app_commands.Choice(name="Intermediate (tense)", value="INTERMEDIATE"),
    app_commands.Choice(name="Professional (hard)", value="PROFESSIONAL"),
    app_commands.Choice(name="Nightmare (brutal)", value="NIGHTMARE"),
]

VOICE_CHOICES = [
    app_commands.Choice(name="Off (text only)", value=VoiceConsent.OFF.value),
    app_commands.Choice(name="SFX only (short stings)", value=VoiceConsent.SFX_ONLY.value),
    app_commands.Choice(name="Ghost voice (short lines)", value=VoiceConsent.GHOST_VOICE.value),
    app_commands.Choice(
        name="Ghost voice + death whispers",
        value=VoiceConsent.GHOST_VOICE_DEATH.value,
    ),
]

VOICE_FLAIR_CHOICES = [
    app_commands.Choice(name="Random", value="random"),
    app_commands.Choice(name="Grave (onyx)", value="onyx"),
    app_commands.Choice(name="Eerie (alloy)", value="alloy"),
]


@dataclass
class GhostProfile:
    name: str
    evidence: Set[str]
    trait: str
    mods: dict


ghosts = [
    GhostProfile(
        name="Banshee",
        evidence={"SPIRITBOX", "EMF", "FREEZING", "DOTS"},
        trait="Fixates on the contract host. Spirit Box is more talkative.",
        mods={"spiritbox_bonus": 0.15, "hunt_pressure_bonus": 1},
    ),
    GhostProfile(
        name="Demon",
        evidence={"EMF", "FREEZING"},
        trait="Loves to hunt early. Surviving a hunt is harder.",
        mods={"survive_penalty": 0.10, "hunt_chance_bonus": 0.10},
    ),
    GhostProfile(
        name="Phantom",
        evidence={"SPIRITBOX", "FREEZING", "DOTS"},
        trait="Creates fake readings. EMF 5 is rarer. DOTS glow is faint.",
        mods={"emf_true_penalty": 0.15, "fake_event_bonus": 0.15},
    ),
    GhostProfile(
        name="Shade",
        evidence={"EMF", "SPIRITBOX", "UV"},
        trait="Shy but dangerous when sanity is low.",
        mods={"low_sanity_hunt_bonus": 0.12},
    ),
    GhostProfile(
        name="Revenant",
        evidence={"EMF", "SPIRITBOX", "FREEZING", "UV"},
        trait="Slow build, brutal hunts. FREEZE action helps a bit.",
        mods={"freeze_action_bonus": 0.08, "hunt_pressure_bonus": 1},
    ),
    GhostProfile(
        name="Wraith",
        evidence={"SPIRITBOX", "EMF", "DOTS"},
        trait="Flickers lights and glides. Harder to hear before hunts.",
        mods={"fake_event_bonus": 0.20, "hunt_chance_bonus": 0.05},
    ),
    GhostProfile(
        name="Poltergeist",
        evidence={"EMF", "FREEZING", "UV"},
        trait="Throws stuff. EMF noise is messy, but freezing is steady.",
        mods={"emf_true_penalty": 0.10, "freeze_action_bonus": 0.05},
    ),
    GhostProfile(
        name="Siren",
        evidence={"SPIRITBOX", "FREEZING", "DOTS"},
        trait="Whispers lullabies. Spirit Box odds up, hunts punish freeze.",
        mods={"spiritbox_bonus": 0.18, "freeze_action_bonus": -0.05},
    ),
    GhostProfile(
        name="Doppelganger",
        evidence={"EMF", "SPIRITBOX", "UV"},
        trait="Mimics footsteps. Hunts pick up faster with pressure.",
        mods={"hunt_pressure_bonus": 2, "hunt_chance_bonus": 0.05},
    ),
]


# =========================
# GAME STATE
# =========================
@dataclass
class Game:
    guild_id: int
    channel_id: int
    host_id: int
    difficulty: str
    ghost: GhostProfile

    phase: Phase = Phase.INVESTIGATION
    sanity: int = 100
    pressure: int = 0
    evidence_found: Set[str] = field(default_factory=set)
    guess: Optional[str] = None

    voice_consent: str = "Off"
    voice_flair: str = "random"
    voice_channel_id: Optional[int] = None

    hunt_deadline_seconds: int = 6
    hunt_active: bool = False


# =========================
# COG
# =========================
class GhostGameCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: Dict[int, Game] = {}
        self.player_stats: Dict[str, dict] = self.load_stats()

    # ---------- helpers ----------
    def stats_key(self, guild_id: int, user_id: int) -> str:
        return f"{guild_id}:{user_id}"

    def load_stats(self) -> Dict[str, dict]:
        if STATS_PATH.exists():
            try:
                return json.loads(STATS_PATH.read_text())
            except Exception:
                return {}
        return {}

    def save_stats(self):
        try:
            STATS_PATH.write_text(json.dumps(self.player_stats, indent=2))
        except Exception:
            pass

    def bump_stat(self, guild_id: int, user_id: int, key: str, amount: int = 1):
        k = self.stats_key(guild_id, user_id)
        record = self.player_stats.setdefault(
            k, {"started": 0, "wins": 0, "hunts_survived": 0, "deaths": 0, "clues_logged": 0}
        )
        record[key] = record.get(key, 0) + amount
        self.player_stats[k] = record
        self.save_stats()

    async def disconnect_voice(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        vc = guild.voice_client
        if vc and vc.is_connected():
            try:
                await vc.disconnect()
            except Exception:
                pass

    async def disconnect_voice_after_play(self, guild_id: int, max_delay: float = 6.0):
        """Wait for current audio (up to max_delay) before disconnecting."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        vc = guild.voice_client
        if not vc:
            return
        waited = 0.0
        while vc.is_playing() and waited < max_delay:
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                return
            waited += 0.5
        await self.disconnect_voice(guild_id)

    def pick_voice_name(self, game: Optional[Game], prefer_female: bool = False) -> str:
        if not game:
            return VOICE_NAME
        style = game.voice_flair if game.voice_flair and game.voice_flair != "random" else None
        if prefer_female and not style:
            style = "alloy"
        if not style:
            style = random.choice(list(VOICE_STYLES.keys()))
        return style if style in VOICE_STYLES else VOICE_NAME

    def tts_to_file(self, text: str, voice_name: str, file_path: Path, instructions: str) -> bool:
        try:
            response = client.audio.speech.create(
                model=VOICE_MODEL,
                voice=voice_name,
                input=text,
                response_format="wav",
                instructions=instructions,
            )
            response.stream_to_file(str(file_path))
            return True
        except Exception:
            if voice_name != VOICE_NAME:
                try:
                    response = client.audio.speech.create(
                        model=VOICE_MODEL,
                        voice=VOICE_NAME,
                        input=text,
                        response_format="wav",
                        instructions=instructions,
                    )
                    response.stream_to_file(str(file_path))
                    return True
                except Exception:
                    return False
            return False

    async def send_box(self, channel: discord.abc.Messageable, text: str):
        await channel.send(f"```txt\n{text}\n```")

    def is_game_channel(self, message: discord.Message, game: Game) -> bool:
        return message.channel.id == game.channel_id

    async def play_voice(self, guild_id: int, text: str):
        game = self.games.get(guild_id)
        if not game or game.voice_consent == VoiceConsent.OFF.value:
            return

        if not game.voice_channel_id:
            return

        voice_channel = self.bot.get_channel(game.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            return

        file_path = AI_VOICE_DIR / f"ghost_{guild_id}.wav"
        ok = self.tts_to_file(
            text,
            self.pick_voice_name(game),
            file_path,
            "Speak slowly, ominously, like a horror game narrator. Lean into pauses and low tones.",
        )
        if not ok:
            return

        vc: Optional[discord.VoiceClient] = voice_channel.guild.voice_client
        try:
            if vc and vc.channel != voice_channel:
                await vc.move_to(voice_channel)
            elif not vc:
                vc = await voice_channel.connect()
        except Exception:
            return

        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(str(file_path)))

    async def play_death_voice(self, guild_id: int, text: str):
        game = self.games.get(guild_id)
        if not game or game.voice_consent == VoiceConsent.OFF.value:
            return
        if not game.voice_channel_id:
            return

        voice_channel = self.bot.get_channel(game.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            return

        file_path = AI_VOICE_DIR / f"death_{guild_id}.wav"
        ok = self.tts_to_file(
            text,
            self.pick_voice_name(game, prefer_female=True),
            file_path,
            "Creepy female whisper. Soft, eerie, unnervingly calm. Keep it under 3 seconds.",
        )
        if not ok:
            return

        vc: Optional[discord.VoiceClient] = voice_channel.guild.voice_client
        try:
            if vc and vc.channel != voice_channel:
                await vc.move_to(voice_channel)
            elif not vc:
                vc = await voice_channel.connect()
        except Exception:
            return

        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(str(file_path)))

    async def play_sfx_event(self, guild_id: int, prompt: str):
        """Short SFX/voice sting for ghost events; non-blocking trigger."""
        game = self.games.get(guild_id)
        if not game or game.voice_consent == VoiceConsent.OFF.value:
            return
        if not game.voice_channel_id:
            return

        voice_channel = self.bot.get_channel(game.voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            return

        file_path = AI_VOICE_DIR / f"event_{guild_id}.wav"
        ok = self.tts_to_file(
            prompt,
            self.pick_voice_name(game),
            file_path,
            "Keep it to 2 seconds. Whispery, creepy, quick sting.",
        )
        if not ok:
            return

        vc: Optional[discord.VoiceClient] = voice_channel.guild.voice_client
        try:
            if vc and vc.channel != voice_channel:
                await vc.move_to(voice_channel)
            elif not vc:
                vc = await voice_channel.connect()
        except Exception:
            return

        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(str(file_path)))

    async def show_actions(self, channel: discord.abc.Messageable, game: Game):
        if game.phase == Phase.INVESTIGATION:
            embed = discord.Embed(
                title="🕯️ THE HOUSE LISTENS",
                description="_Short words. Quick replies._",
                color=discord.Color.from_str("#4A3D5E"),
            )
            embed.add_field(name="Moves", value="`scan` · `wait`", inline=True)
            embed.add_field(name="Tools", value="`emf` · `spirit <q>` · `thermo` · `dots` · `uv`", inline=True)
            embed.add_field(
                name="Evidence",
                value="`log emf` · `log spirit` · `log freeze` · `log dots` · `log uv`",
                inline=False,
            )
            embed.add_field(
                name="Journal",
                value="`undo <evidence>` · `journal` · `list ghosts`",
                inline=False,
            )
            embed.add_field(name="Commit", value="`commit <ghost>` · `end`", inline=False)
            embed.set_footer(text="Tip: the quiet ones live longer.")
            await channel.send(embed=embed)
        elif game.phase == Phase.HUNT:
            embed = discord.Embed(
                title="💀 HUNT (RPS)",
                description="_Type one word fast._",
                color=discord.Color.from_str("#8B0000"),
            )
            embed.add_field(
                name="hide",
                value="> listen   | < search  | = chase",
                inline=False,
            )
            embed.add_field(
                name="move",
                value="> search   | < chase   | = listen",
                inline=False,
            )
            embed.add_field(
                name="freeze",
                value="> chase    | < listen  | = search",
                inline=False,
            )
            embed.set_footer(text="One word. Hurry.")
            await channel.send(embed=embed)

    def format_status(self, game: Game) -> str:
        ev = ", ".join(sorted(game.evidence_found)) if game.evidence_found else "None"
        return f"Sanity: {game.sanity}% | Pressure: {game.pressure} | Evidence: {ev}"

    def ghost_for_name(self, name: str) -> Optional[GhostProfile]:
        for ghost in ghosts:
            if ghost.name.lower() == name.lower():
                return ghost
        return None

    # =========================
    # SLASH COMMAND: /ghosthunt
    # =========================
    @app_commands.command(
        name="ghosthunt",
        description="Start a contract. Pick difficulty and voice, or roll with defaults.",
    )
    @app_commands.describe(
        difficulty="Difficulty vibe",
        voice="Voice/SFX level",
        channel="Voice channel for audio (needed if voice is on)",
        voice_flair="Pick a voice style (optional)",
    )
    @app_commands.choices(
        difficulty=DIFFICULTY_CHOICES,
        voice=VOICE_CHOICES,
        voice_flair=VOICE_FLAIR_CHOICES,
    )
    async def ghosthunt(
        self,
        interaction: discord.Interaction,
        difficulty: Optional[app_commands.Choice[str]] = None,
        voice: Optional[app_commands.Choice[str]] = None,
        voice_flair: Optional[app_commands.Choice[str]] = None,
        channel: Optional[discord.VoiceChannel] = None,
    ):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Guild-only.", ephemeral=True)

        if guild.id in self.games and self.games[guild.id].phase != Phase.ENDED:
            return await interaction.response.send_message("A contract is already active.", ephemeral=True)

        chosen = (
            difficulty.value
            if difficulty and difficulty.value != Difficulty.RANDOM.value
            else random.choice(DIFFICULTY_POOL)
        )

        voice_value = voice.value if voice else VoiceConsent.OFF.value
        voice_flair_value = voice_flair.value if voice_flair else "random"

        if voice_value != VoiceConsent.OFF.value and channel is None:
            return await interaction.response.send_message(
                "If voice is ON, pick a voice channel for output audio.",
                ephemeral=True,
            )

        ghost = random.choice(ghosts)
        game = Game(
            guild_id=guild.id,
            channel_id=interaction.channel_id,
            host_id=interaction.user.id,
            difficulty=chosen,
            ghost=ghost,
            voice_consent=voice_value,
            voice_flair=voice_flair_value,
            voice_channel_id=channel.id if channel else None,
        )

        settings = DIFF_SETTINGS[chosen]
        game.hunt_deadline_seconds = settings["hunt_timer"]

        self.games[guild.id] = game
        self.bump_stat(guild.id, interaction.user.id, "started")

        await interaction.response.send_message(
            f"```txt\nCONTRACT STARTED\nGhost present.\nDifficulty: {chosen}\nVoice: {voice_value}\nVoice flair: {voice_flair_value}\n"
            f"Text channel: <#{interaction.channel_id}>\n"
            f"{'Voice channel: ' + channel.name if channel else 'Voice channel: (none)'}\n\n"
            f"Type actions in this channel.\n{self.format_status(game)}\n```"
        )
        await self.show_actions(interaction.channel, game)
        await self.play_voice(guild.id, "The contract has begun. Tread softly.")

    @app_commands.command(name="ghoststats", description="Show a player's contract stats.")
    @app_commands.describe(member="Player to inspect (default: you)")
    async def ghoststats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Guild-only.", ephemeral=True)
        member = member or interaction.user
        key = self.stats_key(guild.id, member.id)
        record = self.player_stats.get(
            key, {"started": 0, "wins": 0, "hunts_survived": 0, "deaths": 0, "clues_logged": 0}
        )
        embed = discord.Embed(
            title=f"📜 {member.display_name}'s Stats",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Contracts started", value=str(record.get("started", 0)), inline=True)
        embed.add_field(name="Wins", value=str(record.get("wins", 0)), inline=True)
        embed.add_field(name="Hunts survived", value=str(record.get("hunts_survived", 0)), inline=True)
        embed.add_field(name="Deaths", value=str(record.get("deaths", 0)), inline=True)
        embed.add_field(name="Clues logged", value=str(record.get("clues_logged", 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ghostend", description="Force end the active contract.")
    async def ghostend(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Guild-only.", ephemeral=True)

        game = self.games.get(guild.id)
        if not game:
            return await interaction.response.send_message("No active contract.", ephemeral=True)

        if interaction.user.id != game.host_id and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Only host or admins can end it.", ephemeral=True)

        game.phase = Phase.ENDED
        ended = self.games.pop(guild.id, None)
        reveal = f"Ghost was: {ended.ghost.name}" if ended else "Ghost unknown."
        await interaction.response.send_message(f"```txt\nContract ended.\n{reveal}\n```")
        await self.play_voice(guild.id, "The hunt is called off. For now.")
        await self.disconnect_voice(guild.id)

    # =========================
    # MESSAGE-DRIVEN GAMEPLAY
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        game = self.games.get(message.guild.id)
        if not game:
            return

        if not self.is_game_channel(message, game):
            return

        if game.phase == Phase.ENDED:
            return

        content = message.content.strip()
        if not content:
            return

        if content.lower() == "end":
            ended = self.games.pop(message.guild.id, None)
            reveal = f"The ghost was: {ended.ghost.name}" if ended else "Ghost unknown."
            await self.send_box(message.channel, f"Contract ended.\n{reveal}")
            await self.play_voice(message.guild.id, "The investigation ceases. The house watches.")
            await self.disconnect_voice(message.guild.id)
            return

        if game.phase == Phase.INVESTIGATION:
            await self.handle_investigation(message, game, content)
        elif game.phase == Phase.HUNT:
            await self.handle_hunt_input(message, game, content)

    async def handle_investigation(self, message: discord.Message, game: Game, content: str):
        cmd = content.lower()
        settings = DIFF_SETTINGS[game.difficulty]

        def normalize_ev(ev: str) -> str:
            ev = ev.upper()
            if ev in {"SPIRIT", "SPIRITBOX", "BOX"}:
                return "SPIRITBOX"
            if ev in {"FREEZE", "FREEZING", "COLD"}:
                return "FREEZING"
            if ev in {"DOT", "DOTS"}:
                return "DOTS"
            if ev in {"UV", "ULTRAVIOLET"}:
                return "UV"
            return ev

        async def maybe_event():
            base = 0.18 + (game.pressure * 0.04)
            base += game.ghost.mods.get("hunt_chance_bonus", 0)
            if game.sanity < 30:
                base += 0.07
                base += game.ghost.mods.get("low_sanity_hunt_bonus", 0)
            if random.random() < 0.25 + game.ghost.mods.get("fake_event_bonus", 0):
                await self.send_box(message.channel, "GHOST EVENT\nA light flickers, then silence.")
                asyncio.create_task(
                    self.play_sfx_event(
                        message.guild.id,
                        random.choice(
                            [
                                "A light flickers.",
                                "A whisper.",
                                "Footsteps stop.",
                                "A cold breath.",
                            ]
                        ),
                    )
                )
            if game.pressure >= settings["hunt_threshold"] and random.random() < base:
                await self.start_hunt(message.channel, game, target=message.author)

        if cmd == "list ghosts":
            lines = []
            for g in ghosts:
                ev = ", ".join(sorted(g.evidence))
                lines.append(f"{g.name}: {ev}\n- {g.trait}")
            await self.send_box(message.channel, "GHOST ROSTER\n" + "\n\n".join(lines))
            return

        if cmd == "journal":
            ev = ", ".join(sorted(game.evidence_found)) if game.evidence_found else "None"
            await self.send_box(
                message.channel,
                "JOURNAL\n"
                f"Ghost evidence to find: EMF, SPIRITBOX, FREEZING, DOTS, UV\n"
                f"Logged: {ev}\n"
                "Log evidence with: log emf | log spirit | log freeze | log dots | log uv\n"
                "Undo with: undo <evidence>\n"
                "Commit guess: commit <ghost name>\n"
                f"{self.format_status(game)}",
            )
            return

        if cmd.startswith("log "):
            ev = normalize_ev(cmd.replace("log ", "").strip())
            if ev not in EVIDENCE:
                await self.send_box(message.channel, "Unknown evidence. Try: emf, spirit, freeze, dots, uv.")
                return
            game.evidence_found.add(ev)
            self.bump_stat(message.guild.id, message.author.id, "clues_logged")
            await self.send_box(message.channel, f"Logged {ev}. {self.format_status(game)}")
            return

        if cmd.startswith("undo "):
            ev = normalize_ev(cmd.replace("undo ", "").strip())
            game.evidence_found.discard(ev)
            await self.send_box(message.channel, f"Removed {ev} from journal. {self.format_status(game)}")
            return

        if cmd.startswith("commit "):
            guess_name = content[7:].strip()
            if not guess_name:
                await self.send_box(message.channel, "Usage: commit <ghost name>")
                return
            guess = self.ghost_for_name(guess_name)
            if not guess:
                await self.send_box(message.channel, "Ghost not found. Try: list ghosts")
                return
            game.guess = guess.name
            if guess.name == game.ghost.name:
                game.phase = Phase.ENDED
                self.games.pop(message.guild.id, None)
                self.bump_stat(message.guild.id, message.author.id, "wins")
                await self.send_box(
                    message.channel,
                    f"CONTRACT COMPLETE\nYou identified the ghost: {guess.name}\nYou win.",
                )
                await self.play_voice(message.guild.id, "You named me correctly. I recede, for now.")
                await self.disconnect_voice(message.guild.id)
            else:
                await self.kill(
                    message.channel,
                    game,
                    f"Wrong guess: {guess.name}. The ghost was {game.ghost.name}.",
                    actor=message.author,
                )
            return

        if cmd == "scan":
            game.pressure += settings["pressure_gain"]
            game.sanity = max(0, game.sanity - random.randint(1, 4))
            lines = [
                "You scan. A faint creak echoes somewhere.",
                "You scan. The air feels heavier for a moment.",
                "You scan. Something shifts out of sight.",
            ]
            await self.send_box(message.channel, random.choice(lines) + f"\n{self.format_status(game)}")
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd == "wait":
            game.pressure += settings["pressure_gain"] + 1
            game.sanity = max(0, game.sanity - random.randint(6, 12))
            await self.send_box(message.channel, f"You wait. Time crawls.\n{self.format_status(game)}")
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd == "emf" or cmd.startswith("use emf"):
            game.pressure += settings["pressure_gain"]
            base_true = 0.55 if "EMF" in game.ghost.evidence else 0.20
            base_true -= game.ghost.mods.get("emf_true_penalty", 0)
            reading_true = random.random() < base_true
            if reading_true:
                result = random.choice(["EMF 5 spike", "EMF 5 sustained", "EMF 5 then silence"])
            else:
                result = random.choice(["EMF 2", "EMF 3 blip", "EMF flicker, no spike"])
            await self.send_box(message.channel, f"You use EMF.\n{result}\n{self.format_status(game)}")
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd.startswith("spirit") or cmd.startswith("use spiritbox"):
            game.pressure += settings["pressure_gain"]
            base_true = 0.50 if "SPIRITBOX" in game.ghost.evidence else 0.20
            base_true += game.ghost.mods.get("spiritbox_bonus", 0)
            response_true = random.random() < base_true
            if response_true:
                answer = random.choice(["\"BEHIND\"", "\"HERE\"", "\"LEAVE\"", "\"DIE\""])
            else:
                answer = "...static..."
            await self.send_box(
                message.channel,
                f"You use Spirit Box.\nSpirit Box: {answer}\n{self.format_status(game)}",
            )
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd == "thermo" or cmd.startswith("use thermo"):
            game.pressure += settings["pressure_gain"]
            freezing_true = random.random() < (0.55 if "FREEZING" in game.ghost.evidence else 0.22)
            if freezing_true:
                temp_line = random.choice(["-5C (freezing!)", "-3C (freezing!)", "-7C (freezing!)"])
            else:
                temp_line = random.choice(["7C", "9C", "12C"])
            await self.send_box(
                message.channel,
                f"You check temperature.\nThermometer reads: {temp_line}\n{self.format_status(game)}",
            )
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd == "dots" or cmd.startswith("use dots"):
            game.pressure += settings["pressure_gain"]
            dots_true = random.random() < (0.55 if "DOTS" in game.ghost.evidence else 0.20)
            if dots_true:
                dots_line = random.choice(
                    ["Shadow crosses the DOTS", "Green shimmer streaks past", "Silhouette flickers in the dots"]
                )
            else:
                dots_line = random.choice(["Nothing crosses the DOTS", "Dots flicker, no figure", "Static shimmer only"])
            await self.send_box(
                message.channel,
                f"DOTS projector:\n{dots_line}\n{self.format_status(game)}",
            )
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        if cmd == "uv" or cmd.startswith("use uv"):
            game.pressure += settings["pressure_gain"]
            uv_true = random.random() < (0.55 if "UV" in game.ghost.evidence else 0.22)
            if uv_true:
                uv_line = random.choice(["Fresh fingerprints glow", "Handprint streak on the wall", "Smudge lights up purple"])
            else:
                uv_line = random.choice(["No prints", "Nothing reacts to UV", "Faint dust, no clear prints"])
            await self.send_box(
                message.channel,
                f"UV scan:\n{uv_line}\n{self.format_status(game)}",
            )
            await maybe_event()
            await self.show_actions(message.channel, game)
            return

        return

    # =========================
    # HUNT SYSTEM
    # =========================
    async def start_hunt(self, channel: discord.abc.Messageable, game: Game, target: discord.Member):
        if game.hunt_active:
            return

        game.phase = Phase.HUNT
        game.hunt_active = True

        timer = DIFF_SETTINGS[game.difficulty]["hunt_timer"]

        def ghost_action_choice() -> str:
            # Weight chase a bit more as pressure rises.
            base = {"SEARCH": 0.34, "LISTEN": 0.33, "CHASE": 0.33}
            chase_bonus = min(0.10, game.pressure * 0.02)
            base["CHASE"] += chase_bonus
            total = sum(base.values())
            roll = random.random() * total
            for action, weight in base.items():
                roll -= weight
                if roll <= 0:
                    return action
            return "SEARCH"

        ghost_action = ghost_action_choice()
        clue_text = random.choice(GHOST_ACTION_CLUES.get(ghost_action, ["You hear movement."]))

        embed = discord.Embed(
            title="💀 HUNT STARTED",
            description="Choose one action fast.\n`hide` | `move` | `freeze`",
            color=discord.Color.from_str("#8B0000"),
        )
        embed.add_field(name="Target", value=target.display_name, inline=True)
        embed.add_field(name="Time", value=f"{timer}s", inline=True)
        embed.add_field(name="Clue", value=f"**{clue_text}**", inline=False)
        embed.set_footer(text="Rock/Paper/Scissors rules. One word.")

        await channel.send(embed=embed)
        # Kick off the hunt audio without delaying message capture.
        asyncio.create_task(self.play_voice(game.guild_id, "It is hunting. Do not breathe."))

        def check(m: discord.Message) -> bool:
            if m.author.bot:
                return False
            if not m.guild or m.guild.id != game.guild_id:
                return False
            if m.channel.id != game.channel_id:
                return False
            c = m.content.strip().upper()
            return c in HUNT_ACTIONS

        try:
            msg = await self.bot.wait_for("message", timeout=timer, check=check)
        except asyncio.TimeoutError:
            await self.kill(channel, game, "No response in time.")
            return

        choice = msg.content.strip().upper()
        def resolve_outcome(player: str, ghost: str) -> str:
            win_pairs = {("HIDE", "LISTEN"), ("MOVE", "SEARCH"), ("FREEZE", "CHASE")}
            lose_pairs = {("HIDE", "SEARCH"), ("MOVE", "CHASE"), ("FREEZE", "LISTEN")}
            if (player, ghost) in win_pairs:
                return "win"
            if (player, ghost) in lose_pairs:
                return "lose"
            return "tie"

        outcome = resolve_outcome(choice, ghost_action)
        base_survive = DIFF_SETTINGS[game.difficulty]["survive_chance"] - game.ghost.mods.get(
            "survive_penalty", 0
        )
        action_bonus = {"HIDE": 0.22, "MOVE": 0.10, "FREEZE": 0.14}.get(choice, 0)
        if choice == "FREEZE" and "FREEZING" in game.ghost.evidence:
            action_bonus += game.ghost.mods.get("freeze_action_bonus", 0.05)
        elif choice == "FREEZE":
            action_bonus -= 0.05

        survive_chance = max(0.05, min(0.95, base_survive + action_bonus))

        if outcome == "lose":
            await self.kill(
                channel,
                game,
                f"{msg.author.display_name} chose {choice}. The ghost used {ghost_action} and caught you.",
                actor=msg.author,
            )
            return

        if outcome == "tie" and random.random() > survive_chance:
            await self.kill(
                channel,
                game,
                f"{msg.author.display_name} chose {choice}. The ghost used {ghost_action}. You hesitated and died.",
                actor=msg.author,
            )
            return

        game.phase = Phase.INVESTIGATION
        game.hunt_active = False
        game.pressure = max(0, game.pressure - 2)
        game.sanity = max(0, game.sanity - random.randint(8, 16))
        self.bump_stat(game.guild_id, msg.author.id, "hunts_survived")

        result_line = {
            "win": "You outplayed it.",
            "tie": "You barely slipped by.",
        }.get(outcome, "You survived.")

        result_embed = discord.Embed(
            title="🕯️ HUNT RESULT",
            description=result_line,
            color=discord.Color.from_str("#2E8B57"),
        )
        result_embed.add_field(name="Ghost move", value=ghost_action.title(), inline=True)
        result_embed.add_field(name="You", value=choice, inline=True)
        result_embed.add_field(name="Status", value=self.format_status(game), inline=False)
        result_embed.set_footer(text="Breathe. Until the next hunt.")

        await channel.send(embed=result_embed)
        await self.show_actions(channel, game)

    async def handle_hunt_input(self, message: discord.Message, game: Game, content: str):
        return

    async def kill(self, channel: discord.abc.Messageable, game: Game, reason: str, actor: Optional[discord.Member] = None):
        game.phase = Phase.ENDED
        game.hunt_active = False
        await self.send_box(channel, f"{reason}\nThe ghost was: {game.ghost.name}\n\nYOU DIED.\nContract over.")
        await self.play_death_voice(game.guild_id, "You failed. The house keeps your echo.")
        self.games.pop(game.guild_id, None)
        if actor:
            self.bump_stat(game.guild_id, actor.id, "deaths")
        await self.disconnect_voice_after_play(game.guild_id, max_delay=6.0)


async def setup(bot: commands.Bot):
    await bot.add_cog(GhostGameCog(bot))
