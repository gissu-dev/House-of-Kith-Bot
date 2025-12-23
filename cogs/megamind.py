import asyncio
from pathlib import Path
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

SCENE_DIR = Path("data/megamind_scenes")
SCENE_DIR.mkdir(parents=True, exist_ok=True)

FRAME_DELIMITER = "\n---\n"


def load_scene_frames(path: Path) -> List[str]:
    """Load frames from a scene file, splitting on FRAME_DELIMITER."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    parts = [p.strip("\n") for p in text.split(FRAME_DELIMITER)]
    return [p for p in parts if p.strip()]


class MegamindCog(commands.GroupCog, name="megamind"):
    """Play short ASCII Megamind scenes."""

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.scenes: Dict[str, List[str]] = self.load_all_scenes()
        self.playing_tasks: Dict[int, asyncio.Task] = {}
        self.stop_flags: Dict[int, asyncio.Event] = {}

    # -------- scene loading --------
    def load_all_scenes(self) -> Dict[str, List[str]]:
        scenes: Dict[str, List[str]] = {}
        for file in SCENE_DIR.glob("*.txt"):
            frames = load_scene_frames(file)
            if frames:
                scenes[file.stem] = frames
        return scenes

    def available_scene_names(self) -> List[str]:
        return sorted(self.scenes.keys())

    def scene_frames(self, name: str) -> Optional[List[str]]:
        return self.scenes.get(name.lower())

    # -------- helpers --------
    async def stop_playback(self, channel_id: int):
        flag = self.stop_flags.get(channel_id)
        if flag:
            flag.set()
        task = self.playing_tasks.get(channel_id)
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=2)
            except asyncio.TimeoutError:
                task.cancel()
        self.playing_tasks.pop(channel_id, None)
        self.stop_flags.pop(channel_id, None)

    def render_frame(self, scene: str, frame: str, idx: int, total: int, delay: float) -> str:
        lines = frame.splitlines() or [frame]
        width = min(68, max(len(line) for line in lines) + 2)
        header = f"{scene} | {idx}/{total} | {delay:.2f}s"
        progress_len = 24
        filled = int(progress_len * (idx / max(1, total)))
        bar = "[" + "#" * filled + "-" * (progress_len - filled) + "]"
        top_border = "+" + "-" * width + "+"
        body = "\n".join(f"| {line.ljust(width-2)}|" for line in lines)
        return "```txt\n" + "\n".join(
            [
                header,
                bar,
                top_border,
                body,
                top_border,
                "static: . : *  .  . :",
            ]
        ) + "\n```"

    async def run_scene(
        self,
        channel: discord.abc.Messageable,
        channel_id: int,
        scene_name: str,
        frames: List[str],
        delay: float = 0.28,
    ):
        stop_flag = asyncio.Event()
        self.stop_flags[channel_id] = stop_flag

        try:
            if not frames:
                await channel.send("No frames to play.")
                return

            total = len(frames)
            msg = await channel.send(self.render_frame(scene_name, frames[0], 1, total, delay))
            for i, frame in enumerate(frames[1:], start=2):
                if stop_flag.is_set():
                    break
                await asyncio.sleep(delay)
                try:
                    await msg.edit(content=self.render_frame(scene_name, frame, i, total, delay))
                except discord.HTTPException:
                    await channel.send(self.render_frame(scene_name, frame, i, total, delay))

            if not stop_flag.is_set():
                await channel.send(
                    embed=discord.Embed(
                        title="Megamind - Scene finished",
                        description="PRESENTATION!",
                        color=discord.Color.blurple(),
                    ).set_footer(text="Run /megamind list to see other scenes.")
                )
            else:
                await channel.send("Playback stopped.")
        finally:
            self.playing_tasks.pop(channel_id, None)
            self.stop_flags.pop(channel_id, None)

    async def start_playback(self, channel: discord.abc.Messageable, scene: str, frames: List[str], delay: float):
        channel_id = channel.id if isinstance(channel, discord.TextChannel) else id(channel)
        if channel_id in self.playing_tasks:
            await channel.send("A Megamind scene is already playing here. Use `/megamind stop`.")
            return
        intro = discord.Embed(
            title=f"Megamind: {scene}",
            description=f"Frames: {len(frames)} | Speed: {delay:.2f}s per frame\nUse `/megamind stop` to cancel.",
            color=discord.Color.blurple(),
        )
        await channel.send(embed=intro)
        task = asyncio.create_task(self.run_scene(channel, channel_id, scene, frames, delay=delay))
        self.playing_tasks[channel_id] = task

    def scene_list_text(self) -> str:
        names = self.available_scene_names()
        return ", ".join(names) if names else "No scenes found."

    # -------- slash commands --------
    @app_commands.command(name="play", description="Play an ASCII Megamind scene.")
    @app_commands.describe(scene="Scene name (default: villain_vs_super)", speed="Seconds between frames (0.15-1.0)")
    async def play_slash(self, interaction: discord.Interaction, scene: Optional[str] = None, speed: float = 0.28):
        scene_name = (scene or "villain_vs_super").lower()
        frames = self.scene_frames(scene_name)
        if not frames:
            await interaction.response.send_message(
                f"Scene `{scene_name}` not found. Available: {self.scene_list_text()}",
                ephemeral=True,
            )
            return

        delay = min(1.0, max(0.15, speed))
        await interaction.response.send_message(
            f"Playing `{scene_name}` ({len(frames)} frames) at {delay:.2f}s/frame.",
            ephemeral=True,
        )
        await self.start_playback(interaction.channel, scene_name, frames, delay)

    @app_commands.command(name="list", description="List available Megamind scenes.")
    async def list_slash(self, interaction: discord.Interaction):
        names = self.available_scene_names()
        desc = "\n".join(f"- {n} ({len(self.scenes[n])} frames)" for n in names) if names else "No scenes found."
        await interaction.response.send_message(
            embed=discord.Embed(title="Megamind scenes", description=desc, color=discord.Color.blurple()),
            ephemeral=True,
        )

    @app_commands.command(name="stop", description="Stop the current Megamind playback.")
    async def stop_slash(self, interaction: discord.Interaction):
        channel_id = interaction.channel.id if interaction.channel else 0
        if channel_id not in self.playing_tasks:
            await interaction.response.send_message("Nothing is playing here.", ephemeral=True)
            return
        await self.stop_playback(channel_id)
        await interaction.response.send_message("Stopped playback.", ephemeral=True)

    # -------- prefix commands --------
    @commands.group(name="megamind", invoke_without_command=True)
    async def megamind_group(self, ctx: commands.Context, *, scene: Optional[str] = None):
        await self.play_prefix(ctx, scene=scene)

    @megamind_group.command(name="play")
    async def play_prefix(self, ctx: commands.Context, *, scene: Optional[str] = None):
        scene_name = (scene or "villain_vs_super").lower()
        frames = self.scene_frames(scene_name)
        if not frames:
            await ctx.send(f"Scene `{scene_name}` not found. Available: {self.scene_list_text()}")
            return
        await ctx.send(f"Playing `{scene_name}` ({len(frames)} frames).")
        await self.start_playback(ctx.channel, scene_name, frames, delay=0.28)

    @megamind_group.command(name="list")
    async def list_prefix(self, ctx: commands.Context):
        names = self.available_scene_names()
        desc = "\n".join(f"- {n} ({len(self.scenes[n])} frames)" for n in names) if names else "No scenes found."
        await ctx.send(embed=discord.Embed(title="Megamind scenes", description=desc, color=discord.Color.blurple()))

    @megamind_group.command(name="stop")
    async def stop_prefix(self, ctx: commands.Context):
        channel_id = ctx.channel.id if ctx.channel else 0
        if channel_id not in self.playing_tasks:
            await ctx.send("Nothing is playing here.")
            return
        await self.stop_playback(channel_id)
        await ctx.send("Stopped playback.")


async def setup(bot: commands.Bot):
    await bot.add_cog(MegamindCog(bot))
