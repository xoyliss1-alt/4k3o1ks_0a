import asyncpg
from typing import Optional, List
from config import DATABASE_URL

pool: Optional[asyncpg.Pool] = None

async def init_db() -> None:
    global pool
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=10, max_size=50)

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(64) DEFAULT 'без_юзернейма',
                balance INT DEFAULT 0,
                referrer_id BIGINT DEFAULT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                username VARCHAR(64),
                bet INT NOT NULL,
                multiplier NUMERIC(5, 2) NOT NULL,
                win_amount INT NOT NULL,
                result VARCHAR(10) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS jackpot_bets (
                id SERIAL PRIMARY KEY,
                room_id INT NOT NULL,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                username VARCHAR(64),
                bet INT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

async def get_balance(user_id: int) -> Optional[int]:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)

async def update_balance_safe(user_id: int, amount: int) -> bool:
    """Атомарное обновление баланса с защитой от ухода в минус в рамках транзакции"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if amount < 0:
                current_balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if not current_balance or current_balance < abs(amount):
                    return False
            
            await conn.execute("""
                INSERT INTO users (user_id, balance)
                VALUES ($1, GREATEST(0, $2))
                ON CONFLICT (user_id) DO UPDATE 
                SET balance = GREATEST(0, users.balance + $2);
            """, user_id, amount)
            return True

async def register_user_with_referral(user_id: int, username: str, referrer_id: Optional[int] = None) -> bool:
    """Регистрация пользователя с защитой от накрутки рефералов"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Проверяем, существует ли уже пользователь
            exists = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", user_id)
            
            valid_ref = None
            if referrer_id and referrer_id != user_id:
                ref_exists = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", referrer_id)
                if ref_exists:
                    valid_ref = referrer_id

            if not exists:
                await conn.execute("""
                    INSERT INTO users (user_id, username, balance, referrer_id)
                    VALUES ($1, $2, 0, $3)
                """, user_id, username, valid_ref)
                return True if valid_ref else False
            else:
                await conn.execute("UPDATE users SET username=$1 WHERE user_id=$2", username, user_id)
                return False

async def get_referral_count(referrer_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", referrer_id)

async def add_jackpot_bet(room_id: int, user_id: int, username: str, bet: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO jackpot_bets (room_id, user_id, username, bet)
            VALUES ($1, $2, $3, $4)
        """, room_id, user_id, username, bet)

async def get_jackpot_room_bets(room_id: int) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT user_id, username, SUM(bet) as total_bet
            FROM jackpot_bets
            WHERE room_id = $1
            GROUP BY user_id, username
        """, room_id)

async def clear_jackpot_room(room_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM jackpot_bets WHERE room_id = $1", room_id)
