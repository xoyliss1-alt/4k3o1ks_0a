import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0").strip()

if not BOT_TOKEN:
    raise RuntimeError("Переменная BOT_TOKEN не найдена! Добавьте токен в Render → Environment.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError as exc:
    raise RuntimeError("ADMIN_ID должен быть числом Telegram ID администратора.") from exc
