# Telegram Groq Bot

AI-бот для Telegram на базі Groq (LLaMA 3.3 70B).

## Локальний запуск

1. Встанови залежності:
   ```bash
   pip install -r requirements.txt
   ```

2. Створи файл `.env` в папці проєкту:
   ```
   TELEGRAM_TOKEN=твій_токен_від_BotFather
   GROQ_API_KEY=твій_groq_ключ
   ```

3. Запусти:
   ```bash
   python bot.py
   ```

## Деплой на Railway

1. Завантаж репо на GitHub (без .env!)
2. Railway → New Project → Deploy from GitHub
3. Додай змінні середовища: TELEGRAM_TOKEN і GROQ_API_KEY
