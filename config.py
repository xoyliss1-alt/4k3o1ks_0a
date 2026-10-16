import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment Variables.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

# Render supplies RENDER_EXTERNAL_URL automatically for a Web Service.
BASE_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
WEBAPP_URL = f"{BASE_URL}/app" if BASE_URL else ""
