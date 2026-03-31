import os
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from agente_compra import agente_compra, manejar_callback_compra
from agente_nutricion import agente_nutricion, es_mensaje_nutricion
from subir_archivo import manejar_documento

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

claude = Anthropic(api_key=ANTHROPIC_KEY)
conversaciones = {}

SYSTEM_PROMPT_LISA = """Eres Lisa, una AI Manager personal.
Hablas en español, eres directa, organizada y cálida.

Tu especialidad principal es gestionar la lista de la compra, pero también
ayudas con preguntas generales, planificación y decisiones del día a día.

FORMATO OBLIGATORIO — nunca uses asteriscos (*) ni guiones bajos (_):
- Para negrita usa: <b>texto</b>
- Para cursiva usa: <i>texto</i>
- Para listas usa guiones simples: - item
- Respuestas concisas y accionables siempre."""


def es_mensaje_de_compra(mensaje: str) -> bool:
    palabras_clave = [
        "compra", "lista", "tienda", "mercadona", "lidl", "carrefour", "alcampo",
        "corte inglés", "ikea", "amazon", "zara", "primark", "leche", "pan",
        "añade", "añadir", "necesito", "falta", "faltan", "queda", "quedan",
        "urgente", "compré", "ya compré", "borrar", "elimina", "tacha",
        "qué me falta", "qué necesito", "muéstrame", "ver lista", "mi lista",
        "pendiente", "productos",
    ]
    mensaje_lower = mensaje.lower()
    return any(p in mensaje_lower for p in palabras_clave)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text(
        f"Hola {user.first_name} 👋\n\n"
        "Soy <b>Lisa</b>, tu AI Manager.\n\n"
        "Puedo ayudarte con tu lista de la compra y con lo que necesites.\n\n"
        "<i>Dime qué necesitas.</i>",
        parse_mode="HTML"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversaciones[user.id] = []
    await update.message.reply_text("✅ Historial borrado.", parse_mode="HTML")

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Lisa — AI Manager</b>\n\n"
        "<b>Lista de la compra:</b>\n"
        "- <i>Añade leche x2 en Mercadona</i>\n"
        "- <i>Qué me falta en Mercadona</i>\n"
        "- <i>Ya compré el pan</i>\n"
        "- <i>Muéstrame la lista</i>\n"
        "- <i>Solo los urgentes</i>\n\n"
        "<b>Comandos:</b>\n"
        "/start — Reiniciar\n"
        "/reset — Borrar historial\n"
        "/ayuda — Esta ayuda",
        parse_mode="HTML"
    )


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    mensaje = update.message.text

    if user.id not in conversaciones:
        conversaciones[user.id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        if es_mensaje_de_compra(mensaje):
            await update.message.reply_text("🛒 <i>Consultando tu lista...</i>", parse_mode="HTML")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            texto, teclado = await agente_compra(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML", reply_markup=teclado)

        elif es_mensaje_reset_nutricion(mensaje):                         
            texto, teclado = await agente_nutricion_reset(mensaje)
            await update.message.reply_text(texto, parse_mode="HTML",     
                                            reply_markup=teclado)         

        elif es_mensaje_nutricion(mensaje):                          
            await update.message.reply_text(                         
                "🥗 <i>Analizando tu comida...</i>",                 
                parse_mode="HTML"                                    
            )                                                        
            await context.bot.send_chat_action(                      
                chat_id=update.effective_chat.id, action="typing"    
            )                                                        
            texto = await agente_nutricion(mensaje)                  
            await update.message.reply_text(texto, parse_mode="HTML")
        else:
            conversaciones[user.id].append({"role": "user", "content": mensaje})
            resp = claude.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                system=SYSTEM_PROMPT_LISA,
                messages=conversaciones[user.id]
            )
            respuesta_texto = resp.content[0].text
            conversaciones[user.id].append({"role": "assistant", "content": respuesta_texto})
            if len(conversaciones[user.id]) > 10:
                conversaciones[user.id] = conversaciones[user.id][-10:]
            await update.message.reply_text(respuesta_texto, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Hubo un error. Inténtalo de nuevo.", parse_mode="HTML")


async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("nutricion_"):
        texto, _ = await manejar_callback_nutricion(query.data)
        await query.edit_message_text(text=texto, parse_mode="HTML")
        return

    texto, teclado = await manejar_callback_compra(query.data)
    await query.edit_message_text(text=texto, parse_mode="HTML", reply_markup=teclado)


def main():
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