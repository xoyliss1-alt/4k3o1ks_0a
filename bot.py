import os
import logging
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# -------------------------------------------------------------------
# КОНФИГУРАЦИЯ БОТА И БАЗЫ ДАННЫХ
# -------------------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # URL подключения к PostgreSQL на Render
ADMIN_USERNAME = "xoyli"                  # Никнейм главного админа без @

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
pool = None  # Пул соединений PostgreSQL


# FSM Состояния для админ-панели
class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_reward = State()


# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ POSTGRESQL
# -------------------------------------------------------------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(dsn=DATABASE_URL)
    
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INT DEFAULT 0,
                referrer_id BIGINT,
                is_bot_verified BOOLEAN DEFAULT FALSE
            );
        ''')
        # Таблица обязательных каналов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                url TEXT NOT NULL
            );
        ''')
        # Таблица настроек (награда за реферала)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value INT NOT NULL
            );
        ''')
        # Значения по умолчанию
        await conn.execute('''
            INSERT INTO settings (key, value) VALUES ('star_reward', 5)
            ON CONFLICT (key) DO NOTHING;
        ''')
        await conn.execute('''
            INSERT INTO channels (channel_id, url) 
            VALUES ('@voodoo_channels', 'https://t.me/voodoo_channels')
            ON CONFLICT (channel_id) DO NOTHING;
        ''')


# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -------------------------------------------------------------------
async def get_channels():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT channel_id, url FROM channels;")

async def get_star_reward() -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'star_reward';")
        return row['value'] if row else 5

async def check_subscriptions(user_id: int) -> bool:
    channels = await get_channels()
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel['channel_id'], user_id=user_id)
            if member.status not in ["creator", "administrator", "member"]:
                return False
        except Exception:
            return False
    return True

async def get_sub_keyboard():
    channels = await get_channels()
    buttons = []
    for idx, ch in enumerate(channels, 1):
        buttons.append([InlineKeyboardButton(text=f"📢 Подписаться (Канал #{idx})", url=ch['url'])])
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_captcha_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="🤖 Я бот", callback_data="captcha_fail"),
            InlineKeyboardButton(text="👤 Я человек", callback_data="captcha_pass"),
            InlineKeyboardButton(text="🤖 Я бот", callback_data="captcha_fail")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
@dp.message(CommandStart())
async def start_cmd(message: Message):
    user_id = message.from_user.id

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", user_id)
        
        if not user:
            args = message.text.split()
            referrer_id = None
            if len(args) > 1 and args[1].isdigit():
                potential_ref = int(args[1])
                if potential_ref != user_id:
                    ref_exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1;", potential_ref)
                    if ref_exists:
                        referrer_id = potential_ref

            await conn.execute(
                "INSERT INTO users (user_id, balance, referrer_id, is_bot_verified) VALUES ($1, 0, $2, FALSE);",
                user_id, referrer_id
            )
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", user_id)

    # Проверка подписки
    is_subbed = await check_subscriptions(user_id)
    if not is_subbed:
        await message.answer(
            "⚠️ **Для работы с ботом необходимо подписаться на наш канал:**",
            reply_markup=await get_sub_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Проверка капчи
    if not user['is_bot_verified']:
        await message.answer(
            "🛡 **Защита от накрутки:** Пожалуйста, подтвердите, что вы человек:",
            reply_markup=get_captcha_keyboard()
        )
        return

    await send_main_menu(message)


@dp.callback_query(F.data == "captcha_pass")
async def process_captcha_pass(callback: CallbackQuery):
    user_id = callback.from_user.id
    reward = await get_star_reward()

    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_bot_verified = TRUE WHERE user_id = $1;", user_id)
        user = await conn.fetchrow("SELECT referrer_id FROM users WHERE user_id = $1;", user_id)
        
        referrer_id = user['referrer_id'] if user else None
        if referrer_id:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2;", reward, referrer_id)
            await conn.execute("UPDATE users SET referrer_id = NULL WHERE user_id = $1;", user_id)
            try:
                await bot.send_message(
                    referrer_id, 
                    f"🎉 По вашей ссылке зарегистрировался новый пользователь! Вам начислено **{reward} ⭐** (Звёзд).",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await callback.message.delete()
    await callback.message.answer("✅ Проверка успешно пройдена!")
    await send_main_menu(callback.message)


@dp.callback_query(F.data == "captcha_fail")
async def process_captcha_fail(callback: CallbackQuery):
    await callback.answer("❌ Неверно! Попробуйте снова через /start", show_alert=True)


@dp.callback_query(F.data == "check_sub")
async def process_check_sub(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_subbed = await check_subscriptions(user_id)
    
    if is_subbed:
        await callback.message.delete()
        async with pool.acquire() as conn:
            is_verified = await conn.fetchval("SELECT is_bot_verified FROM users WHERE user_id = $1;", user_id)
        
        if not is_verified:
            await callback.message.answer(
                "🛡 **Защита от накрутки:** Пожалуйста, подтвердите, что вы человек:",
                reply_markup=get_captcha_keyboard()
            )
        else:
            await send_main_menu(callback.message)
    else:
        await callback.answer("❌ Вы подписались не на все каналы!", show_alert=True)


async def send_main_menu(message: Message):
    user_id = message.chat.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    async with pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1;", user_id) or 0
    reward = await get_star_reward()

    text = (
        f"👋 **Главное меню**\n\n"
        f"⭐️ Ваш баланс: **{balance} ⭐ Telegram Stars**\n"
        f"🎁 Награда за 1 приглашённого друга: **{reward} ⭐**\n\n"
        f"🔗 Ваша реферальная ссылка:\n`{ref_link}`"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить меню", callback_data="refresh_menu")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "refresh_menu")
async def refresh_menu_cb(callback: CallbackQuery):
    await callback.message.delete()
    await send_main_menu(callback.message)


# -------------------------------------------------------------------
# АДМИН-ПАНЕЛЬ (Для @xoyli)
# -------------------------------------------------------------------
def is_admin(username: str) -> bool:
    return username and username.lower() == ADMIN_USERNAME.lower()


@dp.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if not is_admin(message.from_user.username):
        await message.answer("❌ У вас нет доступа к панели администратора.")
        return
    await send_admin_menu(message)


async def send_admin_menu(message: Message):
    channels = await get_channels()
    reward = await get_star_reward()
    channels_text = "\n".join([f"• {ch['channel_id']}" for ch in channels]) or "Нет каналов"
    
    text = (
        f"⚙️ **Админ-Панель (@{ADMIN_USERNAME})**\n\n"
        f"⭐️ Награда за реферала: **{reward} ⭐**\n"
        f"📢 Обязательные каналы:\n{channels_text}"
    )

    buttons = [
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="admin_del_channel")],
        [InlineKeyboardButton(text="✏️ Изменить награду (Звёзды)", callback_data="admin_change_reward")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "admin_change_reward")
async def admin_change_reward_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        return
    await callback.message.answer("Укажите новое количество ⭐ за одного реферала (введите число):")
    await state.set_state(AdminStates.waiting_for_reward)


@dp.message(AdminStates.waiting_for_reward)
async def admin_change_reward_process(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    
    new_reward = int(message.text)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE settings SET value = $1 WHERE key = 'star_reward';", new_reward)
        
    await state.clear()
    await message.answer(f"✅ Награда за реферала изменена на **{new_reward} ⭐**.")
    await send_admin_menu(message)


@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.username):
        return
    await callback.message.answer(
        "Пришлите username канала и ссылку через пробел.\n"
        "Пример:\n`@voodoo_channels https://t.me/voodoo_channels`",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_channel)


@dp.message(AdminStates.waiting_for_channel)
async def admin_add_channel_process(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Ошибка ввода. Укажите ID и ссылку через пробел.")
        return

    channel_id, channel_url = parts[0], parts[1]
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO channels (channel_id, url) VALUES ($1, $2) ON CONFLICT (channel_id) DO UPDATE SET url = $2;",
            channel_id, channel_url
        )
    await state.clear()
    await message.answer(f"✅ Канал `{channel_id}` добавлен.")
    await send_admin_menu(message)


@dp.callback_query(F.data == "admin_del_channel")
async def admin_del_channel_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.username):
        return

    channels = await get_channels()
    if not channels:
        await callback.answer("Список каналов пуст!", show_alert=True)
        return

    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Удалить {ch['channel_id']}", 
            callback_data=f"del_ch_{ch['channel_id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите канал для удаления:", reply_markup=kb)


@dp.callback_query(F.data.startswith("del_ch_"))
async def admin_del_channel_process(callback: CallbackQuery):
    ch_id = callback.data.replace("del_ch_", "")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM channels WHERE channel_id = $1;", ch_id)
    await callback.answer(f"Канал {ch_id} удален!")
    await callback.message.delete()
    await send_admin_menu(callback.message)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    await init_db()
    print("Бот и база данных PostgreSQL успешно запущены...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
