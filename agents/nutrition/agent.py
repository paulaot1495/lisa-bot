"""
agent.py — Agente de nutrición.

Responsabilidad: orquestar ia.py y storage.py para responder al usuario.

Flujo:
  1. main.py llama a run(mensaje) cuando detecta que el usuario quiere nutrición
  2. agent.py llama a ia.interpretar() para entender la intención
  3. Según la intención, llama a storage para leer/escribir
  4. Devuelve (texto_respuesta, teclado_opcional) a main.py

Separación clara:
  - ia.py     → solo habla con Claude
  - storage.py → solo toca el Excel
  - agent.py  → solo coordina y construye respuestas para Telegram
"""

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import ia, storage

logger = logging.getLogger(__name__)

# Tipo de retorno estándar del agente
AgentResponse = tuple[str, InlineKeyboardMarkup | None]


# ── Helpers de formato ────────────────────────────────────────────────────────

def _detectar_fecha(mensaje: str) -> datetime:
    """Devuelve ayer si el mensaje lo menciona, hoy en caso contrario."""
    if any(p in mensaje.lower() for p in ["ayer", "anoche"]):
        return datetime.now() - timedelta(days=1)
    return datetime.now()


def _teclado_confirmacion(fecha_str: str, scope: str) -> InlineKeyboardMarkup:
    """Genera el teclado inline de confirmación para borrados."""
    fecha_enc = fecha_str.replace("/", "-")  # '/' no permitido en callback_data
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Sí, borrar",
            callback_data=f"nutr_confirm_{scope}_{fecha_enc}",
        ),
        InlineKeyboardButton(
            "❌ Cancelar",
            callback_data="nutr_cancel",
        ),
    ]])


def _formatear_respuesta_registro(
    datos: dict,
    fecha_str: str,
    es_ayer: bool,
    es_nueva: bool,
) -> str:
    """Construye el mensaje HTML que se envía al usuario tras registrar."""
    t      = datos["totales"]
    dia    = "Día anterior" if es_ayer else "Hoy"
    estado = "nueva entrada" if es_nueva else "sumado a lo anterior"

    desglose = ""
    for alimento in datos.get("alimentos", []):
        desglose += (
            f"  <b>{alimento['nombre']}</b> ({alimento.get('cantidad_g', '?')}g)\n"
            f"    {alimento['calorias']:.0f} kcal  |  "
            f"{alimento['proteinas']:.1f}g prot  |  "
            f"{alimento['carbohidratos']:.1f}g CH  |  "
            f"{alimento['grasas']:.1f}g grasa\n"
        )

    return (
        f"{dia} — <b>{fecha_str}</b> <i>({estado})</i>\n\n"
        f"<b>{datos['descripcion_comida']}</b>\n\n"
        f"<b>Desglose por alimento:</b>\n"
        f"{desglose}\n"
        f"<b>Total acumulado del día:</b>\n"
        f"  Calorías:       <b>{t['calorias']:.0f} kcal</b>\n"
        f"  Proteínas:      <b>{t['proteinas']:.1f} g</b>\n"
        f"  Carbohidratos:  <b>{t['carbohidratos']:.1f} g</b>\n"
        f"  Grasas:         <b>{t['grasas']:.1f} g</b>\n"
        f"  Azúcar:         <b>{t['azucar']:.1f} g</b>\n"
        f"  Fibra:          <b>{t['fibra']:.1f} g</b>\n\n"
        f"<i>✅ Guardado en el Excel.</i>"
    )


# ── Punto de entrada principal ────────────────────────────────────────────────

