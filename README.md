# Telegram Bot with Profile, Balance & Points System

Удобный Telegram-бот с профилем пользователя, системой очков, внутренним балансом и админ-панелью.

## 🚀 Настройка и деплой на Render

1. Загрузите файлы репозитория на **GitHub**.
2. Перейдите на [Render.com](https://render.com).
3. Создайте новый сервис **Background Worker** (не Web Service).
4. Подключите ваш GitHub репозиторий.
5. Укажите команды:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
6. В разделе **Environment Variables** добавьте:
   - `BOT_TOKEN`: Токен вашего бота от @BotFather
   - `ADMIN_IDS`: Ваш Telegram ID (или списком через запятую, например: `123456789,987654321`)
