import asyncio
import json
import logging
import os
import random
from html import escape
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    LabeledPrice,
)

from config import BOT_TOKEN, ADMIN_ID, WEBAPP_URL
import db

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CURRENT_ROOM_ID = 1
JACKPOT_TIMER_TASK = None
ROUND_LOCK = asyncio.Lock()
TOP_UP_AMOUNT = 100


def main_keyboard(balance: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Открыть GiftsMMS", web_app=WebAppInfo(url=WEBAPP_URL))],
        [
            InlineKeyboardButton(text="⭐ Пополнить 100", callback_data="add_100"),
            InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw_info"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance")],
    ])


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    if user is None:
        return
    user_id = user.id
    username = user.username or "без_юзернейма"

    args = (message.text or "").split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except ValueError:
            referrer_id = None

    is_new_ref = await db.register_user_with_referral(user_id, username, referrer_id)
    if is_new_ref and referrer_id:
        ref_count = await db.get_referral_count(referrer_id)
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 Новый пользователь по вашей реферальной ссылке! Всего приглашено: {ref_count}.",
            )
        except Exception:
            log.exception("Could not notify referrer")

    balance = await db.get_balance(user_id) or 0
    me = await bot.get_me()
    await message.answer(
        f"🎁 <b>Добро пожаловать в GiftsMMS!</b>\n\n"
        f"💰 Твой баланс: <b>{balance} ⭐</b>\n"
        f"📤 Минимальный вывод: <b>100 ⭐</b>\n\n"
        f"🔗 Твоя реферальная ссылка:\n"
        f"<code>https://t.me/{me.username}?start=ref_{user_id}</code>",
        reply_markup=main_keyboard(balance),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "refresh_balance")
async def refresh_balance_callback(callback: types.CallbackQuery):
    balance = await db.get_balance(callback.from_user.id) or 0
    try:
        await callback.message.edit_text(
            f"💰 Твой баланс: <b>{balance} ⭐</b>\n\nВыбери действие:",
            reply_markup=main_keyboard(balance),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"💰 Твой баланс: <b>{balance} ⭐</b>",
            reply_markup=main_keyboard(balance),
            parse_mode="HTML",
        )
    await callback.answer("Баланс обновлён")


@dp.callback_query(F.data == "withdraw_info")
async def withdraw_info_callback(callback: types.CallbackQuery):
    await callback.message.answer(
        "📤 <b>Вывод средств</b>\n\n"
        "Отправь команду: <code>/withdraw 100</code>\n"
        "Минимальная сумма — 100 ⭐.\n"
        "Баланс списывается при создании заявки.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(Command("withdraw"))
async def withdraw_cmd(message: types.Message):
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer(
            "Формат: <code>/withdraw 100</code>\nМинимальная сумма — 100 ⭐.",
            parse_mode="HTML",
        )
        return

    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Введи сумму целым числом.")
        return

    if amount < 100:
        await message.answer("❌ Минимальная сумма вывода — 100 ⭐.")
        return

    user = message.from_user
    if user is None:
        return
    success = await db.create_withdraw_request(user.id, amount)
    if not success:
        await message.answer("❌ Недостаточно средств на балансе.")
        return

    username = escape(user.username or "без_юзернейма")
    await message.answer(
        f"✅ Заявка на вывод <b>{amount} ⭐</b> создана. Администратор рассмотрит её.",
        parse_mode="HTML",
    )
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 <b>Новая заявка на вывод</b>\n\n"
                f"👤 Игрок: @{username} (ID: <code>{user.id}</code>)\n"
                f"💰 Сумма: <b>{amount} ⭐</b>",
                parse_mode="HTML",
            )
        except Exception:
            log.exception("Could not notify admin about withdrawal")


@dp.callback_query(F.data == "add_100")
async def add_balance_invoice(callback: types.CallbackQuery):
    # Баланс начисляется только после подтверждённого платежа Telegram Stars.
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Пополнение GiftsMMS",
            description="Пополнение внутреннего баланса на 100 ⭐",
            payload=f"topup:{callback.from_user.id}:{TOP_UP_AMOUNT}",
            currency="XTR",
            prices=[LabeledPrice(label="100 Telegram Stars", amount=TOP_UP_AMOUNT)],
        )
        await callback.answer()
    except Exception:
        log.exception("Could not create Telegram Stars invoice")
        await callback.answer("Не удалось создать счёт. Попробуй позже.", show_alert=True)


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload.split(":")
    valid = (
        len(payload) == 3
        and payload[0] == "topup"
        and payload[1].isdigit()
        and int(payload[1]) == pre_checkout_query.from_user.id
        and payload[2].isdigit()
        and int(payload[2]) == TOP_UP_AMOUNT
        and pre_checkout_query.currency == "XTR"
        and pre_checkout_query.total_amount == TOP_UP_AMOUNT
    )
    await pre_checkout_query.answer(ok=valid, error_message=None if valid else "Счёт недействителен.")


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    user = message.from_user
    if payment is None or user is None:
        return
    payload = payment.invoice_payload.split(":")
    if not (
        len(payload) == 3
        and payload[0] == "topup"
        and payload[1].isdigit()
        and int(payload[1]) == user.id
        and payload[2].isdigit()
        and int(payload[2]) == TOP_UP_AMOUNT
        and payment.currency == "XTR"
        and payment.total_amount == TOP_UP_AMOUNT
    ):
        await message.answer("❌ Не удалось подтвердить платёж. Свяжись с администратором.")
        log.error("Unexpected successful payment payload for user %s", user.id)
        return

    await db.update_balance_safe(user.id, TOP_UP_AMOUNT)
    balance = await db.get_balance(user.id) or 0
    await message.answer(f"✅ Оплата подтверждена! Начислено 100 ⭐. Баланс: {balance} ⭐")


