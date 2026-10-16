# WoodooGifi Telegram Bot

Telegram bot built with Python, aiogram 3, aiohttp, and SQLite.

## Render deployment

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`
- Health check path: `/healthz`
- Required environment variable: `BOT_TOKEN` (token from @BotFather)
- Optional environment variable: `BOT_DB_PATH` (SQLite database file path; defaults to `bot.db`)

The bot exposes an HTTP health endpoint for Render and runs Telegram long polling. The SQLite database is stored on the service filesystem by default. On a free Render Web Service, local files are not persistent across all redeploys/restarts, so use persistent storage or an external database if user data must survive them.

## Run locally

```bash
python -m pip install -r requirements.txt
export BOT_TOKEN="your-token-here"
python main.py
```

On Windows PowerShell, set the token with `$env:BOT_TOKEN="your-token-here"` before running `python main.py`.
