import os
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agentes import agente_redactor, agente_resumen

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

# ─────────────────────────────────────────
# LISA: el cerebro coordinador
# Su trabajo es DECIDIR qué agente usar
# ─────────────────────────────────────────
SYSTEM_PROMPT_LISA = """Eres Lisa, una AI Manager coordinadora.
Tienes a tu disposición estos agentes especializados:

- REDACTOR: para escribir emails, posts, mensajes, textos de cualquier tipo
- RESUMEN: para resumir textos, artículos, documentos largos
- LISA: para todo lo demás (preguntas generales, planificación, decisiones)

Tu trabajo es:
1. Leer el mensaje del usuario
2. Decidir qué agente es el más adecuado
3. Responder ÚNICAMENTE con una línea en este formato exacto:
   AGENTE: REDACTOR
   AGENTE: RESUMEN
   AGENTE: LISA

Nada más. Solo esa línea. No expliques nada."""


async def decidir_agente(mensaje: str) -> str:
    """Lisa decide qué agente usar"""
    respuesta = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=20,  # Solo necesita decir el nombre del agente
        system=SYSTEM_PROMPT_LISA,
        messages=[{"role": "user", "content": mensaje}]
    )
    decision = respuesta.content[0].text.strip().upper()
    logger.info(f"Lisa decidió: {decision}")
    return decision


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋 Soy Lisa, tu AI Manager.\n\n"
        "Tengo dos agentes listos para ayudarte:\n"
        "✍️ *Redactor* — escribe emails, posts, mensajes\n"
        "📋 *Resumen* — resume cualquier texto\n\n"
        "Dime qué necesitas y yo coordino todo 🎯",
        parse_mode="Markdown"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text("✅ Historial borrado. ¡Empezamos de cero!")

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Lisa — AI Manager*\n\n"
        "Agentes disponibles:\n"
        "✍️ *Redactor* — 'Escríbeme un email para...'\n"
        "📋 *Resumen* — 'Resume este texto: ...'\n\n"
        "Comandos:\n"
        "/start — Reiniciar\n"
        "/reset — Borrar historial\n"
        "/ayuda — Esta ayuda",
        parse_mode="Markdown"
    )

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    mensaje = update.message.text

    if user.id not in conversaciones:
        conversaciones[user.id] = []

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # 1. Lisa decide qué agente usar
        decision = await decidir_agente(mensaje)

        # 2. Llamar al agente correcto
        if "REDACTOR" in decision:
            await update.message.reply_text("✍️ *Pasando al agente Redactor...*", parse_mode="Markdown")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            respuesta_texto = await agente_redactor(mensaje)

        elif "RESUMEN" in decision:
            await update.message.reply_text("📋 *Pasando al agente Resumen...*", parse_mode="Markdown")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            respuesta_texto = await agente_resumen(mensaje)

        else:
            # Lisa responde ella misma
            conversaciones[user.id].append({"role": "user", "content": mensaje})
            resp = claude.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                system="Eres Lisa, una AI Manager personal. Hablas en español, eres directa y útil.",
                messages=conversaciones[user.id]
            )
            respuesta_texto = resp.content[0].text
            conversaciones[user.id].append({"role": "assistant", "content": respuesta_texto})

            if len(conversaciones[user.id]) > 10:
                conversaciones[user.id] = conversaciones[user.id][-10:]

        await update.message.reply_text(respuesta_texto)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("⚠️ Hubo un error. Inténtalo de nuevo.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    logger.info("🤖 Lisa arrancada y escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()