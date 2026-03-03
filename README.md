# House of Kith Bot

A custom Discord bot I built for the House of Kith server.

Still a work in progress, but the core features are stable and running.
It has utility commands, role setup helpers, archive reactions, tarot reads, and an AI voice feature for horror-style messages.

## What it does right now

- Prefix commands:
  - `!kith wake up` -> runs a diagnostics/status check
  - `!about` -> shows bot info/version
  - `!restart` -> owner-only restart command
  - `!omen [text]` -> reads a creepy line in voice (or your custom text)
  - `!setup_roles` -> posts self-role panels
- Auto archive:
  - React with candle emoji (`🕯️`) to save messages into the archive channel
- Slash commands:
  - Tarot: `/tarot`, `/tarotspread`
  - Valorant (optional if API key is set): `/valorant link`, `/valorant mmr`, `/valorant lastmatch`, and more

## Inactive modules (kept in repo)

- `cogs/ghost_game.py`
- `cogs/megamind.py`

These are parked for now and not loaded at startup.

## Tech stack

- Python 3.11+
- `discord.py`
- OpenAI API (text + TTS)
- Optional: HenrikDev Valorant API

## Quick start (Windows / PowerShell)

1. Create venv:
   ```powershell
   py -m venv venv
   ```
2. Activate venv:
   ```powershell
   .\venv\Scripts\activate
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Create env file:
   ```powershell
   Copy-Item .env.example .env
   ```
5. Fill in your real tokens/IDs in `.env`.
6. Run:
   ```powershell
   .\kithbot.bat
   ```

## Required environment variables

- `DISCORD_TOKEN`
- `OPENAI_API_KEY`

## Optional environment variables

- `BOT_DEVELOPER`
- `BOT_CREATED_ON`
- `BOT_VERSION`
- `BOT_STATUS_CHANNEL_ID`
- `BOT_OWNER_ID`
- `VAL_API_KEY`
- `VAL_REGION` (default: `na`)

## Before pushing to GitHub

- Keep `.env` private (already ignored).
- Runtime voice files and local DB files are ignored in `.gitignore`.
- If you already tracked generated files before ignore rules, untrack them once:
  ```powershell
  git rm --cached sounds/ai_voice/*.wav data/valorant.db data/stats.json data/tarot_daily.json data/bot_status_message_id.txt
  ```

## Notes

Built for real server use first, polish second.
The code is organized enough to extend, but still reflects active development.

