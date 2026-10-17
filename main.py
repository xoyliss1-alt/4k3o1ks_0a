import asyncio
import logging
import os
import sys
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Берем токен из переменных окружения Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "xoyli"

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN:
    sys.exit("Ошибка: Переменная BOT_TOKEN не найдена!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("voodoo_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    referrer_id INTEGER DEFAULT 0,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    url TEXT
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""
)

cursor.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_reward', '1')"
)
cursor.execute(
    "INSERT OR IGNORE INTO channels (channel_id, url) VALUES ('@voodoo_channels', 'https://t.me/voodoo_channels')"
)
conn.commit()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_reward_amount():
    cursor.execute("SELECT value FROM settings WHERE key = 'referral_reward'")
    res = cursor.fetchone()
    return float(res[0]) if res else 1.0


def set_reward_amount(val: float):
    cursor.execute(
        "UPDATE settings SET value = ? WHERE key = 'referral_reward'",
        (str(val),),
    )
    conn.commit()


def get_channels():
    cursor.execute("SELECT channel_id, url FROM channels")
    return cursor.fetchall()


async def check_subscriptions(user_id: int) -> bool:
    channels = get_channels()
    for ch_id, _ in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logging.error(f"Ошибка проверки подписки на {ch_id}: {e}")
            return False
    return True


class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_reward = State()


