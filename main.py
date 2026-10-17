import asyncio
import logging
import urllib.parse
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from config import BOT_TOKEN, ADMIN_ID
import database as db

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для админки
class AdminStates(StatesGroup):
    wait_channel = State()
    wait_reward = State()

# --- ФУНКЦИИ ПРОВЕРКИ И КЛАВИАТУРЫ ---
REQUIRED_CHANNEL = "@voodoo_Channels"

async def check_sub(user_id: int):
    # Обязательный канал плюс каналы, добавленные администратором.
    channels = list(dict.fromkeys([REQUIRED_CHANNEL, *(await db.get_all_channels())]))
    not_subbed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ["left", "kicked"] or getattr(member, "is_member", True) is False:
                not_subbed.append(ch)
        except Exception:
            # Не пропускаем пользователя, если проверка не удалась.
            logging.exception("Не удалось проверить подписку на %s", ch)
            not_subbed.append(ch)
    return not_subbed

def get_sub_keyboard(not_subbed):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for ch in not_subbed:
        channel_name = ch.lstrip("@")
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"📢 Подписаться на {ch}", url=f"https://t.me/{channel_name}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")])
    return kb

class SubscriptionMiddleware:
    async def __call__(self, handler, event, data):
        # /start сам показывает экран обязательной подписки.
        if isinstance(event, Message) and (event.text or "").split(maxsplit=1) and (event.text or "").split(maxsplit=1)[0].split("@")[0] == "/start":
            return await handler(event, data)
        # Кнопка проверки должна быть доступна неподписанным пользователям.
        if isinstance(event, types.CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        not_subbed = await check_sub(event.from_user.id)
        if not not_subbed:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(
                "⛔ Чтобы пользоваться WoodooGifi, сначала подпишись на обязательный канал:",
                reply_markup=get_sub_keyboard(not_subbed)
            )
        elif isinstance(event, types.CallbackQuery):
            await event.answer("⛔ Сначала подпишись на обязательный канал!", show_alert=True)
            if event.message:
                await event.message.answer(
                    "⛔ Чтобы пользоваться WoodooGifi, сначала подпишись на обязательный канал:",
                    reply_markup=get_sub_keyboard(not_subbed)
                )
        return

dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

def get_main_keyboard(is_admin=False):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"),
            InlineKeyboardButton(text="⭐ Баланс", callback_data="balance")
        ],
        [
            InlineKeyboardButton(text="🎁 Заработать звезды", callback_data="earn_stars"),
            InlineKeyboardButton(text="📥 Вывести звезды", callback_data="withdraw")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")
        ]
    ])
    if is_admin:
        kb.inline_keyboard.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return kb

def get_admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add_ch")],
        [InlineKeyboardButton(text="➖ Удалить канал", callback_data="admin_del_ch")],
        [InlineKeyboardButton(text="💰 Изменить награду", callback_data="admin_set_reward")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]
    ])
    return kb

# --- СТАРТ ---
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    if referrer_id == message.from_user.id:
        referrer_id = None
        
    await db.add_user(message.from_user.id, referrer_id)
    
    not_subbed = await check_sub(message.from_user.id)
    if not_subbed:
        await message.answer("👋 Привет! Для начала работы подпишись на наши каналы:", reply_markup=get_sub_keyboard(not_subbed))
    else:
        is_admin = message.from_user.id == ADMIN_ID
        await message.answer("🌟 **Добро пожаловать в WoodooGifi!**\n\n✨ Твой мир Telegram Stars начинается здесь.\nВыбери нужный раздел в меню ниже:", reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: types.CallbackQuery):
    not_subbed = await check_sub(callback.from_user.id)
    if not_subbed:
        await callback.answer("❌ Вы подписались не на все каналы!", show_alert=True)
    else:
        is_admin = callback.from_user.id == ADMIN_ID
        await callback.message.edit_text("✅ **Спасибо за подписку!**\n\n🌟 Добро пожаловать в WoodooGifi!\nВыбери нужный раздел в меню ниже:", reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")

# --- МЕНЮ ---
@dp.callback_query(F.data == "profile")
async def cb_profile(callback: types.CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"👤 **Твой профиль**\n\n🆔 ID: `{user[0]}`\n⭐ Баланс: {user[2]} Stars\n👥 Приглашено: {user[3]} чел.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]]),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "balance")
async def cb_balance(callback: types.CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"⭐ **Твой баланс:** {user[2]} Stars\n\nВывести можно в разделе '📥 Вывести звезды'.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]]),
        parse_mode="Markdown"
    )

# --- ЗАРАБОТОК (ТЕКСТОВЫЙ ШЕРИНГ) ---
@dp.callback_query(F.data == "earn_stars")
async def cb_earn_stars(callback: types.CallbackQuery):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={callback.from_user.id}"
    
    # ТЕКСТ, КОТОРЫЙ ВЫ ПРОСИЛИ
    share_text = "Заходи в вуду старс !\nПолучай звезды за приглашения и выводи! Все честно и чисто!"
    
    encoded_text = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(ref_link)
    share_url = f"https://t.me/share/url?url={encoded_link}&text={encoded_text}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Поделиться", url=share_url)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]
    ])
    
    await callback.message.edit_text(
        f"🎁 **Заработай звезды!**\n\n"
        f"Нажми на кнопку ниже, чтобы отправить сообщение друзьям.\n"
        f"За каждого друга ты получишь Stars!\n\n"
        f"Твоя ссылка: `{ref_link}`",
        reply_markup=kb, parse_mode="Markdown"
    )

