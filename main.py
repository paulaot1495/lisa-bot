"""
main.py — Bot de Telegram Lisa
Versión corregida y refactorizada.

Cambios respecto al original:
  - Detección de mensajes de compra mejorada (más patrones, menos falsos positivos)
  - Gestión de confirmación de borrado separada en su propia función
  - manejar_callback reorganizado y sin código duplicado
  - Imports limpios
"""

import os
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from agente_compra import (
    agente_compra_con_confirmacion,
    ejecutar_borrado_confirmado,
    leer_items,
    manejar_callback_compra,
)
from agente_nutricion import (
    agente_nutricion,
    es_mensaje_nutricion,
    es_mensaje_reset_nutricion,
    agente_nutricion_reset,
    manejar_callback_nutricion,
    es_mensaje_consulta_nutricion,
    agente_consulta_nutricion,
)
from subir_archivo import manejar_documento

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

claude         = Anthropic(api_key=ANTHROPIC_KEY)
conversaciones: dict[int, list[dict]] = {}

# user_id → {"accion": str, "datos": dict}
pendiente_confirmacion: dict[int, dict] = {}

SYSTEM_PROMPT_LISA = """Eres Lisa, una AI Manager personal.
Hablas en español, eres directa, organizada y cálida.

Tu especialidad principal es gestionar la lista de la compra, pero también
ayudas con preguntas generales, planificación y decisiones del día a día.

FORMATO OBLIGATORIO — nunca uses asteriscos (*) ni guiones bajos (_):
- Para negrita usa: <b>texto</b>
- Para cursiva usa: <i>texto</i>
- Para listas usa guiones simples: - item
- Respuestas concisas y accionables siempre."""

# ─────────────────────────────────────────
# DETECCIÓN DE MENSAJES DE COMPRA
# ─────────────────────────────────────────

_TIENDAS = {
    "mercadona", "lidl", "carrefour", "alcampo", "corte inglés",
    "ikea", "amazon", "zara", "primark", "sklum", "leroy merlin",
    "media markt", "decathlon", "sephora", "mango", "aldi", "primor",
    "el corte inglés",
}

_FRASES_ACCION = (
    "añade ", "añadir ", "apunta ", "agrega ", "agregar ",
    "ya compré", "ya he comprado", "he comprado",
    "tacha ", "tachame ", "táchame ",
    "borra de la lista", "elimina de la lista", "quita de la lista",
    "elimina ", "quita ",
    "mi lista", "ver lista", "muéstrame la lista", "enseñame la lista",
    "qué me falta", "qué tengo pendiente", "qué necesito comprar",
    "lista de la compra", "compra de ", "hice la compra", "he hecho la compra",
    "limpia la categoría", "limpia los ", "limpia las ", "limpia ",
    "cambia el ", "cambia la ", "actualiza el ", "actualiza la ",
    "ponlo en ", "ponla en ", "muévelo a ", "muévela a ",
    "urgente", "urgentes",
    "ver categoría", "ver tienda", "filtrar por",
)


def es_mensaje_de_compra(mensaje: str) -> bool:
    ml = mensaje.lower()
    if any(t in ml for t in _TIENDAS):
        return True
    if any(ml.startswith(f) or f" {f}" in ml for f in _FRASES_ACCION):
        return True
    return False


# ─────────────────────────────────────────
# HANDLERS DE COMANDOS
# ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text(
        f"Hola {user.first_name} 👋\n\n"
        "Soy <b>Lisa</b>, tu AI Manager.\n\n"
        "Puedo ayudarte con tu lista de la compra y con lo que necesites.\n\n"
        "<i>Dime qué necesitas.</i>",
        parse_mode="HTML",
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text("✅ Historial borrado.", parse_mode="HTML")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 <b>Lisa — AI Manager</b>\n\n"
        "<b>Lista de la compra:</b>\n"
        "- <i>Añade leche x2 en Mercadona</i>\n"
        "- <i>Qué me falta en Mercadona</i>\n"
        "- <i>Ya compré el pan</i>\n"
        "- <i>Muéstrame la lista</i>\n"
        "- <i>Solo los urgentes</i>\n"
        "- <i>Muéstrame alimentación de Mercadona</i>\n\n"
        "<b>Comandos:</b>\n"
        "/start — Reiniciar\n"
        "/reset — Borrar historial\n"
        "/ayuda — Esta ayuda",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────