def main_menu_kb():
    kb = [
        [
            KeyboardButton(text="👤 Мой профиль"),
            KeyboardButton(text="⭐ Баланс"),
        ],
        [
            KeyboardButton(text="🎁 Заработать звезды"),
            KeyboardButton(text="📥 Вывести звезды"),
        ],
        [KeyboardButton(text="ℹ️ О проекте")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


async def sub_check_kb(user_id: int):
    channels = get_channels()
    builder = []
    for ch_id, url in channels:
        builder.append(
            [InlineKeyboardButton(text=f"Подписаться ({ch_id})", url=url)]
        )
    builder.append(
        [
            InlineKeyboardButton(
                text="✅ Я подписался", callback_data="check_sub_again"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=builder)


def admin_kb():
    kb = [
        [
            InlineKeyboardButton(
                text="➕ Добавить канал", callback_data="admin_add_channel"
            ),
            InlineKeyboardButton(
                text="➖ Удалить канал", callback_data="admin_del_channel"
            ),
        ],
        [
            InlineKeyboardButton(
                text="✏️ Изменить награду", callback_data="admin_set_reward"
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ХЭНДЛЕРЫ ---


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Пользователь"

    args = message.text.split()
    referrer_id = 0
    if len(args) > 1 and args[1].isdigit():
        possible_ref = int(args[1])
        if possible_ref != user_id:
            referrer_id = possible_ref

    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    existing_user = cursor.fetchone()

    if not existing_user:
        cursor.execute(
            "INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)",
            (user_id, username, referrer_id),
        )
        conn.commit()

    is_subbed = await check_subscriptions(user_id)
    if not is_subbed:
        await message.answer(
            "⚠️ **Для использования бота необходимо подписаться на наши каналы!**",
            reply_markup=await sub_check_kb(user_id),
            parse_mode="Markdown",
        )
        return

    await process_referral_reward(user_id)

    welcome_text = (
        "🌟 **Добро пожаловать в VoodooGifi!** 🌟\n\n"
        f"👋 Привет, {message.from_user.first_name}!\n"
        "🚀 Получай звезды за приглашение людей! VoodooGifi кормит!\n\n"
        "✨ Зарабатывай Telegram Stars, собирай команду друзей и выводи их в любое время!\n\n"
        "👇 Выбери нужный раздел в меню:"
    )
    await message.answer(
        welcome_text, reply_markup=main_menu_kb(), parse_mode="Markdown"
    )


async def process_referral_reward(user_id: int):
    cursor.execute(
        "SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)
    )
    res = cursor.fetchone()
    if res and res[0] != 0:
        referrer_id = res[0]
        reward = get_reward_amount()

        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (reward, referrer_id),
        )
        cursor.execute(
            "UPDATE users SET referrer_id = 0 WHERE user_id = ?", (user_id,)
        )
        conn.commit()

        try:
            await bot.send_message(
                referrer_id,
                f"🎉 По вашей ссылке зарегистрировался и подписался новый пользователь! Вам начислено: **{reward} ⭐**",
                parse_mode="Markdown",
            )
        except Exception:
            pass


@dp.callback_query(F.data == "check_sub_again")
async def check_sub_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    if await check_subscriptions(user_id):
        await call.message.delete()
        await process_referral_reward(user_id)
        await call.message.answer(
            "✅ Подписка подтверждена! Добро пожаловать в меню.",
            reply_markup=main_menu_kb(),
        )
    else:
        await call.answer(
            "❌ Вы подписались не на все каналы!", show_alert=True
        )


@dp.message(F.text == "👤 Мой профиль")
async def profile_handler(message: types.Message):
    if not await check_subscriptions(message.from_user.id):
        return await message.answer(
            "⚠️ Подпишитесь на каналы!",
            reply_markup=await sub_check_kb(message.from_user.id),
        )

    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)
    )
    balance = cursor.fetchone()[0]

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"

    text = (
        f"👤 **Ваш профиль:**\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"⭐ Баланс: **{balance} Stars**\n\n"
        f"🔗 Ваша реферальная ссылка:\n`{ref_link}`"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "⭐ Баланс")
async def balance_handler(message: types.Message):
    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)
    )
    balance = cursor.fetchone()[0]
    await message.answer(
        f"⭐ Ваш текущий баланс: **{balance} Telegram Stars**",
        parse_mode="Markdown",
    )


@dp.message(F.text == "🎁 Заработать звезды")
async def earn_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    reward = get_reward_amount()

    text = (
        f"🚀 **Зарабатывай Stars вместе с нами!**\n\n"
        f"Приглашай друзей по своей ссылке и получай **{reward} ⭐** за каждого подписавшегося!\n\n"
        f"Твоя ссылка для приглашений:\n`{ref_link}`"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "📥 Вывести звезды")
async def withdraw_handler(message: types.Message):
    await message.answer(
        "💸 Минимальная сумма для вывода: **50 Stars**.\nКопите звезды и возвращайтесь!",
        parse_mode="Markdown",
    )


@dp.message(F.text == "ℹ️ О проекте")
async def about_handler(message: types.Message):
    await message.answer(
        "ℹ️ **VoodooGifi** — лучший бот для заработка Telegram Stars!\nПриглашайте друзей и выводите реальные звезды.",
        parse_mode="Markdown",
    )


# --- АДМИН-ПАНЕЛЬ ---


@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if (
        message.from_user.username
        and message.from_user.username.lower() == ADMIN_USERNAME.lower()
    ):
        await message.answer(
            "⚙️ **Административная панель @xoyli:**",
            reply_markup=admin_kb(),
            parse_mode="Markdown",
        )
    else:
        await message.answer("❌ У вас нет доступа к админ-панели.")


@dp.callback_query(F.data == "admin_set_reward")
async def admin_set_reward_start(
    call: types.CallbackQuery, state: FSMContext
):
    await call.message.answer(
        "Введите новое количество звезд за 1 приглашенного человека:"
    )
    await state.set_state(AdminStates.waiting_for_reward)


@dp.message(AdminStates.waiting_for_reward)
async def admin_set_reward_process(
    message: types.Message, state: FSMContext
):
    try:
        val = float(message.text)
        set_reward_amount(val)
        await message.answer(f"✅ Награда за реферала успешно изменена на {val} ⭐")
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число!")


@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_ch_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "Введите юзернейм или ID канала (например: `@voodoo_channels`):",
        parse_mode="Markdown",
    )
    await state.set_state(AdminStates.waiting_for_channel_id)


@dp.message(AdminStates.waiting_for_channel_id)
async def admin_add_ch_id(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer(
        "Теперь введите ссылку на канал (например: `https://t.me/voodoo_channels`):",
        parse_mode="Markdown",
    )
    await state.set_state(AdminStates.waiting_for_channel_url)


@dp.message(AdminStates.waiting_for_channel_url)
async def admin_add_ch_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data["ch_id"]
    url = message.text

    cursor.execute(
        "INSERT OR REPLACE INTO channels (channel_id, url) VALUES (?, ?)",
        (ch_id, url),
    )
    conn.commit()

    await message.answer(
        f"✅ Канал {ch_id} успешно добавлен в обязательные подписки!"
    )
    await state.clear()


@dp.callback_query(F.data == "admin_del_channel")
async def admin_del_ch(call: types.CallbackQuery):
    channels = get_channels()
    if not channels:
        return await call.message.answer("Список обязательных каналов пуст.")

    builder = []
    for ch_id, _ in channels:
        builder.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Удалить {ch_id}",
                    callback_data=f"del_ch_{ch_id}",
                )
            ]
        )

    await call.message.answer(
        "Выберите канал для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder),
    )


@dp.callback_query(F.data.startswith("del_ch_"))
async def admin_del_ch_confirm(call: types.CallbackQuery):
    ch_id = call.data.replace("del_ch_", "")
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch_id,))
    conn.commit()
    await call.message.answer(f"✅ Канал {ch_id} удален из обязательных!")


# --- HTTP HEALTH CHECK FOR RENDER ---
async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "VoodooGifi"})


async def start_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/healthz", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("Health server listening on 0.0.0.0:%s", port)
    return runner


# --- ЗАПУСК БОТА ---
async def main():
    runner = await start_health_server()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
