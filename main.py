import asyncio
import json
import random
from html import escape
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import BOT_TOKEN, ADMIN_ID, WEBAPP_URL
import db

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CURRENT_ROOM_ID = 1
JACKPOT_TIMER_TASK = None

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без_юзернейма"

    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
        except ValueError:
            pass

    is_new_ref = await db.register_user_with_referral(user_id, username, referrer_id)
    
    if is_new_ref and referrer_id:
        ref_count = await db.get_referral_count(referrer_id)
        try:
            await bot.send_message(
                referrer_id, 
                f"🎉 Новый честный друг по вашей реферальной ссылке! Всего приглашено: {ref_count}."
            )
        except Exception:
            pass

    balance = await db.get_balance(user_id) or 0

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Открыть GiftsMMS", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="⭐ Пополнить 100", callback_data="add_100"),
         InlineKeyboardButton(text="⭐ Пополнить 500", callback_data="add_500")]
    ])

    await message.answer(
        f"🎁 <b>Добро пожаловать в GiftsMMS!</b>\n\n"
        f"💰 Твой баланс: <b>{balance} ⭐</b>\n"
        f"🔗 Твоя реферальная ссылка:\n<code>https://t.me/{(await bot.get_me()).username}?start=ref_{user_id}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("add_"))
async def add_balance_instant(callback: types.CallbackQuery):
    try:
        amount = int(callback.data.split("_")[1])
        user_id = callback.from_user.id

        await db.update_balance_safe(user_id, amount)
        new_balance = await db.get_balance(user_id)

        await callback.answer(f"✅ +{amount} ⭐ зачислено!", show_alert=True)
        await callback.message.answer(f"⭐ Новый баланс: {new_balance} ⭐")
    except Exception:
        await callback.answer("Ошибка при обработке запроса.", show_alert=True)

async def finish_jackpot_round():
    global CURRENT_ROOM_ID, JACKPOT_TIMER_TASK
    await asyncio.sleep(30)

    bets = await db.get_jackpot_room_bets(CURRENT_ROOM_ID)
    if not bets:
        JACKPOT_TIMER_TASK = None
        return

    total_pot = sum(b["total_bet"] for b in bets)
    
    if len(bets) == 1:
        single_user = bets[0]
        await db.update_balance_safe(single_user["user_id"], single_user["total_bet"])
        await bot.send_message(
            single_user["user_id"],
            f"⚠️ Раунд отменён: недостаточно участников. Ставка {single_user['total_bet']} ⭐ возвращена."
        )
        await db.clear_jackpot_room(CURRENT_ROOM_ID)
        JACKPOT_TIMER_TASK = None
        return

    ticket = random.uniform(0, total_pot)
    current_ticket = 0
    winner = None

    for b in bets:
        current_ticket += b["total_bet"]
        if ticket <= current_ticket:
            winner = b
            break

    if not winner:
        winner = bets[-1]

    win_amount = total_pot
    winner_chance = round((winner["total_bet"] / total_pot) * 100, 2)

    await db.update_balance_safe(winner["user_id"], win_amount)

    for b in bets:
        msg = (
            f"🎉 <b>Итоги Jackpot (Комната #{CURRENT_ROOM_ID})!</b>\n\n"
            f"🏆 Победитель: @{escape(winner['username'])}\n"
            f"💰 Общий банк: <b>{win_amount} ⭐</b>\n"
            f"📊 Шанс победителя: <b>{winner_chance}%</b>\n"
        )
        try:
            await bot.send_message(b["user_id"], msg, parse_mode="HTML")
        except Exception:
            pass

    await db.clear_jackpot_room(CURRENT_ROOM_ID)
    CURRENT_ROOM_ID += 1
    JACKPOT_TIMER_TASK = None

@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    global JACKPOT_TIMER_TASK
    try:
        payload = json.loads(message.web_app_data.data)
        bet = int(payload.get("bet", 0))
        user_id = message.from_user.id
        username = message.from_user.username or "без_юзернейма"

        if bet < 15 or bet > 10000:
            await message.answer("❌ Ставка должна быть от 15 до 10 000 ⭐")
            return

        # Безопасное списание с проверкой баланса внутри транзакции
        success = await db.update_balance_safe(user_id, -bet)
        if not success:
            await message.answer("❌ Недостаточно средств на балансе!")
            return

        await db.add_jackpot_bet(CURRENT_ROOM_ID, user_id, username, bet)

        bets = await db.get_jackpot_room_bets(CURRENT_ROOM_ID)
        total_pot = sum(b["total_bet"] for b in bets)

        await message.answer(
            f"✅ Ставка <b>{bet} ⭐</b> принята в Jackpot!\n"
            f"💰 Банк комнаты: <b>{total_pot} ⭐</b>\n"
            f"👥 Игроков: {len(bets)}",
            parse_mode="HTML"
        )

        if JACKPOT_TIMER_TASK is None:
            JACKPOT_TIMER_TASK = asyncio.create_task(finish_jackpot_round())

    except Exception:
        await message.answer("❌ Ошибка при приёме ставки.")

async def on_startup():
    await db.init_db()
    print("✅ База данных подключена, пул оптимизирован под высокую нагрузку.")

async def main():
    dp.startup.register(on_startup)
    print("🚀 Бот запущен и защищен от рейдов!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
