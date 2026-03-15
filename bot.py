import os
import logging
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

groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """Ти корисний AI-асистент. Відповідай чітко, по суті та дружньо.
Якщо не знаєш відповіді — так і скажи, не вигадуй."""

conversation_history: dict[int, list] = {}
MAX_HISTORY = 20


def get_history(chat_id: int) -> list:
    return conversation_history.get(chat_id, [])


def add_to_history(chat_id: int, role: str, content: str):
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
        "👋 Привіт! Я AI-асистент на базі Groq.\n\n"
        "Просто напиши мені що-небудь, і я відповім!\n\n"
        "Команди:\n"
        "/start — почати нову розмову\n"
        "/help — допомога\n"
        "/clear — очистити історію розмови"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Як користуватись ботом:*\n\n"
        "Просто надсилай мені повідомлення — я пам'ятаю контекст розмови.\n\n"
        "*/start* — почати нову розмову (скидає контекст)\n"
        "*/clear* — очистити історію розмови\n"
        "*/help* — показати цю довідку",
        parse_mode="Markdown"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text("🧹 Історію розмови очищено! Починаємо з чистого аркуша.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    add_to_history(chat_id, "user", user_message)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id)

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        assistant_reply = response.choices[0].message.content
        add_to_history(chat_id, "assistant", assistant_reply)
        await update.message.reply_text(assistant_reply)

    except Exception as e:
        logger.error(f"Groq API error: {e}")
        await update.message.reply_text("❌ Виникла помилка при зверненні до AI. Спробуй ще раз.")


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
