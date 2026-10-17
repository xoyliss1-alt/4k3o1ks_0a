import aiosqlite

DB_NAME = "woodoo_gifi.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            balance INTEGER DEFAULT 0,
            invited_count INTEGER DEFAULT 0
        )""")
        # Таблица настроек
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # Таблица каналов
        await db.execute("""CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY
        )""")
        
        # Стандартная награда за приглашение (10 звезд)
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('reward', '10')")
        # Добавляем главный канал (он всегда в базе)
        await db.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", ("@voodoo_channels",))
        await db.commit()

async def add_user(user_id: int, referrer_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not await cursor.fetchone():
            await db.execute("INSERT INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
            if referrer_id:
                # Начисляем звезды пригласившему
                cursor = await db.execute("SELECT value FROM settings WHERE key = 'reward'")
                reward = int((await cursor.fetchone())[0])
                await db.execute("UPDATE users SET balance = balance + ?, invited_count = invited_count + 1 WHERE user_id = ?", (reward, referrer_id))
            await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def get_all_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT channel_id FROM channels")
        return [row[0] for row in await cursor.fetchall()]

async def add_channel(channel_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (channel_id,))
        await db.commit()

async def remove_channel(channel_id: str):
    # ЗАЩИТА: главный канал удалить нельзя
    if channel_id == "@voodoo_channels":
        return False
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        await db.commit()
    return True

async def get_setting(key: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        res = await cursor.fetchone()
        return res[0] if res else None

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
        await db.commit()

async def withdraw_stars(user_id: int, amount: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = (await cursor.fetchone())[0]
        if balance >= amount:
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            await db.commit()
            return True
        return False
