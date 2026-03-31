"""
subir_archivo.py — Handler para subir base_nutricional.xlsx a /data vía Telegram.
Añade esto a bot.py para poder enviar el Excel directamente por chat.
"""

import os
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

BASE_NUTRICIONAL_PATH = Path(os.getenv("BASE_NUTRICIONAL_PATH", "/data/base_nutricional.xlsx"))


async def manejar_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda cualquier .xlsx recibido como base_nutricional si el nombre lo indica,
    o pregunta al usuario qué quiere hacer con él."""
    doc = update.message.document

    if not doc.file_name.endswith(".xlsx"):
        await update.message.reply_text(
            "⚠️ Solo acepto archivos <b>.xlsx</b>.",
            parse_mode="HTML"
        )
        return

    nombre = doc.file_name.lower()
    es_base = any(p in nombre for p in ["nutricional", "base", "alimento", "macro"])

    await update.message.reply_text(
        f"📥 <i>Recibiendo <b>{doc.file_name}</b>...</i>",
        parse_mode="HTML"
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        BASE_NUTRICIONAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        await file.download_to_drive(str(BASE_NUTRICIONAL_PATH))

        await update.message.reply_text(
            f"✅ <b>{doc.file_name}</b> guardado correctamente como base nutricional.\n\n"
            f"<i>Ruta: {BASE_NUTRICIONAL_PATH}</i>\n\n"
            f"A partir de ahora usaré tus datos para calcular macros.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error guardando archivo: {e}")
        await update.message.reply_text(
            "❌ No pude guardar el archivo. Comprueba que el volumen /data está montado en Railway.",
            parse_mode="HTML"
        )


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRACIÓN EN bot.py
# Añade estas dos líneas en la función main(), junto a los otros handlers:
#
#   from subir_archivo import manejar_documento
#   app.add_handler(MessageHandler(filters.Document.ALL, manejar_documento))
#
# ─────────────────────────────────────────────────────────────────────────────