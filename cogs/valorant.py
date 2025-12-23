import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
import httpx

VAL_API_KEY = os.getenv("VAL_API_KEY")
DEFAULT_REGION = os.getenv("VAL_REGION", "na")
API_BASE = "https://api.henrikdev.xyz/valorant"
DB_PATH = Path("data/valorant.db")


class ValorantAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10)

    async def close(self):
        await self.client.aclose()

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = {"Authorization": self.api_key} if self.api_key else {}
        resp = await self.client.get(f"{API_BASE}{path}", headers=headers, params=params)
        if resp.status_code in (204, 404):
            return None
        if resp.status_code == 429:
            raise RuntimeError("Rate limited by Valorant API. Try again soon.")
        resp.raise_for_status()
        return resp.json()

    async def account(self, name: str, tag: str) -> Optional[Dict[str, Any]]:
        return await self.get(f"/v1/account/{name}/{tag}")

    async def mmr(self, name: str, tag: str, region: str) -> Optional[Dict[str, Any]]:
        return await self.get(f"/v2/mmr/{region}/{name}/{tag}")

    async def matches(self, name: str, tag: str, region: str, size: int = 5) -> Optional[Dict[str, Any]]:
        return await self.get(f"/v4/matches/{region}/{name}/{tag}", params={"size": size, "filter": "competitive"})

    async def live(self, name: str, tag: str) -> Optional[Dict[str, Any]]:
        return await self.get(f"/v4/live/{name}/{tag}")


