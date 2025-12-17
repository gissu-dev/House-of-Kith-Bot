import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI

# =========================
# CARD DATA
# =========================
MAJOR_ARCANA = [
    {
        "name": "The Fool",
        "upright": "Clean slate, soft risk, trust the first step.",
        "reversed": "Reckless loops, stalled start, fear of falling.",
        "aesthetic": "A lone moth at an open window.",
    },
    {
        "name": "The Magician",
        "upright": "Tools in reach; focus turns ideas into form.",
        "reversed": "Scattered will, sleight of hand, misdirected effort.",
        "aesthetic": "A desk of candles and ink, still warm.",
    },
    {
        "name": "The High Priestess",
        "upright": "Quiet knowing, intuition, secrets breathe slowly.",
        "reversed": "Noise over signal; ignoring your own instincts.",
        "aesthetic": "A black mirror that ripples once.",
    },
    {
        "name": "The Empress",
        "upright": "Nurture, comfort, lush growth in dim light.",
        "reversed": "Withholding warmth, creative block, overgrown vines.",
        "aesthetic": "Velvet drapes, a bowl of dark fruit.",
    },
    {
        "name": "The Emperor",
        "upright": "Structure, boundaries, calm command.",
        "reversed": "Rigid control, cold authority, resentment brewing.",
        "aesthetic": "An iron key stamped with a sigil.",
    },
    {
        "name": "The Hierophant",
        "upright": "Tradition, guidance, lessons passed in whispers.",
        "reversed": "Question the rules; ritual without meaning is hollow.",
        "aesthetic": "A cracked hymn book, pages marked.",
    },
    {
        "name": "The Lovers",
        "upright": "Aligned choices, bonds that mirror values.",
        "reversed": "Misaligned desires, uneasy mirror, divided path.",
        "aesthetic": "Two candles burning unevenly.",
    },
    {
        "name": "The Chariot",
        "upright": "Momentum, direction, disciplined drive.",
        "reversed": "Drift, losing the reins, pulled by two moods.",
        "aesthetic": "Rain on the carriage window, reins taut.",
    },
    {
        "name": "Strength",
        "upright": "Soft courage, patience, gentleness that holds.",
        "reversed": "Frayed nerves, impatience, forcing what needs calm.",
        "aesthetic": "A hand steadying a restless hound.",
    },
    {
        "name": "The Hermit",
        "upright": "Seek quiet, reflect, the lantern is enough.",
        "reversed": "Isolation bites; reach out before the cold sets in.",
        "aesthetic": "A small lantern under a hood.",
    },
    {
        "name": "Wheel of Fortune",
        "upright": "Cycles turn; luck shifts; ride the change, not the fear.",
        "reversed": "Stuck wheel, fighting tides, delay before the shift.",
        "aesthetic": "A clock missing its hands.",
    },
    {
        "name": "Justice",
        "upright": "Cause and effect; weigh with honesty; balance returns.",
        "reversed": "Bias, avoidance, imbalance left unchecked.",
        "aesthetic": "Scales tipped by a single feather.",
    },
    {
        "name": "The Hanged Man",
        "upright": "Pause, reframe, surrender to see what is hidden.",
        "reversed": "Stalled out, martyr loop, refusing a new view.",
        "aesthetic": "A figure suspended in violet light.",
    },
    {
        "name": "Death",
        "upright": "Ending becomes opening; shed what is finished.",
        "reversed": "Clinging to stale cycles; change waits at the door.",
        "aesthetic": "A doorway of smoke and moths.",
    },
    {
        "name": "Temperance",
        "upright": "Blend, pace, find the middle note; patience heals.",
        "reversed": "Excess, imbalance, pouring too fast from one cup.",
        "aesthetic": "Two chalices trading a silver stream.",
    },
    {
        "name": "The Devil",
        "upright": "Temptation, cords of habit, own your desire.",
        "reversed": "Breaking chains, naming the trap, small freedoms.",
        "aesthetic": "A ribbon tied to your wrist, gently tugged.",
    },
    {
        "name": "The Tower",
        "upright": "Sudden break, revelation, walls crack for light.",
        "reversed": "Avoided upheaval, slow crumble, delayed truth.",
        "aesthetic": "Lightning frozen in a photograph.",
    },
    {
        "name": "The Star",
        "upright": "Hope after dust settles; soft guidance; calm breath.",
        "reversed": "Doubt, dimmed faith; refill your own well first.",
        "aesthetic": "A basin catching faint starlight.",
    },
    {
        "name": "The Moon",
        "upright": "Dream logic, intuition; follow the tide, not the fear.",
        "reversed": "Fog thickens; illusions; anchor to a simple truth.",
        "aesthetic": "Moonlight on water that will not sit still.",
    },
    {
        "name": "The Sun",
        "upright": "Clarity, warmth, honest joy; let yourself be seen.",
        "reversed": "Drained glow, forced positivity; rest in shade first.",
        "aesthetic": "A sunbeam through cathedral glass.",
    },
    {
        "name": "Judgement",
        "upright": "Awakening, call to action, answer your own trumpet.",
        "reversed": "Self-doubt, stalled verdict; forgive and move.",
        "aesthetic": "A bell rope that thrums on its own.",
    },
    {
        "name": "The World",
        "upright": "Completion, integration, a loop closes softly.",
        "reversed": "Almost there; one thread still asks attention.",
        "aesthetic": "A wreath hung on a midnight door.",
    },
]

