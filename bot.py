import os
import logging
import asyncio
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
# КОНФИГУРАЦИЯ БОТА
# -------------------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")  # Токен берется из настроек Render
ADMIN_USERNAME = "xoyli"         # Никнейм главного админа без @

# Локальная база данных в памяти
db = {
    "users": {},        # user_id: {"balance": int, "referrer": int, "is_bot_verified": bool}
    "channels": [       # Обязательные каналы
        {"id": "@voodoo_channels", "url": "https://t.me/voodoo_channels"}
    ],
    "star_reward": 5,   # Звёзд за одного реферала по умолчанию
    "admin_ids": []     # Хранилище Telegram ID админа
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# FSM Состояния для админ-панели
class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_reward = State()


# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -------------------------------------------------------------------
async def check_subscriptions(user_id: int) -> bool:
    """Проверка подписки на все обязательные каналы."""
    for channel in db["channels"]:
        try:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status not in ["creator", "administrator", "member"]:
                return False
        except Exception:
            return False
    return True


def get_sub_keyboard():
    """Клавиатура со ссылками на обязательные каналы."""
    buttons = []
    for idx, ch in enumerate(db["channels"], 1):
        buttons.append([InlineKeyboardButton(text=f"📢 Подписаться (Канал #{idx})", url=ch["url"])])
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_captcha_keyboard():
    """Анти-накрутка от ботов."""
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
    username = message.from_user.username

    # Активация админа по логину @xoyli
    if username and username.lower() == ADMIN_USERNAME.lower():
        if user_id not in db["admin_ids"]:
            db["admin_ids"].append(user_id)

    # Регистрация нового пользователя
    if user_id not in db["users"]:
        args = message.text.split()
        referrer_id = None
        if len(args) > 1 and args[1].isdigit():
            potential_ref = int(args[1])
            if potential_ref != user_id and potential_ref in db["users"]:
                referrer_id = potential_ref

        db["users"][user_id] = {
            "balance": 0,
            "referrer": referrer_id,
            "is_bot_verified": False
        }

    # Проверка подписки на канал
    is_subbed = await check_subscriptions(user_id)
    if not is_subbed:
        await message.answer(
            "⚠️ **Для работы с ботом необходимо подписаться на наш канал:**",
            reply_markup=get_sub_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Проверка на бота / капча
    if not db["users"][user_id]["is_bot_verified"]:
        await message.answer(
            "🛡 **Защита от накрутки:** Пожалуйста, подтвердите, что вы человек:",
            reply_markup=get_captcha_keyboard()
        )
        return

    await send_main_menu(message)


@dp.callback_query(F.data == "captcha_pass")
async def process_captcha_pass(callback: CallbackQuery):
    user_id = callback.from_user.id
    db["users"][user_id]["is_bot_verified"] = True
    
    # Начисление звёзд пригласителю
    referrer_id = db["users"][user_id].get("referrer")
    if referrer_id:
        reward = db["star_reward"]
        db["users"][referrer_id]["balance"] += reward
        db["users"][user_id]["referrer"] = None 
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
        if not db["users"][user_id]["is_bot_verified"]:
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
    balance = db["users"][user_id]["balance"]
    reward = db["star_reward"]

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
def is_admin(user_id: int, username: str) -> bool:
    if username and username.lower() == ADMIN_USERNAME.lower():
        return True
    return user_id in db["admin_ids"]


@dp.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if not is_admin(message.from_user.id, message.from_user.username):
        await message.answer("❌ У вас нет доступа к панели администратора.")
        return

    await send_admin_menu(message)


async def send_admin_menu(message: Message):
    channels_text = "\n".join([f"• {ch['id']}" for ch in db["channels"]]) or "Нет каналов"
    text = (
        f"⚙️ **Админ-Панель (@{ADMIN_USERNAME})**\n\n"
        f"⭐️ Награда за реферала: **{db['star_reward']} ⭐**\n"
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
    if not is_admin(callback.from_user.id, callback.from_user.username):
        return
    await callback.message.answer("Укажите новое количество ⭐ за одного реферала (введите число):")
    await state.set_state(AdminStates.waiting_for_reward)


@dp.message(AdminStates.waiting_for_reward)
async def admin_change_reward_process(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    
    db["star_reward"] = int(message.text)
    await state.clear()
    await message.answer(f"✅ Награда за реферала изменена на **{db['star_reward']} ⭐**.")
    await send_admin_menu(message)


@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id, callback.from_user.username):
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
    db["channels"].append({"id": channel_id, "url": channel_url})
    await state.clear()
    await message.answer(f"✅ Канал `{channel_id}` добавлен.")
    await send_admin_menu(message)


@dp.callback_query(F.data == "admin_del_channel")
async def admin_del_channel_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id, callback.from_user.username):
        return

    if not db["channels"]:
        await callback.answer("Список каналов пуст!", show_alert=True)
        return

    buttons = []
    for ch in db["channels"]:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Удалить {ch['id']}", 
            callback_data=f"del_ch_{ch['id']}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите канал для удаления:", reply_markup=kb)


@dp.callback_query(F.data.startswith("del_ch_"))
async def admin_del_channel_process(callback: CallbackQuery):
    ch_id = callback.data.replace("del_ch_", "")
    db["channels"] = [ch for ch in db["channels"] if ch["id"] != ch_id]
    await callback.answer(f"Канал {ch_id} удален!")
    await callback.message.delete()
    await send_admin_menu(callback.message)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    print("Бот успешно запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
