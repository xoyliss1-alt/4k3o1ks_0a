import os
import aiosqlite

# Render'e yazma izni olan geçici dizin; DATABASE_PATH verilirse onu kullanır.
DB_PATH = os.getenv("DATABASE_PATH", "/tmp/woodoogifi.db")


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                referrals INTEGER NOT NULL DEFAULT 0,
                referrer_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel TEXT PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('reward', '1')"
        )
        await db.commit()


async def add_user(user_id: int, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        exists = await cursor.fetchone()
        if exists:
            return
        await db.execute(
            "INSERT INTO users (user_id, balance, referrals, referrer_id) VALUES (?, 0, 0, ?)",
            (user_id, referrer_id),
        )
        if referrer_id:
            cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
            if await cursor.fetchone():
                await db.execute(
                    "UPDATE users SET referrals = referrals + 1 WHERE user_id = ?",
                    (referrer_id,),
                )
                cursor = await db.execute("SELECT value FROM settings WHERE key = 'reward'")
                row = await cursor.fetchone()
                reward = int(row[0]) if row else 1
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (reward, referrer_id),
                )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, username, balance, referrals FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users (user_id, balance, referrals) VALUES (?, 0, 0)",
                (user_id,),
            )
            await db.commit()
            return (user_id, None, 0, 0)
        return row


async def get_all_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT channel FROM channels ORDER BY channel")
        return [row[0] for row in await cursor.fetchall()]


async def add_channel(channel: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO channels (channel) VALUES (?)", (channel,))
        await db.commit()


async def remove_channel(channel: str):
    if channel == "@voodoo_channels":
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM channels WHERE channel = ?", (channel,))
        await db.commit()
        return cursor.rowcount > 0


async def get_setting(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else "1"


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