SUIT_INFO = {
    "Wands": {"theme": "passion, creativity, momentum", "sigil": "ember-tipped wand"},
    "Cups": {"theme": "feelings, intuition, relationships", "sigil": "overfull chalice"},
    "Swords": {"theme": "thought, clarity, conflict", "sigil": "slim silver blade"},
    "Pentacles": {"theme": "work, body, resources", "sigil": "worn coin"},
}

MINOR_RANKS = {
    "Ace": (
        "Spark of {theme}; raw potential wants a direction.",
        "Blocked start; hesitation smothers the spark.",
        "A single {sigil} glows faintly.",
    ),
    "Two": (
        "Duality; balancing options; choosing with care.",
        "Stalemate or wobble; avoiding the choice.",
        "Two {sigil}s set on a velvet cloth.",
    ),
    "Three": (
        "Early growth; collaboration; first proof of concept.",
        "Misalignment in the team; plans wobble.",
        "Ink sketches beside a resting {sigil}.",
    ),
    "Four": (
        "Stability; pause; conserve energy.",
        "Stagnation; comfort calcifies; rest becomes rut.",
        "Four {sigil}s arranged in a square.",
    ),
    "Five": (
        "Tension, tests, friction that teaches.",
        "Needless struggle; pride keeps the door shut.",
        "Scattered {sigil}s after a quiet argument.",
    ),
    "Six": (
        "Relief, generosity, sharing what you can.",
        "Strings attached; imbalance in give and take.",
        "An offered {sigil} on an open palm.",
    ),
    "Seven": (
        "Assessment; hold the line; patience with progress.",
        "Restlessness; second-guessing the path.",
        "{sigil}s tucked behind a gate, half-guarded.",
    ),
    "Eight": (
        "Steady work; craft; disciplined pace.",
        "Drudgery; perfectionism stalls the flow.",
        "{sigil}s lined up with careful spacing.",
    ),
    "Nine": (
        "Near completion; self-reliance; maintaining boundaries.",
        "Fatigue, hyper-vigilance; walls too high.",
        "A figure resting against a stack of {sigil}s.",
    ),
    "Ten": (
        "Culmination; carrying the full weight of {theme}.",
        "Overburdened; something must be set down.",
        "{sigil}s gathered under a low ceiling.",
    ),
    "Page": (
        "Curious student; messages; beginner mind in {theme}.",
        "Scattered focus; news delayed or misread.",
        "A letter sealed with a {sigil}.",
    ),
    "Knight": (
        "Pursuit and motion; carrying {theme} forward.",
        "Impulsive or stalled; speed without direction.",
        "A riderless steed bearing a {sigil}.",
    ),
    "Queen": (
        "Mature mastery; intuitive leadership in {theme}.",
        "Inward, guarded, or overprotective with resources.",
        "A quiet throne draped in cloth, a {sigil} atop.",
    ),
    "King": (
        "Command, structure, visible authority in {theme}.",
        "Rigidity, control, or neglect of the human side.",
        "A high-backed chair etched with a {sigil}.",
    ),
}