class ValorantCog(commands.GroupCog, name="valorant"):
    """Valorant stats, parties, live match, and smurf heuristic."""

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.api = ValorantAPI(VAL_API_KEY or "")
        self.db_ready = asyncio.Event()
        self.db_path = DB_PATH
        bot.loop.create_task(self.init_db())

    async def cog_unload(self):
        await self.api.close()

    # -------- DB --------
    async def init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users(
                    discord_id INTEGER PRIMARY KEY,
                    riot_name TEXT NOT NULL,
                    riot_tag TEXT NOT NULL,
                    puuid TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS matches(
                    match_id TEXT PRIMARY KEY,
                    started_at INTEGER,
                    map TEXT,
                    mode TEXT,
                    team_win TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS players(
                    match_id TEXT,
                    puuid TEXT,
                    name TEXT,
                    tag TEXT,
                    team TEXT,
                    party_id TEXT,
                    kills INTEGER,
                    deaths INTEGER,
                    assists INTEGER,
                    score INTEGER,
                    hs REAL,
                    adr REAL,
                    UNIQUE(match_id, puuid)
                )
                """
            )
            await db.commit()
        self.db_ready.set()

    async def get_link(self, discord_id: int) -> Optional[Tuple[str, str]]:
        await self.db_ready.wait()
        async with aiosqlite.connect(self.db_path) as db:
            row = await db.execute_fetchone("SELECT riot_name, riot_tag FROM users WHERE discord_id = ?", (discord_id,))
        if row:
            return row[0], row[1]
        return None

    async def set_link(self, discord_id: int, name: str, tag: str, puuid: Optional[str]):
        await self.db_ready.wait()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users(discord_id, riot_name, riot_tag, puuid)
                VALUES(?,?,?,?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    riot_name=excluded.riot_name,
                    riot_tag=excluded.riot_tag,
                    puuid=excluded.puuid
                """,
                (discord_id, name, tag, puuid),
            )
            await db.commit()

    async def clear_link(self, discord_id: int):
        await self.db_ready.wait()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE discord_id = ?", (discord_id,))
            await db.commit()

    async def store_match(self, match: Dict[str, Any]):
        """Persist minimal match/party data for later party lookups."""
        await self.db_ready.wait()
        meta = match.get("metadata") or {}
        match_id = meta.get("matchid")
        if not match_id:
            return
        started = int(meta.get("game_start", 0) // 1000)
        map_name = meta.get("map")
        mode = meta.get("mode")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO matches(match_id, started_at, map, mode, team_win) VALUES(?,?,?,?,?)",
                (match_id, started, map_name, mode, (meta.get("cluster") or "")),
            )
            players = match.get("players", {}).get("all_players", [])
            for p in players:
                stats = p.get("stats", {}) or {}
                await db.execute(
                    """
                    INSERT OR IGNORE INTO players(
                        match_id, puuid, name, tag, team, party_id, kills, deaths, assists, score, hs, adr
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        match_id,
                        p.get("puuid"),
                        p.get("name"),
                        p.get("tag"),
                        p.get("team"),
                        p.get("party_id"),
                        stats.get("kills"),
                        stats.get("deaths"),
                        stats.get("assists"),
                        stats.get("score"),
                        stats.get("headshots_percent"),
                        stats.get("damage_made"),
                    ),
                )
            await db.commit()

    # -------- helpers --------
    async def resolve_target(self, interaction: discord.Interaction, user: Optional[discord.User], region: Optional[str]) -> Optional[Tuple[str, str, str]]:
        target = user or interaction.user
        linked = await self.get_link(target.id)
        if not linked:
            await interaction.response.send_message("No Riot account linked. Use `/valorant link <name> <tag>`.", ephemeral=True)
            return None
        name, tag = linked
        return name, tag, region or DEFAULT_REGION

    def find_player(self, match: Dict[str, Any], name: str, tag: str) -> Optional[Dict[str, Any]]:
        players = match.get("players", {}).get("all_players", []) or []
        for p in players:
            if p.get("name", "").lower() == name.lower() and p.get("tag", "").lower() == tag.lower():
                return p
        return None

    def format_party_groups(self, match: Dict[str, Any]) -> List[str]:
        parties: Dict[str, List[str]] = {}
        for p in match.get("players", {}).get("all_players", []):
            pid = p.get("party_id") or "solo"
            parties.setdefault(pid, []).append(f"{p.get('name')}#{p.get('tag')}")
        lines = []
        for pid, members in parties.items():
            label = "Solo" if pid == "solo" else f"Party {pid[:4]}"
            lines.append(f"{label}: {', '.join(members)}")
        return lines

    def smurf_score(self, level: Optional[int], rank_label: str, matches: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
        score = 0
        reasons: List[str] = []
        if level is not None:
            if level < 30:
                score += 40
                reasons.append("Account level < 30")
            elif level < 50:
                score += 20
                reasons.append("Account level < 50")
        low_rank = rank_label.startswith(("Iron", "Bronze", "Silver"))
        if matches:
            recent = matches[0]
            subject = self.find_player(recent, recent.get("player_name", ""), recent.get("player_tag", ""))
            # If find_player fails, just pick first player to avoid empty output
            subject = subject or (recent.get("players", {}).get("all_players", [])[:1] or [None])[0]
            if subject:
                stats = subject.get("stats", {}) or {}
                kd = stats.get("kills", 0) / max(1, stats.get("deaths", 1))
                adr = stats.get("damage_made", 0) / max(1, recent.get("metadata", {}).get("rounds_played", 1))
                hs = stats.get("headshots_percent", 0)
                if kd > 1.5 and low_rank:
                    score += 25
                    reasons.append(f"High KD {kd:.2f} vs low rank")
                if adr and adr > 150:
                    score += 10
                    reasons.append(f"High ADR {adr:.0f}")
                if hs and hs > 25:
                    score += 5
                    reasons.append(f"High HS% {hs:.0f}")
        score = min(score, 100)
        if score >= 70:
            reasons.insert(0, "Risk: High")
        elif score >= 40:
            reasons.insert(0, "Risk: Medium")
        else:
            reasons.insert(0, "Risk: Low")
        return score, reasons

    def mmr_fields(self, data: Dict[str, Any]) -> Tuple[str, int, int, List[int]]:
        current = data.get("current_data", {}) or {}
        tier = current.get("currenttierpatched", "Unranked")
        rr = current.get("ranking_in_tier", 0)
        delta = current.get("mmr_change_to_last_game", 0)
        history = data.get("mmr_change_to_last_game", [])
        history_vals = history if isinstance(history, list) else []
        return tier, rr, delta, history_vals

    # -------- commands --------
    @app_commands.command(name="link", description="Link your Riot name and tag for Valorant lookups.")
    async def link(self, interaction: discord.Interaction, riot_name: str, riot_tag: str):
        if not VAL_API_KEY:
            await interaction.response.send_message("VAL_API_KEY missing in .env", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        acct = await self.api.account(riot_name, riot_tag)
        if not acct or "data" not in acct:
            await interaction.followup.send("Account not found. Check spelling/case.", ephemeral=True)
            return
        puuid = acct.get("data", {}).get("puuid")
        await self.set_link(interaction.user.id, riot_name, riot_tag, puuid)
        await interaction.followup.send(f"Linked to {riot_name}#{riot_tag} ({DEFAULT_REGION}).", ephemeral=True)

    @app_commands.command(name="unlink", description="Remove your linked Valorant account.")
    async def unlink(self, interaction: discord.Interaction):
        await self.clear_link(interaction.user.id)
        await interaction.response.send_message("Unlinked your Valorant account.", ephemeral=True)

    @app_commands.command(name="mmr", description="Show rank/RR and recent RR changes.")
    async def mmr(self, interaction: discord.Interaction, user: Optional[discord.User] = None, region: Optional[str] = None):
        if not VAL_API_KEY:
            await interaction.response.send_message("VAL_API_KEY missing in .env", ephemeral=True)
            return
        resolved = await self.resolve_target(interaction, user, region)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        mmr_resp = await self.api.mmr(name, tag, reg)
        if not mmr_resp or "data" not in mmr_resp:
            await interaction.followup.send("MMR data unavailable.", ephemeral=True)
            return
        tier, rr, delta, history = self.mmr_fields(mmr_resp["data"])
        embed = discord.Embed(
            title=f"{name}#{tag} • {reg.upper()}",
            description=f"{tier} ({rr} RR)",
            color=discord.Color.red(),
        )
        embed.add_field(name="Last RR change", value=str(delta), inline=True)
        if history:
            embed.add_field(name="Recent RR changes", value=" → ".join(str(x) for x in history[:5]), inline=False)
        embed.set_footer(text="Data via HenrikDev Valorant API")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="lastmatch", description="Show your last competitive match summary.")
    async def lastmatch(self, interaction: discord.Interaction, user: Optional[discord.User] = None, region: Optional[str] = None):
        if not VAL_API_KEY:
            await interaction.response.send_message("VAL_API_KEY missing in .env", ephemeral=True)
            return
        resolved = await self.resolve_target(interaction, user, region)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        matches = await self.api.matches(name, tag, reg, size=1)
        if not matches or not matches.get("data"):
            await interaction.followup.send("No recent matches found.", ephemeral=True)
            return
        match = matches["data"][0]
        await self.store_match(match)
        meta = match.get("metadata", {}) or {}
        players = match.get("players", {}).get("all_players", []) or []
        subject = self.find_player(match, name, tag) or (players[0] if players else None)
        stats = subject.get("stats", {}) if subject else {}
        kd_line = f"K/D/A: {stats.get('kills', 0)}/{stats.get('deaths', 0)}/{stats.get('assists', 0)}"
        embed = discord.Embed(
            title=f"{meta.get('map')} • {meta.get('mode')}",
            description=kd_line,
            color=discord.Color.green(),
        )
        red = match.get("teams", {}).get("red", {})
        blue = match.get("teams", {}).get("blue", {})
        embed.add_field(name="Score", value=f"{red.get('rounds_won', '?')} - {blue.get('rounds_won', '?')}", inline=True)
        embed.add_field(name="HS%", value=str(stats.get("headshots_percent", "n/a")), inline=True)
        embed.add_field(name="ADR", value=str(stats.get("damage_made", "n/a")), inline=True)
        parties = self.format_party_groups(match)
        if parties:
            embed.add_field(name="Parties", value="\n".join(parties[:6]), inline=False)
        embed.set_footer(text="Data via HenrikDev Valorant API")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="live", description="Check if a player is in a live match.")
    async def live(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        if not VAL_API_KEY:
            await interaction.response.send_message("VAL_API_KEY missing in .env", ephemeral=True)
            return
        resolved = await self.resolve_target(interaction, user, None)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        live_resp = await self.api.live(name, tag)
        if not live_resp or not live_resp.get("data"):
            await interaction.followup.send("Not in a live match.", ephemeral=True)
            return
        data = live_resp["data"]
        meta = data.get("metadata", {}) or {}
        players = data.get("players", {}).get("all_players", []) or []
        player_lines = [f"{p.get('team', '?')} • {p.get('name')}#{p.get('tag')} ({p.get('character')})" for p in players[:10]]
        embed = discord.Embed(
            title=f"Live: {meta.get('map')} • {meta.get('mode')}",
            description="\n".join(player_lines) or "Players unavailable",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Round", value=str(meta.get("round", "0")), inline=True)
        embed.add_field(name="Server", value=str(meta.get("cluster", "")), inline=True)
        embed.set_footer(text="Data via HenrikDev Valorant API")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="party", description="Show party groupings from the last match.")
    async def party(self, interaction: discord.Interaction, user: Optional[discord.User] = None, region: Optional[str] = None):
        resolved = await self.resolve_target(interaction, user, region)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        matches = await self.api.matches(name, tag, reg, size=1)
        if not matches or not matches.get("data"):
            await interaction.followup.send("No match found to extract parties.", ephemeral=True)
            return
        match = matches["data"][0]
        parties = self.format_party_groups(match)
        if not parties:
            await interaction.followup.send("Party info unavailable.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Party breakdown",
            description="\n".join(parties[:10]),
            color=discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="smurf", description="Estimate smurf risk based on level, rank, and performance.")
    async def smurf(self, interaction: discord.Interaction, user: Optional[discord.User] = None, region: Optional[str] = None):
        if not VAL_API_KEY:
            await interaction.response.send_message("VAL_API_KEY missing in .env", ephemeral=True)
            return
        resolved = await self.resolve_target(interaction, user, region)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        acct = await self.api.account(name, tag)
        mmr_resp = await self.api.mmr(name, tag, reg)
        matches_resp = await self.api.matches(name, tag, reg, size=3) or {"data": []}
        level = acct.get("data", {}).get("account_level") if acct else None
        rank_label = ""
        if mmr_resp and mmr_resp.get("data"):
            rank_label = mmr_resp["data"].get("current_data", {}).get("currenttierpatched", "") or ""
        score, reasons = self.smurf_score(level, rank_label, matches_resp.get("data", []))
        embed = discord.Embed(
            title=f"Smurf probability: {score}%",
            description="\n".join(reasons),
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="Account level", value=str(level or "n/a"), inline=True)
        embed.add_field(name="Rank", value=rank_label or "Unranked", inline=True)
        embed.set_footer(text="Heuristic only. Not official MMR.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="stats", description="Recent competitive stats (winrate, KD, ADR, HS).")
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None, region: Optional[str] = None):
        resolved = await self.resolve_target(interaction, user, region)
        if not resolved:
            return
        name, tag, reg = resolved
        await interaction.response.defer(thinking=True)
        matches = await self.api.matches(name, tag, reg, size=10)
        if not matches or not matches.get("data"):
            await interaction.followup.send("No matches to summarize.", ephemeral=True)
            return
        data = matches["data"]
        kd_sum = 0.0
        hs_sum = 0.0
        adr_sum = 0.0
        wins = 0
        count = 0
        for m in data:
            subject = self.find_player(m, name, tag) or (m.get("players", {}).get("all_players", [])[:1] or [None])[0]
            if not subject:
                continue
            stats = subject.get("stats", {}) or {}
            kd_sum += stats.get("kills", 0) / max(1, stats.get("deaths", 1))
            hs_sum += stats.get("headshots_percent", 0)
            adr_sum += stats.get("damage_made", 0) / max(1, m.get("metadata", {}).get("rounds_played", 1))
            team = subject.get("team")
            teams = m.get("teams", {}) or {}
            if team == "Red" and teams.get("red", {}).get("has_won"):
                wins += 1
            if team == "Blue" and teams.get("blue", {}).get("has_won"):
                wins += 1
            count += 1
        if count == 0:
            await interaction.followup.send("Could not parse recent stats.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Recent stats • {name}#{tag}",
            color=discord.Color.teal(),
        )
        embed.add_field(name="Winrate", value=f"{(wins / count) * 100:.0f}% ({wins}/{count})", inline=True)
        embed.add_field(name="Avg KD", value=f"{kd_sum / count:.2f}", inline=True)
        embed.add_field(name="Avg ADR", value=f"{adr_sum / count:.0f}", inline=True)
        embed.add_field(name="Avg HS%", value=f"{hs_sum / count:.0f}%", inline=True)
        embed.set_footer(text="Last 10 competitive matches")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ValorantCog(bot))
