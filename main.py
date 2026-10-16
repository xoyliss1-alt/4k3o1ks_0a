import os
import asyncio
import logging
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            referred_by INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            channel_link TEXT,
            channel_name TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ref_reward', '3')")
    conn.commit()
    conn.close()

def get_setting(key: str, default: str) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, balance, referred_by FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_user(user_id: int, username: str, first_name: str, referred_by: int = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, balance, referred_by)
            VALUES (?, ?, ?, 0, ?)
        """, (user_id, username, first_name, referred_by))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def update_user_balance(user_id: int, amount: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def set_user_balance(user_id: int, value: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def get_channels():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_link, channel_name FROM channels")
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_channel(channel_id: str, channel_link: str, channel_name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels (channel_id, channel_link, channel_name) VALUES (?, ?, ?)", 
                   (channel_id, channel_link, channel_name))
    conn.commit()
    conn.close()

def remove_channel(channel_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_value = State()
    waiting_for_ref_reward = State()
    waiting_for_channel_id = State()
    waiting_for_channel_link = State()
    waiting_for_channel_name = State()

async def check_subscriptions(user_id: int) -> list:
    channels = get_channels()
    unsubscribed = []
    for ch_id, ch_link, ch_name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed.append((ch_link, ch_name))
        except Exception:
            pass
    return unsubscribed

# 💎 Красивое и современное меню с кнопками
def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [
            InlineKeyboardButton(text="⭐ Баланс", callback_data="balance"),
            InlineKeyboardButton(text="🎁 Заработать звезды", callback_data="earn_stars")
        ]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Изменить баланс пользователя", callback_data="adm_change_balance")],
        [InlineKeyboardButton(text="🎁 Награда за друга", callback_data="adm_ref_reward")],
        [InlineKeyboardButton(text="📢 Управление каналами", callback_data="adm_channels")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def channels_keyboard(channels) -> InlineKeyboardMarkup:
    buttons = []
    for ch_id, ch_link, ch_name in channels:
        buttons.append([InlineKeyboardButton(text=f"📢 Подписаться: {ch_name}", url=ch_link)])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args
    
    referrer_id = None
    if args and args.isdigit():
        ref_id = int(args)
        if ref_id != user_id:
            referrer_id = ref_id

    is_new = add_user(user_id, message.from_user.username or "", message.from_user.first_name, referrer_id)
    
    if is_new and referrer_id:
        ref_reward = int(get_setting("ref_reward", "3"))
        update_user_balance(referrer_id, ref_reward)
        try:
            await bot.send_message(referrer_id, f"🎉 По вашей ссылке перешел новый друг! Вам начислено **+{ref_reward} ⭐ звезд**.", parse_mode="Markdown")
        except Exception:
            pass

    unsubscribed = await check_subscriptions(user_id)
    if unsubscribed:
        channels = get_channels()
        await message.answer(
            "🔒 **Доступ ограничен!**\n\nДля использования бота подпишитесь на наши каналы ниже:",
            parse_mode="Markdown",
            reply_markup=channels_keyboard(channels)
        )
        return

    await message.answer(
        f"✨ **Добро пожаловать, {message.from_user.first_name}!**\n\n"
        f"Используйте интуитивное меню ниже для навигации по всем возможностям бота 👇",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery):
    user_id = callback.from_user.id
    unsubscribed = await check_subscriptions(user_id)
    if unsubscribed:
        await callback.answer("❌ Вы подписались еще не на все каналы!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"✅ **Подписка успешно подтверждена!**\n\nДобро пожаловать в главное меню ✨",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    unsubscribed = await check_subscriptions(user_id)
    if unsubscribed:
        channels = get_channels()
        await callback.message.edit_text(
            "🔒 **Доступ ограничен!**\n\nДля использования бота подпишитесь на наши каналы ниже:",
            parse_mode="Markdown",
            reply_markup=channels_keyboard(channels)
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "🎛️ **Главное меню**\n\nВыберите нужный раздел из списка ниже:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        add_user(callback.from_user.id, callback.from_user.username or "", callback.from_user.first_name)
        user = get_user(callback.from_user.id)
    
    user_id, username, first_name, balance, _ = user
    
    text = (
        f"👤 **Ваш профиль**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"🏷️ **Имя:** {first_name}\n"
        f"⭐ **Баланс:** `{balance}` звезд\n"
        f"━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    balance = user[3] if user else 0
    text = (
        f"⭐ **Состояние счета**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Ваш текущий баланс: **{balance} ⭐**\n"
        f"━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "earn_stars")
async def cb_earn_stars(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    ref_count = cursor.fetchone()[0]
    conn.close()

    ref_reward = get_setting("ref_reward", "3")
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    text = (
        f"🎁 **Заработок звезд**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Приглашайте друзей по вашей личной ссылке и получайте **{ref_reward} ⭐ звезд** за каждого приглашенного!\n\n"
        f"👥 Приглашено друзей: **{ref_count}**\n\n"
        f"🔗 **Ваша реферальная ссылка:**\n`{ref_link}`\n"
        f"━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Недостаточно прав.", show_alert=True)
        return
    text = "🛠️ **Панель администратора**\n\nВыберите действие:"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "adm_ref_reward")
async def cb_adm_ref_reward(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    current = get_setting("ref_reward", "3")
    await state.set_state(AdminStates.waiting_for_ref_reward)
    await callback.message.edit_text(
        f"🎁 **Награда за друга**\n\nТекущая награда: `{current}` звезд.\nВведите новое количество звезд за 1 друга:",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_ref_reward)
async def process_ref_reward(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите целое число.")
        return
    set_setting("ref_reward", message.text.strip())
    await message.answer(f"✅ Награда за друга изменена на **{message.text.strip()} ⭐**!", parse_mode="Markdown", reply_markup=main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "adm_channels")
async def cb_adm_channels(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    channels = get_channels()
    text = "📢 **Обязательные каналы**\n\nСписок каналов:\n"
    if not channels:
        text += "_Каналы отсутствуют._\n"
    else:
        for ch_id, ch_link, ch_name in channels:
            text += f"• {ch_name} (`{ch_id}`) — [Ссылка]({ch_link})\n"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="adm_add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="adm_del_channel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)
    await callback.answer()

@dp.callback_query(F.data == "adm_add_channel")
async def cb_adm_add_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.message.edit_text("📢 Введите ID канала (например, `-1001234567890` или `@username`):", reply_markup=back_keyboard())
    await callback.answer()

@dp.message(AdminStates.waiting_for_channel_id)
async def process_ch_id(message: Message, state: FSMContext):
    await state.update_data(ch_id=message.text.strip())
    await state.set_state(AdminStates.waiting_for_channel_link)
    await message.answer("🔗 Введите ссылку на канал (например, `https://t.me/...`):")

@dp.message(AdminStates.waiting_for_channel_link)
async def process_ch_link(message: Message, state: FSMContext):
    await state.update_data(ch_link=message.text.strip())
    await state.set_state(AdminStates.waiting_for_channel_name)
    await message.answer("📝 Введите название канала:")

@dp.message(AdminStates.waiting_for_channel_name)
async def process_ch_name(message: Message, state: FSMContext):
    data = await state.get_data()
    add_channel(data['ch_id'], data['ch_link'], message.text.strip())
    await message.answer("✅ Канал успешно добавлен!", reply_markup=main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "adm_del_channel")
async def cb_adm_del_channel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    channels = get_channels()
    if not channels:
        await callback.answer("Нет каналов для удаления.", show_alert=True)
        return
    buttons = []
    for ch_id, ch_link, ch_name in channels:
        buttons.append([InlineKeyboardButton(text=f"❌ Удалить: {ch_name}", callback_data=f"del_ch_{ch_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_channels")])
    await callback.message.edit_text("🗑 Выберите канал для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("del_ch_"))
async def cb_process_del_ch(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    ch_id = callback.data.replace("del_ch_", "")
    remove_channel(ch_id)
    await callback.answer("✅ Канал удален!", show_alert=True)
    channels = get_channels()
    text = "📢 **Обязательные каналы**\n\nСписок каналов:\n"
    if not channels:
        text += "_Каналы отсутствуют._\n"
    else:
        for cid, clink, cname in channels:
            text += f"• {cname} (`{cid}`) — [Ссылка]({clink})\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="adm_add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="adm_del_channel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

@dp.callback_query(F.data == "adm_change_balance")
async def cb_adm_change_balance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Отказано в доступе.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.message.edit_text(
        "🛠️ **Изменение баланса**\n\nВведите Telegram ID пользователя:",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите корректный числовой ID.")
        return
    target_id = int(message.text)
    user = get_user(target_id)
    if not user:
        await message.answer("❌ Пользователь не найден в базе. Попробуйте еще раз:")
        return

    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_for_value)
    await message.answer("Укажите новое значение баланса звезд (или используйте `+` / `-`, например: `+10` или `-5`):", parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_value)
async def process_value(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    text_val = message.text.strip()
    
    try:
        if text_val.startswith("+") or text_val.startswith("-"):
            val = int(text_val)
            update_user_balance(target_id, val)
        else:
            val = int(text_val)
            set_user_balance(target_id, val)
        
        await message.answer(f"✅ Баланс пользователя `{target_id}` успешно обновлен!", parse_mode="Markdown", reply_markup=main_keyboard(message.from_user.id))
        await state.clear()
    except ValueError:
        await message.answer("❌ Ошибка. Введите целое число (например: 15, +5, -2).")

# Веб-сервер для удержания порта на бесплатном Web Service Render
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    init_db()
    asyncio.create_task(web_server())
    print("Бот и веб-сервер успешно запущены!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
