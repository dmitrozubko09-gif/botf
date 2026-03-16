import os
import json
import logging
import httpx
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
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")  # безкоштовно на openweathermap.org
NEWS_API_KEY = os.getenv("NEWS_API_KEY")         # безкоштовно на newsapi.org

groq_client = Groq(api_key=GROQ_API_KEY)

# ─── Системний промпт ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""Ти корисний AI-асистент у Telegram. Відповідай чітко, дружньо та по суті.
Поточна дата і час: {datetime.now().strftime('%d.%m.%Y %H:%M')} (UTC).

Ти маєш доступ до інструментів:
- get_weather: отримати реальну погоду для будь-якого міста
- get_news: отримати останні новини (за темою або загальні)

Використовуй ці інструменти АВТОМАТИЧНО коли користувач:
- питає про погоду, температуру, опади в будь-якому місті
- просить показати новини, що відбувається у світі, останні події
- питає "що зараз відбувається", "які новини", "що нового"

Якщо не знаєш відповіді — так і скажи, не вигадуй.
Відповідай мовою, якою пише користувач."""

# ─── Опис інструментів для Groq ──────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Отримати поточну погоду та прогноз для вказаного міста. Використовуй коли користувач питає про погоду.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Назва міста англійською або мовою оригіналу, наприклад: Kyiv, London, Lviv"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Отримати останні новини. Використовуй коли користувач питає про новини, поточні події, що відбувається у світі.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Тема для пошуку новин англійською, наприклад: Ukraine, technology, sport, war, politics. Якщо загальні світові новини — залиш порожнім."
                    }
                },
                "required": []
            }
        }
    }
]

# ─── Реальне отримання погоди ─────────────────────────────────────────────────
async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "❌ WEATHER_API_KEY не налаштовано. Додай ключ з openweathermap.org у змінні середовища."

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Поточна погода
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "uk"
                }
            )
            if resp.status_code == 404:
                return f"❌ Місто '{city}' не знайдено. Спробуй написати назву англійською."
            resp.raise_for_status()
            data = resp.json()

            # Прогноз на 5 днів
            forecast_resp = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "q": city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "uk",
                    "cnt": 24  # 3 дні по 8 записів
                }
            )
            forecast_data = forecast_resp.json()

        # Поточна погода
        name = data["name"]
        country = data["sys"]["country"]
        temp = round(data["main"]["temp"])
        feels_like = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"].capitalize()
        humidity = data["main"]["humidity"]
        wind = round(data["wind"]["speed"])
        visibility = data.get("visibility", 0) // 1000

        # Иконка погоди
        weather_id = data["weather"][0]["id"]
        icon = _weather_icon(weather_id)

        result = (
            f"{icon} *Погода в {name}, {country}*\n\n"
            f"🌡 Температура: *{temp}°C* (відчувається як {feels_like}°C)\n"
            f"☁️ {desc}\n"
            f"💧 Вологість: {humidity}%\n"
            f"💨 Вітер: {wind} м/с\n"
            f"👁 Видимість: {visibility} км\n"
        )

        # Прогноз на наступні дні (по одному запису на день)
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
        return "❌ Сервіс погоди не відповідає. Спробуй пізніше."
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return f"❌ Не вдалося отримати погоду для '{city}'."


def _weather_icon(weather_id: int) -> str:
    if weather_id < 300:
        return "⛈"
    elif weather_id < 400:
        return "🌧"
    elif weather_id < 600:
        return "🌧"
    elif weather_id < 700:
        return "❄️"
    elif weather_id < 800:
        return "🌫"
    elif weather_id == 800:
        return "☀️"
    elif weather_id < 803:
        return "⛅️"
    else:
        return "☁️"


# ─── Реальне отримання новин ──────────────────────────────────────────────────
async def get_news(query: str = "") -> str:
    if not NEWS_API_KEY:
        return "❌ NEWS_API_KEY не налаштовано. Отримай безкоштовний ключ на newsapi.org і додай у змінні середовища."

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if query:
                resp = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": query,
                        "apiKey": NEWS_API_KEY,
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": 5
                    }
                )
            else:
                resp = await client.get(
                    "https://newsapi.org/v2/top-headlines",
                    params={
                        "apiKey": NEWS_API_KEY,
                        "language": "en",
                        "pageSize": 5
                    }
                )
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("articles", [])
        if not articles:
            return f"📰 Новини за запитом '{query}' не знайдено."

        title = f"📰 *Топ новини{' про ' + query if query else ''}:*\n\n"
        result = title
        for i, article in enumerate(articles[:5], 1):
            art_title = article.get("title", "Без назви")
            source = article.get("source", {}).get("name", "")
            url = article.get("url", "")
            published = article.get("publishedAt", "")[:10]

            # Обрізаємо довгі заголовки
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
        return "❌ Сервіс новин не відповідає. Спробуй пізніше."
    except Exception as e:
        logger.error(f"News error: {e}")
        return "❌ Не вдалося отримати новини."


# ─── Виклик інструменту ───────────────────────────────────────────────────────
async def call_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "get_weather":
        return await get_weather(tool_args.get("city", ""))
    elif tool_name == "get_news":
        return await get_news(
            query=tool_args.get("query", "")
        )
    return "❌ Невідомий інструмент."


# ─── Історія розмов ───────────────────────────────────────────────────────────
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


# ─── Команди ──────────────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text(
        "👋 Привіт! Я AI-асистент з доступом до реальних даних.\n\n"
        "Просто пиши мені — я сам розберусь що тобі потрібно:\n\n"
        "🌤 *Погода* — «яка погода в Києві?», «температура в Лондоні»\n"
        "📰 *Новини* — «що відбувається у світі?», «новини про Україну»\n"
        "🤖 *AI* — будь-які питання, допомога, розмова\n\n"
        "Команди:\n"
        "/start — нова розмова\n"
        "/clear — очистити історію\n"
        "/help — довідка",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Як користуватись:*\n\n"
        "Просто пиши звичайним текстом, я сам розумію що тобі треба:\n\n"
        "🌤 *Погода:*\n"
        "— «яка погода в Парижі?»\n"
        "— «температура зараз у Харкові»\n"
        "— «чи буде дощ у Варшаві?»\n\n"
        "📰 *Новини:*\n"
        "— «що нового у світі?»\n"
        "— «останні новини про Україну»\n"
        "— «новини про футбол»\n\n"
        "🤖 *AI-асистент:*\n"
        "— будь-які запитання\n"
        "— переклад, написання текстів\n"
        "— допомога з завданнями\n\n"
        "*/clear* — очистити历историю розмови",
        parse_mode="Markdown"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text("🧹 Історію очищено! Починаємо з чистого аркуша.")


# ─── Головний обробник повідомлень ────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    add_to_history(chat_id, "user", user_message)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id)

    try:
        # Перший запит до AI з інструментами
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

        # Якщо AI вирішив використати інструмент
        if tool_calls:
            # Додаємо відповідь AI з tool_calls до контексту
            messages.append({
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in tool_calls
                ]
            })

            # Виконуємо всі інструменти
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")

                tool_result = await call_tool(tool_name, tool_args)

                # Додаємо результат інструменту
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result
                })

            # Другий запит — AI формулює фінальну відповідь
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            final_response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            assistant_reply = final_response.choices[0].message.content

        else:
            # AI відповів без інструментів
            assistant_reply = response_message.content

        add_to_history(chat_id, "assistant", assistant_reply)

        # Telegram має ліміт 4096 символів
        if len(assistant_reply) > 4096:
            for i in range(0, len(assistant_reply), 4096):
                await update.message.reply_text(
                    assistant_reply[i:i+4096],
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(assistant_reply, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Виникла помилка. Спробуй ще раз або /clear для скидання."
        )


# ─── Запуск ───────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущено!")
    app.run_polling()


if __name__ == "__main__":
    main()
