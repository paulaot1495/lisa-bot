"""
main.py — Bot de Telegram: Lisa, AI Manager personal.

Arquitectura:
  - Lisa responde conversación general directamente con Claude
  - Cuando el usuario menciona nutrición, Lisa devuelve el token AGENTE:NUTRICION
    y main.py deriva al agente correspondiente
  - Los callbacks de botones inline se enrutan por prefijo

Para añadir un nuevo agente en el futuro:
  1. Crea agents/<nombre>/agent.py con run() y handle_callback()
  2. Importa el agente aquí
  3. Añade "AGENTE:<NOMBRE>" al SYSTEM_LISA
  4. Añade el elif en manejar_mensaje()
  5. Añade el routing por prefijo en manejar_callback()
"""

import logging
import os

from anthropic import Anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents.nutrition import agent as nutrition_agent

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_TOKEN:
    raise EnvironmentError("Falta la variable de entorno TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

claude         = Anthropic()
_conversaciones: dict[int, list[dict]] = {}

# ── System prompt de Lisa ─────────────────────────────────────────────────────

SYSTEM_LISA = """Eres Lisa, una AI Manager personal. Hablas en español, eres directa, organizada y cálida.

AGENTES DISPONIBLES:
- Agente de nutrición: registra comidas, consulta macros y gestiona el historial nutricional.

REGLA DE DERIVACIÓN — MUY IMPORTANTE:
Si el usuario menciona "nutrición", "agente de nutrición", "bot de nutrición", "gente de nutrición",
o pide registrar/consultar/borrar comidas o macros, tu respuesta debe ser ÚNICAMENTE este token:
AGENTE:NUTRICION

No añadas texto antes ni después. Solo el token exacto, nada más.

En cualquier otro caso, responde tú directamente de forma concisa y útil.

FORMATO (cuando respondes tú directamente):
- Usa <b>negrita</b> e <i>cursiva</i> HTML. Nunca asteriscos ni guiones bajos."""


# ── Comandos ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    _conversaciones[user.id] = []
    await update.message.reply_text(
        f"Hola {user.first_name} 👋\n\n"
        "Soy <b>Lisa</b>, tu AI Manager personal.\n\n"
        "Para gestionar tu nutrición dime algo como:\n"
        "<i>«Dile al agente de nutrición que he comido una tortilla»</i>\n\n"
        "¿En qué trabajamos hoy?",
        parse_mode="HTML",
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _conversaciones[update.effective_user.id] = []
    await update.message.reply_text("✅ Historial de conversación borrado.", parse_mode="HTML")


# ── Handler principal de mensajes ─────────────────────────────────────────────

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    mensaje = update.message.text.strip()

    _conversaciones.setdefault(user.id, [])
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        _conversaciones[user.id].append({"role": "user", "content": mensaje})

        decision = claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=50,          # El token tiene 16 chars; 50 es más que suficiente
            system=SYSTEM_LISA,
            messages=_conversaciones[user.id],
        ).content[0].text.strip()

        # ── Derivar al agente de nutrición ────────────────────────────────────
        # Usamos "in" en vez de "==" para ser robustos ante texto extra de Claude
        if "AGENTE:NUTRICION" in decision.upper():
            _conversaciones[user.id].pop()  

            await update.message.reply_text(
                "🥗 <i>Consultando el agente de nutrición...</i>",
                parse_mode="HTML",
            )
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action="typing"
            )

            texto, teclado = await nutrition_agent.run(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML", reply_markup=teclado)

        # ── Lisa responde directamente ─────────────────────────────────────────
        else:
            _conversaciones[user.id].append({"role": "assistant", "content": decision})

            # Mantener solo los últimos 10 turnos (20 mensajes) para no crecer indefinidamente
            if len(_conversaciones[user.id]) > 20:
                _conversaciones[user.id] = _conversaciones[user.id][-20:]

            await update.message.reply_text(decision, parse_mode="HTML")

    except Exception:
        logger.exception("Error en manejar_mensaje (user_id=%s)", user.id)
        await update.message.reply_text(
            "Ocurrió un error inesperado. Inténtalo de nuevo.",
            parse_mode="HTML",
        )


# ── Handler de callbacks (botones inline) ─────────────────────────────────────

async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data  = query.data

    try:
        if data.startswith("nutr_"):
            texto, teclado = await nutrition_agent.handle_callback(data)
            await query.edit_message_text(texto, parse_mode="HTML", reply_markup=teclado)
            return

        logger.warning("Callback no reconocido: %s", data)
        await query.edit_message_text("Acción no reconocida.", parse_mode="HTML")

    except Exception:
        logger.exception("Error en manejar_callback (data=%s)", data)
        await query.edit_message_text(
            "Ocurrió un error procesando esta acción.",
            parse_mode="HTML",
        )


# ── Arranque ──────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(CallbackQueryHandler(manejar_callback))

    logger.info("🤖 Lisa arrancada y escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()