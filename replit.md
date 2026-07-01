# UnityBot

A Telegram bot built with Python, Pyrogram, and MongoDB (Motor).

## Stack
- **Python 3.12**
- **Pyrogram 2.0.106** — Telegram MTProto client
- **Motor** — async MongoDB driver
- **python-dotenv** — env loading (credentials live in Replit Secrets)

## How to run
The workflow `Start application` runs `python bot.py`.

Start it from the Replit workflow panel. Logs appear in the console output.

## Credentials (Replit Secrets)
All secrets are stored in Replit Secrets — never in `.env` or code:
- `API_ID` — Telegram API ID
- `API_HASH` — Telegram API Hash
- `BOT_TOKEN` — Bot token from @BotFather
- `OWNER_ID` — Telegram user ID of the bot owner
- `MONGO_URI` — MongoDB connection string

## Project structure
| File | Purpose |
|------|---------|
| `bot.py` | Entry point — creates the Pyrogram Client and registers handlers |
| `config.py` | Loads secrets from environment |
| `database.py` | MongoDB collections (users, referrals, daily, videos, premium, logs) |
| `start.py` | `/start` command handler |
| `help.py` | `/help` command handler |
| `profile.py` | `/profile` command handler |
| `helpers.py` | Utility functions (time helpers) |

## Notes
- `*.session` and `*.session-journal` are gitignored — never commit Pyrogram session files.
- `/daily` and `/referral` are not yet implemented.
