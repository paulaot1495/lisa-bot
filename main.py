"""
main.py — Bot de Telegram Lisa
Lisa coordina. Solo delega en el agente de nutrición si el usuario lo pide explícitamente.
"""

import os
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from agents.nutrition import agent as nutrition

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

claude = Anthropic()
conversaciones: dict[int, list[dict]] = {}

SYSTEM_LISA = """Eres Lisa, una AI Manager personal. Hablas en español, eres directa y cálida.

Tienes acceso a un agente de nutrición. Úsalo SOLO si el usuario menciona explícitamente
"nutrición", "bot de nutrición", "agente de nutrición", o pide registrar/consultar comidas.

Si debes usar el agente de nutrición responde ÚNICAMENTE con: AGENTE:NUTRICION
En cualquier otro caso, responde tú directamente.

FORMATO: usa <b>negrita</b> e <i>cursiva</i> HTML. Sin asteriscos ni guiones bajos."""


# ── Comandos ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text(
        f"Hola {user.first_name} 👋\n\nSoy <b>Lisa</b>, tu AI Manager.\n\n<i>Dime qué necesitas.</i>",
        parse_mode="HTML",
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversaciones[update.effective_user.id] = []
    await update.message.reply_text("✅ Historial borrado.", parse_mode="HTML")


# ── Mensajes ──────────────────────────────────────────────────────────────────

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    mensaje = update.message.text.strip()
    conversaciones.setdefault(user.id, [])

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Lisa decide si deriva o responde ella
        conversaciones[user.id].append({"role": "user", "content": mensaje})
        decision = claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=SYSTEM_LISA,
            messages=conversaciones[user.id],
        ).content[0].text.strip()

        if decision == "AGENTE:NUTRICION":
            conversaciones[user.id].pop()  # el agente gestiona su propio contexto
            await update.message.reply_text("🥗 <i>Analizando...</i>", parse_mode="HTML")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            texto, teclado = await nutrition.run(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML", reply_markup=teclado)

        else:
            conversaciones[user.id].append({"role": "assistant", "content": decision})
            if len(conversaciones[user.id]) > 20:
                conversaciones[user.id] = conversaciones[user.id][-20:]
            await update.message.reply_text(decision, parse_mode="HTML")

    except Exception as e:
        logger.error(f"manejar_mensaje: {e}", exc_info=True)
        await update.message.reply_text("Hubo un error. Inténtalo de nuevo.")


# ── Callbacks ─────────────────────────────────────────────────────────────────

async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data.startswith("nutr_"):
        texto, _ = await nutrition.handle_callback(query.data)
        await query.edit_message_text(texto, parse_mode="HTML")


# ── Arranque ──────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(CallbackQueryHandler(manejar_callback))

    logger.info("🤖 Lisa arrancada y escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()