WHISPERS = [
    "The House deals gently, but it remembers.",
    "Some cards speak louder when the room is quiet.",
    "Ask softly; the veil answers in texture, not volume.",
    "What you fear to name shapes the reading.",
    "The ink is still wet; you are still writing.",
]

MINOR_IMAGE_BASE = "https://www.sacred-texts.com/tarot/pkt/img/"
SUIT_PREFIX = {
    "WANDS": "wa",
    "CUPS": "cu",
    "SWORDS": "sw",
    "PENTACLES": "pe",
}
RANK_NUMBER = {
    "Ace": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5,
    "Six": 6,
    "Seven": 7,
    "Eight": 8,
    "Nine": 9,
    "Ten": 10,
    "Page": 11,
    "Knight": 12,
    "Queen": 13,
    "King": 14,
}

MAJOR_IMAGE_MAP = {
    "The Fool": "ar00",
    "The Magician": "ar01",
    "The High Priestess": "ar02",
    "The Empress": "ar03",
    "The Emperor": "ar04",
    "The Hierophant": "ar05",
    "The Lovers": "ar06",
    "The Chariot": "ar07",
    "Strength": "ar08",
    "The Hermit": "ar09",
    "Wheel of Fortune": "ar10",
    "Justice": "ar11",
    "The Hanged Man": "ar12",
    "Death": "ar13",
    "Temperance": "ar14",
    "The Devil": "ar15",
    "The Tower": "ar16",
    "The Star": "ar17",
    "The Moon": "ar18",
    "The Sun": "ar19",
    "Judgement": "ar20",
    "The World": "ar21",
}

CARD_DECK = MAJOR_ARCANA + [
    {
        "name": f"{rank} of {suit}",
        "upright": meanings[0].format(theme=info["theme"]),
        "reversed": meanings[1].format(theme=info["theme"]),
        "aesthetic": meanings[2].format(sigil=info["sigil"]),
    }
    for suit, info in SUIT_INFO.items()
    for rank, meanings in MINOR_RANKS.items()
]

# =========================
# CONFIG
# =========================
LOG_CHANNEL_ID = 1450608097449083103
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DAILY_PATH = DATA_DIR / "tarot_daily.json"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None


class TarotCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_limits: dict[str, str] = self.load_daily_limits()

    # -------- persistence --------
    def load_daily_limits(self) -> dict:
        if DAILY_PATH.exists():
            try:
                return json.loads(DAILY_PATH.read_text())
            except Exception:
                return {}
        return {}

    def save_daily_limits(self):
        try:
            DAILY_PATH.write_text(json.dumps(self.daily_limits, indent=2))
        except Exception:
            pass

    def today_str(self) -> str:
        return datetime.utcnow().date().isoformat()

    def check_daily(self, user_id: int) -> bool:
        return self.daily_limits.get(str(user_id)) == self.today_str()

    def mark_daily(self, user_id: int):
        self.daily_limits[str(user_id)] = self.today_str()
        self.save_daily_limits()

    # -------- card helpers --------
    def draw_card(self) -> Tuple[dict, str, str]:
        card = random.choice(CARD_DECK)
        orientation = random.choice(["upright", "reversed"])
        return card, orientation, card[orientation]

    def draw_spread(self, count: int = 3) -> List[Tuple[dict, str, str]]:
        cards = random.sample(CARD_DECK, k=count)
        spread: List[Tuple[dict, str, str]] = []
        for card in cards:
            orientation = random.choice(["upright", "reversed"])
            spread.append((card, orientation, card[orientation]))
        return spread

    def card_image(self, card: dict) -> Optional[str]:
        if card["name"] in MAJOR_IMAGE_MAP:
            return f"{MINOR_IMAGE_BASE}{MAJOR_IMAGE_MAP[card['name']]}.jpg"
        parts = card["name"].split(" of ")
        if len(parts) == 2:
            rank, suit = parts[0], parts[1].strip().upper()
            prefix = SUIT_PREFIX.get(suit)
            num = RANK_NUMBER.get(rank)
            if prefix and num:
                return f"{MINOR_IMAGE_BASE}{prefix}{num:02d}.jpg"
        return None

    def card_ascii(self, name: str, orientation: Optional[str] = None) -> str:
        parts = name.split(" of ")
        icon = ""
        if len(parts) == 2:
            suit = parts[1].strip().upper()
            icon = {"WANDS": "♣", "CUPS": "♡", "SWORDS": "†", "PENTACLES": "✢"}.get(suit, "")
        title = name if len(name) <= 22 else name[:19] + "..."
        orient = f" {orientation.title()}" if orientation else ""
        line = f"{title}{orient}"
        pad = max(0, 24 - len(line))
        top = "╔" + ("═" * 24) + "╗"
        mid = f"║ {icon} {line}{' ' * pad}║"
        bot = "╚" + ("═" * 24) + "╝"
        return "\n".join([top, mid, bot])

    async def interpret(self, intention: Optional[str], cards: List[Tuple[dict, str, str]], spread: bool) -> Optional[str]:
        if not client:
            return None
        prompt_cards = [f"{card['name']} ({orientation}): {meaning}" for card, orientation, meaning in cards]
        system = (
            "You are a concise tarot reader for a soft goth Discord server. "
            "Offer a brief, grounded interpretation (3-5 sentences), not fortune-telling. "
            "Stay kind, non-deterministic, and invite reflection."
        )
        user = (
            f"Question: {intention or 'General'}\n"
            f"Spread type: {'Three-card' if spread else 'Single'}\n"
            "Cards:\n- " + "\n- ".join(prompt_cards)
        )
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=180,
                temperature=0.8,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return None

    # -------- embeds --------
    def build_card_embed(
        self,
        card: dict,
        orientation: str,
        meaning: str,
        intention: Optional[str],
        visual: bool,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{card['name']} — {orientation.title()}",
            description=meaning,
            color=discord.Color.from_str("#2a1f2f"),
        )
        embed.add_field(name="Atmosphere", value=card["aesthetic"], inline=False)
        if intention:
            embed.add_field(name="Intention", value=intention[:1024], inline=False)
        image_url = self.card_image(card)
        if image_url:
            embed.set_image(url=image_url)
        elif visual:
            embed.add_field(name="Visual", value=f"```{self.card_ascii(card['name'], orientation)}```", inline=False)
        embed.set_footer(text=random.choice(WHISPERS))
        return embed

    def build_spread_summary_embed(
        self,
        cards: List[Tuple[dict, str, str]],
        intention: Optional[str],
        interpretation: Optional[str],
    ) -> discord.Embed:
        labels = ["Past", "Present", "Future"]
        embed = discord.Embed(
            title="Three-Card Spread",
            description=intention[:1024] if intention else "Past / Present / Future",
            color=discord.Color.from_str("#2a1f2f"),
        )
        for label, (card, orientation, meaning) in zip(labels, cards):
            embed.add_field(
                name=f"{label}: {card['name']} ({orientation})",
                value=f"{meaning}\n*{card['aesthetic']}*",
                inline=False,
            )
        if interpretation:
            embed.add_field(name="Reading", value=interpretation, inline=False)
        embed.set_footer(text=random.choice(WHISPERS) + " — Take what resonates; leave what does not.")
        return embed

    def daily_block_embed(self) -> discord.Embed:
        return discord.Embed(
            title="Tarot limit reached",
            description="One reading per day. Try again tomorrow.",
            color=discord.Color.red(),
        )

    # -------- logging --------
    async def log_reading(
        self,
        user: discord.abc.User,
        intention: Optional[str],
        cards: List[Tuple[dict, str, str]],
        interpretation: Optional[str],
        spread: bool,
    ):
        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        labels = ["Past", "Present", "Future"] if spread else ["Single"]
        card_lines = []
        for label, (card, orientation, _) in zip(labels, cards):
            card_lines.append(f"{label}: {card['name']} ({orientation})")

        embed = discord.Embed(
            title="Tarot Reading Logged",
            color=discord.Color.dark_purple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
        if intention:
            embed.add_field(name="Intention", value=intention[:1024], inline=False)
        embed.add_field(name="Cards", value="\n".join(card_lines), inline=False)
        if interpretation:
            embed.add_field(name="Reading", value=interpretation, inline=False)
        await channel.send(embed=embed)

    # -------- commands --------
    @app_commands.command(name="tarot", description="Draw a single tarot card from the House deck.")
    @app_commands.describe(
        intention="What are you asking about?",
        private="Send only to you (ephemeral).",
        visual="Add ASCII fallback if no image loads.",
        interpret="Let the AI offer a short reading.",
    )
    async def tarot(
        self,
        interaction: discord.Interaction,
        intention: Optional[str] = None,
        private: bool = False,
        visual: bool = False,
        interpret: bool = False,
    ):
        if self.check_daily(interaction.user.id):
            await interaction.response.send_message(embed=self.daily_block_embed(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=private, thinking=True)
        card, orientation, meaning = self.draw_card()
        interpretation = await self.interpret(intention, [(card, orientation, meaning)], spread=False) if interpret else None

        embed = self.build_card_embed(card, orientation, meaning, intention, visual)
        if interpretation:
            embed.add_field(name="Reading", value=interpretation, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=private)
        self.mark_daily(interaction.user.id)
        await self.log_reading(interaction.user, intention, [(card, orientation, meaning)], interpretation, spread=False)

    @app_commands.command(name="tarotspread", description="Three-card spread: past, present, future.")
    @app_commands.describe(
        intention="Your question or focus for the spread.",
        private="Send only to you (ephemeral).",
        visual="Add ASCII fallback if any image fails to load.",
        interpret="Let the AI offer a short reading.",
    )
    async def tarotspread(
        self,
        interaction: discord.Interaction,
        intention: Optional[str] = None,
        private: bool = False,
        visual: bool = False,
        interpret: bool = False,
    ):
        if self.check_daily(interaction.user.id):
            await interaction.response.send_message(embed=self.daily_block_embed(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=private, thinking=True)
        spread_cards = self.draw_spread(3)
        interpretation = await self.interpret(intention, spread_cards, spread=True) if interpret else None

        embeds: List[discord.Embed] = []
        for card, orientation, meaning in spread_cards:
            embeds.append(self.build_card_embed(card, orientation, meaning, None, visual))
        embeds.append(self.build_spread_summary_embed(spread_cards, intention, interpretation))

        await interaction.followup.send(embeds=embeds, ephemeral=private)
        self.mark_daily(interaction.user.id)
        await self.log_reading(interaction.user, intention, spread_cards, interpretation, spread=True)

    @commands.command(name="tarot")
    async def tarot_prefix(self, ctx: commands.Context, *, intention: Optional[str] = None):
        """Prefix fallback: !tarot [your question/intent]"""
        if self.check_daily(ctx.author.id):
            await ctx.send(embed=self.daily_block_embed())
            return

        card, orientation, meaning = self.draw_card()
        interpretation = await self.interpret(intention, [(card, orientation, meaning)], spread=False)
        embed = self.build_card_embed(card, orientation, meaning, intention, visual=True)
        if interpretation:
            embed.add_field(name="Reading", value=interpretation, inline=False)
        await ctx.send(embed=embed)
        self.mark_daily(ctx.author.id)
        await self.log_reading(ctx.author, intention, [(card, orientation, meaning)], interpretation, spread=False)

    @commands.command(name="tarotspread")
    async def tarot_spread_prefix(self, ctx: commands.Context, *, intention: Optional[str] = None):
        """Prefix fallback: !tarotspread [question]"""
        if self.check_daily(ctx.author.id):
            await ctx.send(embed=self.daily_block_embed())
            return

        spread_cards = self.draw_spread(3)
        interpretation = await self.interpret(intention, spread_cards, spread=True)
        embeds: List[discord.Embed] = []
        for card, orientation, meaning in spread_cards:
            embeds.append(self.build_card_embed(card, orientation, meaning, None, visual=True))
        embeds.append(self.build_spread_summary_embed(spread_cards, intention, interpretation))

        await ctx.send(embeds=embeds)
        self.mark_daily(ctx.author.id)
        await self.log_reading(ctx.author, intention, spread_cards, interpretation, spread=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TarotCog(bot))