async def run(mensaje: str) -> AgentResponse:
    """
    Punto de entrada único. main.py llama aquí.

    1. Carga contexto (base nutricional + historial últimos 30 días)
    2. Pide a Claude que interprete la intención
    3. Ejecuta la acción correspondiente
    4. Devuelve (texto, teclado) para que main.py lo envíe por Telegram
    """
    fecha  = _detectar_fecha(mensaje)
    es_ayer = (datetime.now() - fecha).days >= 1

    # Cargar contexto para Claude
    base      = storage.cargar_base_nutricional()
    historial = storage.leer_registros(dias=30)

    # Claude interpreta el mensaje
    try:
        intencion, datos = ia.interpretar(mensaje, base, historial)
    except ValueError as e:
        logger.error("Error interpretando mensaje: %s", e)
        return (
            "No pude entender tu mensaje nutricional. "
            "Intenta ser más específico (ej: <i>he comido 200g de pollo y arroz</i>).",
            None,
        )

    # ── Registrar comida ──────────────────────────────────────────────────────
    if intencion == "registrar":
        ok, es_nueva = storage.guardar_comida(datos, fecha)
        if not ok:
            return (
                "❌ Error al guardar en el Excel. "
                "Revisa que el volumen <code>/data</code> esté montado en Railway.",
                None,
            )
        return _formatear_respuesta_registro(
            datos, fecha.strftime("%d/%m/%Y"), es_ayer, es_nueva
        ), None

    # ── Consultar historial ───────────────────────────────────────────────────
    if intencion == "consultar":
        respuesta = datos.get("respuesta", "")
        if not respuesta:
            return "No encontré datos para analizar en tu registro.", None
        return respuesta, None

    # ── Borrar un día (pide confirmación) ────────────────────────────────────
    if intencion == "borrar_dia":
        fecha_str = fecha.strftime("%d/%m/%Y")
        dia_label = "ayer" if es_ayer else "hoy"
        return (
            f"<b>¿Seguro que quieres borrar el registro de {dia_label} ({fecha_str})?</b>\n\n"
            f"Se eliminará solo esa fila del Excel.\n"
            f"<i>Esta acción no se puede deshacer.</i>",
            _teclado_confirmacion(fecha_str, "dia"),
        )

    # ── Borrar todo (pide confirmación) ──────────────────────────────────────
    if intencion == "borrar_todo":
        fecha_str = datetime.now().strftime("%d/%m/%Y")
        return (
            "<b>¿Seguro que quieres borrar TODO el registro nutricional?</b>\n\n"
            "Se eliminará el Excel completo y se creará uno nuevo vacío.\n"
            "<i>Esta acción no se puede deshacer.</i>",
            _teclado_confirmacion(fecha_str, "todo"),
        )

    # No debería llegar aquí (ia.interpretar ya valida la intención)
    return "Acción no reconocida.", None


# ── Handler de callbacks (botones inline) ─────────────────────────────────────

async def handle_callback(data: str) -> AgentResponse:
    """
    Gestiona las respuestas a los botones de confirmación de borrado.
    main.py llama aquí cuando recibe un callback_data que empieza por 'nutr_'.
    """
    if data == "nutr_cancel":
        return "Cancelado. El registro no se ha modificado. 👍", None

    if data.startswith("nutr_confirm_"):
        # Formato: nutr_confirm_{scope}_{fecha_enc}
        # Usamos maxsplit=3 para que la fecha no se parta si contiene '_'
        partes    = data.split("_", 3)
        scope     = partes[2]                                    # "dia" o "todo"
        fecha_str = partes[3].replace("-", "/") if len(partes) > 3 else ""

        if scope == "todo":
            ok = storage.borrar_todo()
            return (
                "<b>✅ Registro completo eliminado.</b>\n"
                "El Excel está vacío y listo para empezar de cero.",
                None,
            ) if ok else ("❌ No pude borrar el Excel. Inténtalo de nuevo.", None)

        if scope == "dia":
            ok = storage.borrar_dia(fecha_str)
            return (
                f"<b>✅ Registro de {fecha_str} eliminado.</b>\n"
                "El resto del historial sigue intacto.",
                None,
            ) if ok else (
                f"No encontré datos para {fecha_str}. "
                "Puede que ya estuviera vacío.",
                None,
            )

    return "Acción de callback no reconocida.", None