# HANDLER DE MENSAJES DE TEXTO
# ─────────────────────────────────────────

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    mensaje = update.message.text.strip()

    if user.id not in conversaciones:
        conversaciones[user.id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        if es_mensaje_de_compra(mensaje):
            await update.message.reply_text("🛒 <i>Consultando tu lista...</i>", parse_mode="HTML")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

            resultado = await agente_compra_con_confirmacion(mensaje)

            if resultado["tipo"] == "confirmacion":
                # Guardamos qué hay que ejecutar si el usuario confirma
                pendiente_confirmacion[user.id] = {
                    "accion": resultado["accion"],
                    "datos":  resultado["datos"],
                }
                botones = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Sí, borrar",  callback_data="confirmar_borrado"),
                    InlineKeyboardButton("❌ Cancelar",    callback_data="cancelar_borrado"),
                ]])
                await update.message.reply_text(
                    resultado["texto"], parse_mode="HTML", reply_markup=botones
                )
            else:
                await update.message.reply_text(
                    resultado["texto"],
                    parse_mode="HTML",
                    reply_markup=resultado.get("teclado"),
                )

        elif es_mensaje_reset_nutricion(mensaje):
            texto, teclado = await agente_nutricion_reset(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML", reply_markup=teclado)

        elif es_mensaje_consulta_nutricion(mensaje):
            await update.message.reply_text("📊 <i>Consultando tu registro...</i>", parse_mode="HTML")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            texto = await agente_consulta_nutricion(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML")

        elif es_mensaje_nutricion(mensaje):
            await update.message.reply_text("🥗 <i>Analizando tu comida...</i>", parse_mode="HTML")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            texto, _ = await agente_nutricion(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML")

        else:
            conversaciones[user.id].append({"role": "user", "content": mensaje})
            resp = claude.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                system=SYSTEM_PROMPT_LISA,
                messages=conversaciones[user.id],
            )
            respuesta_texto = resp.content[0].text
            conversaciones[user.id].append({"role": "assistant", "content": respuesta_texto})
            # Limitar historial a las últimas 10 interacciones
            if len(conversaciones[user.id]) > 20:
                conversaciones[user.id] = conversaciones[user.id][-20:]
            await update.message.reply_text(respuesta_texto, parse_mode="HTML")

    except Exception as e:
        logger.error(f"manejar_mensaje: {e}", exc_info=True)
        await update.message.reply_text(
            "Hubo un error. Inténtalo de nuevo.", parse_mode="HTML"
        )


# ─────────────────────────────────────────
# HANDLER DE CALLBACKS INLINE
# ─────────────────────────────────────────

async def _gestionar_confirmacion_limpiar_tienda(
    query, user_id: int, tienda: str
) -> None:
    """
    Lógica compartida para el botón 'Compra hecha' de la vista de tienda.
    Siempre pide confirmación (independientemente del número de artículos),
    porque el usuario pulsó el botón explícitamente.
    """
    items     = leer_items()
    afectados = [i for i in items if i["tienda"].lower() == tienda]
    if not afectados:
        await query.edit_message_text(
            f"No hay productos de <b>{tienda.capitalize()}</b>.",
            parse_mode="HTML",
        )
        return

    lineas = [
        f"🗑 <b>¿Borrar toda la compra de {tienda.capitalize()}?</b>",
        f"<i>{len(afectados)} productos se eliminarán:</i>",
        "",
    ]
    for p in afectados:
        lineas.append(f"  ⚪ {p['producto']}  ×{p['cantidad']}")

    pendiente_confirmacion[user_id] = {
        "accion": "limpiar_tienda",
        "datos":  {"tienda": tienda},
    }
    botones = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sí, borrar",  callback_data="confirmar_borrado"),
        InlineKeyboardButton("❌ Cancelar",    callback_data="cancelar_borrado"),
    ]])
    await query.edit_message_text(
        "\n".join(lineas), parse_mode="HTML", reply_markup=botones
    )


async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user    = query.from_user
    data    = query.data

    # ── Confirmar borrado ────────────────────────────────────────────────────
    if data == "confirmar_borrado":
        pendiente = pendiente_confirmacion.pop(user.id, None)
        if not pendiente:
            await query.edit_message_text(
                "⚠️ La acción ya expiró. Vuelve a pedirlo.",
                parse_mode="HTML",
            )
            return
        texto, teclado = await ejecutar_borrado_confirmado(
            pendiente["accion"], pendiente["datos"]
        )
        await query.edit_message_text(text=texto, parse_mode="HTML", reply_markup=teclado)
        return

    # ── Cancelar borrado ─────────────────────────────────────────────────────
    if data == "cancelar_borrado":
        pendiente_confirmacion.pop(user.id, None)
        await query.edit_message_text(
            "❌ <b>Cancelado.</b> La lista no se ha modificado.",
            parse_mode="HTML",
        )
        return

    # ── Botón "Compra hecha — borrar tienda" ─────────────────────────────────
    if data.startswith("limpiar_"):
        tienda = data.removeprefix("limpiar_")
        await _gestionar_confirmacion_limpiar_tienda(query, user.id, tienda)
        return

    # ── Callbacks de nutrición ───────────────────────────────────────────────
    if data.startswith("nutricion_"):
        texto, _ = await manejar_callback_nutricion(data)
        await query.edit_message_text(text=texto, parse_mode="HTML")
        return

    # ── Callbacks de compra (navegación) ─────────────────────────────────────
    texto, teclado = await manejar_callback_compra(data)
    await query.edit_message_text(text=texto, parse_mode="HTML", reply_markup=teclado)


# ─────────────────────────────────────────
# ARRANQUE
# ─────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.Document.ALL, manejar_documento))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(CallbackQueryHandler(manejar_callback))

    logger.info("🤖 Lisa arrancada y escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()