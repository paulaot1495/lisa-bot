import os
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

claude = Anthropic(api_key=ANTHROPIC_KEY)

conversaciones = {}

SYSTEM_PROMPT = """Cuando diga hola, respondeme con hola paula como estas?"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋 Soy tu AI Manager.\n\n"
        "Estoy aquí para ayudarte a organizarte, priorizar y tomar mejores decisiones.\n\n"
        "¿En qué trabajamos hoy?"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text("✅ Historial borrado. ¡Empezamos de cero!")

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Comandos disponibles:*\n\n"
        "/start — Iniciar o reiniciar el bot\n"
        "/reset — Borrar el historial de conversación\n"
        "/ayuda — Ver esta ayuda\n\n"
        "O simplemente escríbeme lo que necesites 💬",
        parse_mode="Markdown"
    )

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    mensaje = update.message.text

    if user.id not in conversaciones:
        conversaciones[user.id] = []

    conversaciones[user.id].append({
        "role": "user",
        "content": mensaje
    })

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:                                          # ← aquí, DENTRO de la función
        respuesta = claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=conversaciones[user.id]
        )

        texto_respuesta = respuesta.content[0].text

        conversaciones[user.id].append({
            "role": "assistant",
            "content": texto_respuesta
        })

        if len(conversaciones[user.id]) > 10:
            conversaciones[user.id] = conversaciones[user.id][-10:]

        await update.message.reply_text(texto_respuesta)

    except Exception as e:
        logger.error(f"Error llamando a Claude: {e}")
        await update.message.reply_text("⚠️ Hubo un error. Inténtalo de nuevo.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    logger.info("🤖 Bot arrancado y escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()