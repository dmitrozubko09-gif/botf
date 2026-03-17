import os
import json
import logging
import httpx
import tempfile
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from groq import Groq

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = f"""Ти корисний AI-асистент у Telegram. Відповідай чітко, дружньо та по суті.
Поточна дата і час: {datetime.now().strftime('%d.%m.%Y %H:%M')} (UTC).

Ти маєш доступ до інструментів — використовуй їх АВТОМАТИЧНО:
- get_weather: коли питають про погоду, температуру, опади в будь-якому місті
- get_news: коли питають про новини, події у світі, що відбувається
- get_currency: коли питають про курс валют, обмін валюти, скільки коштує долар/євро/гривня
- generate_image: коли просять намалювати, згенерувати або створити зображення/картинку
- translate_text: коли просять перекласти текст на іншу мову

Якщо не знаєш відповіді — так і скажи, не вигадуй.
Відповідай мовою, якою пише користувач."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Отримати поточну погоду та прогноз для міста.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Назва міста англійською, наприклад: Kyiv, London, Lviv"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Отримати останні новини за темою або загальні світові новини.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Тема англійською: Ukraine, technology, sport. Порожньо — загальні новини."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_currency",
            "description": "Отримати актуальний курс валют. Використовуй коли питають про курс долара, євро, гривні або будь-якої валюти.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "Базова валюта (3 літери): USD, EUR, UAH, GBP. За замовчуванням USD."},
                    "targets": {"type": "array", "items": {"type": "string"}, "description": "Список цільових валют: ['UAH', 'EUR', 'GBP']."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Згенерувати зображення за описом. Використовуй коли просять намалювати або створити картинку.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Детальний опис зображення англійською мовою."}
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "translate_text",
            "description": "Перекласти текст на вказану мову.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст для перекладу."},
                    "target_language": {"type": "string", "description": "Мова перекладу: українська, англійська, польська тощо."}
                },
                "required": ["text", "target_language"]
            }
        }
    }
]


async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "❌ WEATHER_API_KEY не налаштовано."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "uk"}
            )
            if resp.status_code == 404:
                return f"❌ Місто '{city}' не знайдено."
            resp.raise_for_status()
            data = resp.json()
            forecast_resp = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "uk", "cnt": 24}
            )
            forecast_data = forecast_resp.json()

        name = data["name"]
        country = data["sys"]["country"]
        temp = round(data["main"]["temp"])
        feels_like = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"].capitalize()
        humidity = data["main"]["humidity"]
        wind = round(data["wind"]["speed"])
        visibility = data.get("visibility", 0) // 1000
        icon = _weather_icon(data["weather"][0]["id"])

        result = (
            f"{icon} *Погода в {name}, {country}*\n\n"
            f"🌡 Температура: *{temp}°C* (відчувається як {feels_like}°C)\n"
            f"☁️ {desc}\n"
            f"💧 Вологість: {humidity}%\n"
            f"💨 Вітер: {wind} м/с\n"
            f"👁 Видимість: {visibility} км\n"
        )
        if forecast_data.get("list"):
            result += "\n📅 *Прогноз на 3 дні:*\n"
            seen_days = set()
            for item in forecast_data["list"]:
                dt = datetime.fromtimestamp(item["dt"])
                day_key = dt.strftime("%d.%m")
                if day_key in seen_days or day_key == datetime.now().strftime("%d.%m"):
                    continue
                if len(seen_days) >= 3:
                    break
                seen_days.add(day_key)
                day_temp = round(item["main"]["temp"])
                day_desc = item["weather"][0]["description"].capitalize()
                day_icon = _weather_icon(item["weather"][0]["id"])
                result += f"  {day_key}: {day_icon} {day_temp}°C, {day_desc}\n"
        return result
    except httpx.TimeoutException:
        return "❌ Сервіс погоди не відповідає."
    except Exception as e:
        logger.error(f"Weather error: {e}", exc_info=True)
        return f"❌ Помилка: {str(e)}"


def _weather_icon(weather_id: int) -> str:
    if weather_id < 300: return "⛈"
    elif weather_id < 500: return "🌧"
    elif weather_id < 600: return "🌧"
    elif weather_id < 700: return "❄️"
    elif weather_id < 800: return "🌫"
    elif weather_id == 800: return "☀️"
    elif weather_id < 803: return "⛅️"
    else: return "☁️"


async def get_news(query: str = "") -> str:
    if not NEWS_API_KEY:
        return "❌ NEWS_API_KEY не налаштовано."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if query:
                resp = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": query, "apiKey": NEWS_API_KEY, "language": "en", "sortBy": "publishedAt", "pageSize": 5}
                )
            else:
                resp = await client.get(
                    "https://newsapi.org/v2/top-headlines",
                    params={"apiKey": NEWS_API_KEY, "language": "en", "pageSize": 5}
                )
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("articles", [])
        if not articles:
            return f"📰 Новини не знайдено."

        result = f"📰 *Топ новини{' про ' + query if query else ''}:*\n\n"
        for i, article in enumerate(articles[:5], 1):
            art_title = article.get("title", "Без назви")
            source = article.get("source", {}).get("name", "")
            url = article.get("url", "")
            published = article.get("publishedAt", "")[:10]
            if len(art_title) > 100:
                art_title = art_title[:97] + "..."
            result += f"{i}. *{art_title}*\n"
            if source:
                result += f"   📌 {source}"
            if published:
                result += f" · {published}"
            result += f"\n   🔗 {url}\n\n"
        return result.strip()
    except httpx.TimeoutException:
        return "❌ Сервіс новин не відповідає."
    except Exception as e:
        logger.error(f"News error: {e}", exc_info=True)
        return "❌ Не вдалося отримати новини."


async def get_currency(base: str = "USD", targets: list = None) -> str:
    try:
        base = base.upper()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://open.er-api.com/v6/latest/{base}")
            resp.raise_for_status()
            data = resp.json()

        if data.get("result") != "success":
            return "❌ Не вдалося отримати курс валют."

        rates = data["rates"]
        updated = data.get("time_last_update_utc", "")[:16]

        if not targets:
            targets = ["UAH", "EUR", "USD", "GBP", "PLN", "CZK"]
        targets = [t.upper() for t in targets if t.upper() != base]

        flag_map = {
            "UAH": "🇺🇦", "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧",
            "PLN": "🇵🇱", "CZK": "🇨🇿", "CHF": "🇨🇭", "JPY": "🇯🇵",
            "CAD": "🇨🇦", "AUD": "🇦🇺", "CNY": "🇨🇳", "TRY": "🇹🇷"
        }

        result = f"💱 *Курс валют (базова: {base})*\n_Оновлено: {updated}_\n\n"
        for target in targets:
            if target in rates:
                flag = flag_map.get(target, "💰")
                rate = rates[target]
                result += f"{flag} {target}: *{rate:.2f}*\n"
        return result.strip()
    except httpx.TimeoutException:
        return "❌ Сервіс валют не відповідає."
    except Exception as e:
        logger.error(f"Currency error: {e}", exc_info=True)
        return "❌ Не вдалося отримати курс валют."


async def generate_image(prompt: str) -> str:
    encoded = prompt.replace(" ", "%20").replace(",", "%2C")
    image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    return f"IMAGE:{image_url}|PROMPT:{prompt}"


async def translate_text(text: str, target_language: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": f"Ти перекладач. Переклади наданий текст на {target_language}. Поверни ТІЛЬКИ переклад, без пояснень."
                },
                {"role": "user", "content": text}
            ],
            max_tokens=2048,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Translation error: {e}", exc_info=True)
        return "❌ Не вдалося перекласти текст."


async def call_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "get_weather":
        return await get_weather(tool_args.get("city", ""))
    elif tool_name == "get_news":
        return await get_news(query=tool_args.get("query", ""))
    elif tool_name == "get_currency":
        return await get_currency(base=tool_args.get("base", "USD"), targets=tool_args.get("targets", []))
    elif tool_name == "generate_image":
        return await generate_image(tool_args.get("prompt", ""))
    elif tool_name == "translate_text":
        return await translate_text(text=tool_args.get("text", ""), target_language=tool_args.get("target_language", "українська"))
    return "❌ Невідомий інструмент."


conversation_history: dict[int, list] = {}
MAX_HISTORY = 20


def get_history(chat_id: int) -> list:
    return conversation_history.get(chat_id, [])


def add_to_history(chat_id: int, role: str, content):
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    conversation_history[chat_id].append({"role": role, "content": content})
    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]


def clear_history(chat_id: int):
    conversation_history[chat_id] = []


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text(
        "👋 Привіт! Я AI-асистент з розширеними можливостями.\n\n"
        "Просто пиши мені — я сам розберусь що потрібно:\n\n"
        "🌤 *Погода* — «яка погода в Києві?»\n"
        "📰 *Новини* — «що відбувається у світі?»\n"
        "💱 *Валюта* — «який курс долара?»\n"
        "🖼 *Зображення* — «намалюй кота в космосі»\n"
        "🌍 *Переклад* — «переклади на англійську: привіт»\n"
        "🎵 *Голос* — надішли голосове повідомлення\n"
        "🤖 *AI* — будь-які запитання\n\n"
        "Команди: /help · /clear",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Що я вмію:*\n\n"
        "🌤 *Погода:* «яка погода в Парижі?»\n"
        "📰 *Новини:* «останні новини про Україну»\n"
        "💱 *Валюта:* «який курс долара до гривні?»\n"
        "🖼 *Зображення:* «намалюй захід сонця над морем»\n"
        "🌍 *Переклад:* «переклади на англійську: Добрий день»\n"
        "🎵 *Голос:* надішли голосове — розпізнаю і відповім\n\n"
        "*/clear* — очистити історію розмови",
        parse_mode="Markdown"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text("🧹 Історію очищено!")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=("voice.ogg", audio_file),
                model="whisper-large-v3",
                language="uk",
            )

        os.unlink(tmp_path)
        recognized_text = transcription.text

        if not recognized_text.strip():
            await update.message.reply_text("🎵 Не вдалося розпізнати голос. Спробуй ще раз.")
            return

        await update.message.reply_text(f"🎵 *Розпізнано:* {recognized_text}", parse_mode="Markdown")
        add_to_history(chat_id, "user", recognized_text)
        await process_ai_message(update, context, chat_id)

    except Exception as e:
        logger.error(f"Voice error: {e}", exc_info=True)
        await update.message.reply_text("❌ Не вдалося обробити голосове повідомлення.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    add_to_history(chat_id, "user", user_message)
    await process_ai_message(update, context, chat_id)


async def process_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id)

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
            temperature=0.7,
        )

        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        if tool_calls:
            messages.append({
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            })

            image_url = None
            image_prompt = None

            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")

                tool_result = await call_tool(tool_name, tool_args)

                if tool_result.startswith("IMAGE:"):
                    parts = tool_result.split("|PROMPT:")
                    image_url = parts[0].replace("IMAGE:", "")
                    image_prompt = parts[1] if len(parts) > 1 else ""
                    tool_result = f"Зображення згенеровано: {image_prompt}"

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})

            if image_url:
                await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
                try:
                    await update.message.reply_photo(
                        photo=image_url,
                        caption=f"🖼 *{image_prompt}*",
                        parse_mode="Markdown"
                    )
                except Exception as img_err:
                    logger.error(f"Image send error: {img_err}")
                    await update.message.reply_text(f"🖼 Зображення готове:\n{image_url}")
                add_to_history(chat_id, "assistant", f"Згенерував зображення: {image_prompt}")
                return

            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            final_response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            assistant_reply = final_response.choices[0].message.content
        else:
            assistant_reply = response_message.content

        add_to_history(chat_id, "assistant", assistant_reply)

        if len(assistant_reply) > 4096:
            for i in range(0, len(assistant_reply), 4096):
                await update.message.reply_text(assistant_reply[i:i+4096], parse_mode="Markdown")
        else:
            await update.message.reply_text(assistant_reply, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("❌ Виникла помилка. Спробуй ще раз або /clear для скидання.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущено!")
    app.run_polling()


if __name__ == "__main__":
    main()