@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(callback: types.CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if user[3] < 5:
        await callback.answer(
            f"❌ Для вывода нужно пригласить минимум 5 человек.\nПриглашено: {user[3]}/5",
            show_alert=True
        )
    elif user[2] < 15:
        await callback.answer(
            f"❌ Минимальная сумма вывода: 15 Stars.\nУ тебя: {user[2]}",
            show_alert=True
        )
    else:
        await callback.message.edit_text(
            "📥 Заявка на вывод отправлена администратору! Ожидайте.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]
            ])
        )
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ **Заявка на вывод!**\nПользователь: `{user[0]}`\nСумма: {user[2]} Stars",
            parse_mode="Markdown"
        )

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: types.CallbackQuery):
    await callback.message.edit_text("📊 **Статистика бота:**\n\nВсего пользователей: 100+\nВыплачено звезд: 5000+", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]]), parse_mode="Markdown")

@dp.callback_query(F.data == "about")
async def cb_about(callback: types.CallbackQuery):
    await callback.message.edit_text("ℹ️ **О проекте:**\n\nWoodooGifi - лучший бот для заработка Telegram Stars. Приглашай друзей и богатей!", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]]), parse_mode="Markdown")

@dp.callback_query(F.data == "back_menu")
async def cb_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == ADMIN_ID
    await callback.message.edit_text("🌟 Главное меню:", reply_markup=get_main_keyboard(is_admin))

# --- АДМИН ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin_panel")
async def cb_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    reward = await db.get_setting("reward")
    chans = await db.get_all_channels()
    text = f"⚙️ **Админ-панель**\n\nНаграда за друга: {reward} ⭐\nКаналы для подписки:\n" + "\n".join(chans)
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_add_ch")
async def cb_admin_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.wait_channel)
    await callback.message.edit_text("Отправьте @username канала (например: `@mychannel`):", parse_mode="Markdown")

@dp.message(AdminStates.wait_channel)
async def process_add_ch(message: Message, state: FSMContext):
    if message.text.startswith("@"):
        await db.add_channel(message.text)
        await message.answer(f"✅ Канал {message.text} добавлен!", reply_markup=get_admin_keyboard())
    else:
        await message.answer("❌ Ошибка! Канал должен начинаться с @")
    await state.clear()

@dp.callback_query(F.data == "admin_del_ch")
async def cb_admin_del(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    chans = await db.get_all_channels()
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for ch in chans:
        if ch != "@voodoo_channels": # Скрываем главный канал из списка на удаление
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ Удалить {ch}", callback_data=f"del_{ch}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    await callback.message.edit_text("Выберите канал для удаления (главный канал удалить нельзя):", reply_markup=kb)

@dp.callback_query(F.data.startswith("del_"))
async def cb_process_del(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    ch = callback.data.replace("del_", "")
    success = await db.remove_channel(ch)
    if success:
        await callback.answer(f"✅ Канал {ch} удален!")
    else:
        await callback.answer("❌ Этот канал удалить нельзя!", show_alert=True)
    await cb_admin(callback)

@dp.callback_query(F.data == "admin_set_reward")
async def cb_admin_reward(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.wait_reward)
    await callback.message.edit_text("Введите новое количество звезд за 1 приглашение (только число):")

@dp.message(AdminStates.wait_reward)
async def process_reward(message: Message, state: FSMContext):
    if message.text.isdigit():
        await db.set_setting("reward", message.text)
        await message.answer(f"✅ Награда изменена на {message.text} ⭐", reply_markup=get_admin_keyboard())
    else:
        await message.answer("❌ Ошибка! Введите число.")
    await state.clear()

async def main():
    await db.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
