"""
subir_archivo.py — Handler para subir archivos .xlsx a /data vía Telegram.
Guarda cada archivo con su nombre original dentro de /data.
"""

import os
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))


async def manejar_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if not doc.file_name.endswith(".xlsx"):
        await update.message.reply_text(
            "⚠️ Solo acepto archivos <b>.xlsx</b>.",
            parse_mode="HTML"
        )
        return

    destino = DATA_DIR / doc.file_name

    await update.message.reply_text(
        f"📥 <i>Recibiendo <b>{doc.file_name}</b>...</i>",
        parse_mode="HTML"
    )

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(str(destino))

        await update.message.reply_text(
            f"✅ <b>{doc.file_name}</b> guardado correctamente.\n\n"
            f"<i>Ruta: {destino}</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error guardando archivo: {e}")
        await update.message.reply_text(
            "❌ No pude guardar el archivo. Comprueba que el volumen /data está montado en Railway.",
            parse_mode="HTML"
        )