async def finish_jackpot_round(room_id: int):
    global CURRENT_ROOM_ID, JACKPOT_TIMER_TASK
    try:
        await asyncio.sleep(30)
        async with ROUND_LOCK:
            bets = await db.get_jackpot_room_bets(room_id)
            if not bets:
                return

            total_pot = sum(int(b["total_bet"]) for b in bets)
            if len(bets) == 1:
                player = bets[0]
                await db.update_balance_safe(player["user_id"], int(player["total_bet"]))
                try:
                    await bot.send_message(
                        player["user_id"],
                        f"⚠️ Раунд отменён: нужен минимум второй игрок. "
                        f"Возвращено {player['total_bet']} ⭐.",
                    )
                except Exception:
                    log.exception("Could not return single-player bet")
                await db.clear_jackpot_room(room_id)
                return

            ticket = random.uniform(0, total_pot)
            running_total = 0
            winner = bets[-1]
            for bet in bets:
                running_total += int(bet["total_bet"])
                if ticket <= running_total:
                    winner = bet
                    break

            await db.update_balance_safe(winner["user_id"], total_pot)
            winner_chance = round(int(winner["total_bet"]) / total_pot * 100, 2)
            for bet in bets:
                try:
                    await bot.send_message(
                        bet["user_id"],
                        f"🎉 <b>Итоги Jackpot (комната #{room_id})!</b>\n\n"
                        f"🏆 Победитель: @{escape(winner['username'] or 'без_юзернейма')}\n"
                        f"💰 Общий банк: <b>{total_pot} ⭐</b>\n"
                        f"📊 Доля ставок победителя: <b>{winner_chance}%</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    log.exception("Could not send jackpot result to user %s", bet["user_id"])

            await db.clear_jackpot_room(room_id)
            if CURRENT_ROOM_ID == room_id:
                CURRENT_ROOM_ID += 1
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Jackpot round failed for room %s", room_id)
    finally:
        if JACKPOT_TIMER_TASK is asyncio.current_task():
            JACKPOT_TIMER_TASK = None


@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    global JACKPOT_TIMER_TASK
    user = message.from_user
    if user is None or message.web_app_data is None:
        return
    try:
        payload = json.loads(message.web_app_data.data)
        bet = int(payload.get("bet", 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        await message.answer("❌ Некорректная ставка. Открой игру ещё раз.")
        return

    if bet < 15 or bet > 10000:
        await message.answer("❌ Ставка должна быть от 15 до 10 000 ⭐.")
        return

    # Lock makes balance deduction and bet placement sequential for concurrent requests.
    async with ROUND_LOCK:
        if JACKPOT_TIMER_TASK is not None and not JACKPOT_TIMER_TASK.done():
            room_id = CURRENT_ROOM_ID
        else:
            room_id = CURRENT_ROOM_ID

        success = await db.update_balance_safe(user.id, -bet)
        if not success:
            await message.answer("❌ Недостаточно средств на балансе!")
            return

        await db.add_jackpot_bet(room_id, user.id, user.username or "без_юзернейма", bet)
        bets = await db.get_jackpot_room_bets(room_id)
        total_pot = sum(int(b["total_bet"]) for b in bets)

        if JACKPOT_TIMER_TASK is None or JACKPOT_TIMER_TASK.done():
            JACKPOT_TIMER_TASK = asyncio.create_task(finish_jackpot_round(room_id))

    await message.answer(
        f"✅ Ставка <b>{bet} ⭐</b> принята!\n"
        f"💰 Банк комнаты: <b>{total_pot} ⭐</b>\n"
        f"👥 Игроков: <b>{len(bets)}</b>",
        parse_mode="HTML",
    )


async def handle_ping(request: web.Request):
    return web.json_response({"status": "ok", "service": "GiftsMMS bot"})


async def handle_app(request: web.Request):
    index_path = Path(__file__).with_name("index.html")
    if not index_path.exists():
        return web.Response(text="Mini App file is missing", status=500)
    return web.FileResponse(index_path)


async def web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    app.router.add_get("/app", handle_app)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP server listening on port %s", port)
    return runner


async def on_startup():
    await db.init_db()
    await web_server()
    log.info("Database initialized; bot is ready.")


async def main():
    dp.startup.register(on_startup)
    log.info("Starting GiftsMMS bot")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
