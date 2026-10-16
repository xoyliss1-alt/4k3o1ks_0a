import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
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
            balance REAL DEFAULT 0.0,
            points INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, balance, points FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, balance, points)
        VALUES (?, ?, ?, 0.0, 0)
    """, (user_id, username, first_name))
    conn.commit()
    conn.close()

def update_user_field(user_id: int, field: str, amount: float):
    if field not in ['balance', 'points']:
        return False
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = {field} + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def set_user_field(user_id: int, field: str, value: float):
    if field not in ['balance', 'points']:
        return False
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_value = State()

def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
            InlineKeyboardButton(text="⭐ Очки", callback_data="points")
        ]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Изменить баланс", callback_data="adm_change_balance")],
        [InlineKeyboardButton(text="➕ Изменить очки", callback_data="adm_change_points")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

@dp.message(CommandStart())
async def cmd_start(message: Message):
    add_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name)
    await message.answer(
        f"👋 Здравствуйте, {message.from_user.first_name}!\n\nДобро пожаловать. Используйте меню ниже для навигации.",
        reply_markup=main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🔘 Главное меню:\nВыберите нужный раздел.",
        reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        add_user(callback.from_user.id, callback.from_user.username or "", callback.from_user.first_name)
        user = get_user(callback.from_user.id)
    
    user_id, username, first_name, balance, points = user
    text = (
        f"👤 **Профиль пользователя**\n\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"👤 **Имя:** {first_name}\n"
        f"💰 **Баланс:** {balance:.2f} руб.\n"
        f"⭐ **Очки:** {points} pts"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    balance = user[3] if user else 0.0
    text = f"💰 **Ваш внутренний баланс:** {balance:.2f} руб."
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "points")
async def cb_points(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    points = user[4] if user else 0
    text = f"⭐ **Ваши очки:** {points} pts"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет прав доступа к админ-панели.", show_alert=True)
        return
    text = "🛠️ **Панель администратора**\n\nВыберите действие для управления балансом или очками пользователей."
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data.in_({"adm_change_balance", "adm_change_points"}))
async def cb_adm_action(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Отказано в доступе.", show_alert=True)
        return
    
    target_field = "balance" if callback.data == "adm_change_balance" else "points"
    await state.update_data(target_field=target_field)
    await state.set_state(AdminStates.waiting_for_user_id)
    
    field_name = "баланса" if target_field == "balance" else "очков"
    await callback.message.edit_text(
        f"🛠️ **Изменение {field_name}**\n\nВведите Telegram ID пользователя:",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите корректный числовой Telegram ID пользователя.")
        return
    
    target_id = int(message.text)
    user = get_user(target_id)
    if not user:
        await message.answer("❌ Пользователь с таким ID не найден в базе данных. Попробуйте еще раз:")
        return

    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_for_value)
    
    data = await state.get_data()
    field_name = "баланс (в рублях)" if data['target_field'] == "balance" else "очки (целое число)"
    await message.answer(f"Укажите новое значение для **{field_name}** (или используйте + / - для изменения, например: `+100` или `-50`):", parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_value)
async def process_value(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    target_field = data['target_field']
    text_val = message.text.strip()
    
    try:
        if text_val.startswith("+") or text_val.startswith("-"):
            val = float(text_val)
            if target_field == "points":
                val = int(val)
            update_user_field(target_id, target_field, val)
        else:
            val = float(text_val)
            if target_field == "points":
                val = int(val)
            set_user_field(target_id, target_field, val)
        
        await message.answer(f"✅ Успешно обновлено поле **{target_field}** для пользователя `{target_id}`!", parse_mode="Markdown", reply_markup=main_keyboard(message.from_user.id))
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат числа. Введите корректное число (например: 100, +50, -20).")

async def main():
    init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
