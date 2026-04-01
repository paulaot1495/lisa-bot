"""
agent.py — Agente de nutrición.
Detecta intención → llama a ia.py o storage.py → devuelve respuesta + teclado opcional.
"""

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import ia, storage

logger = logging.getLogger(__name__)

# ── Detección de intención ────────────────────────────────────────────────────

_PALABRAS_COMIDA = [
    "comí", "comi", "desayuné", "desayune", "almorcé", "almorce",
    "merendé", "merende", "cené", "cene", "tomé", "tome", "bebí", "bebi",
    "desayuno", "almuerzo", "comida", "merienda", "cena", "snack",
    "he comido", "he desayunado", "he cenado", "he almorzado",
    "me he comido", "me tomé", "ayer comí", "ayer cené", "ayer desayuné",
]
_PALABRAS_RESET = [
    "borrar comidas", "borrar registro", "resetear comidas", "resetear nutricion",
    "borrar nutricion", "empezar de cero", "limpiar excel", "limpiar comidas",
    "eliminar comidas", "reset comidas",
]
_PALABRAS_CONSULTA = [
    "macros de hoy", "macros de ayer", "que llevo hoy", "que llevo comido",
    "cuanto llevo", "resumen de hoy", "resumen de ayer", "resumen del dia",
    "resumen de la semana", "resumen semanal", "resumen del mes", "resumen mensual",
    "como voy", "tendencias", "analisis", "cuantas calorias llevo",
    "mis macros", "mi registro", "ver registro", "historial",
    "media semanal", "estadisticas",
]

def es_comida(msg: str) -> bool:
    return any(p in msg.lower() for p in _PALABRAS_COMIDA)

def es_reset(msg: str) -> bool:
    return any(p in msg.lower() for p in _PALABRAS_RESET)

def es_consulta(msg: str) -> bool:
    return any(p in msg.lower() for p in _PALABRAS_CONSULTA)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _detectar_fecha(msg: str) -> datetime:
    if any(p in msg.lower() for p in ["ayer", "anoche"]):
        return datetime.now() - timedelta(days=1)
    return datetime.now()

def _rango_consulta(msg: str) -> int:
    m = msg.lower()
    if any(p in m for p in ["mes", "mensual", "30 dias"]):
        return 30
    if any(p in m for p in ["semana", "semanal", "7 dias"]):
        return 7
    if "ayer" in m:
        return 2
    return 1  # hoy por defecto

def _teclado_reset(fecha_str: str, scope: str) -> InlineKeyboardMarkup:
    fecha_enc = fecha_str.replace("/", "-")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Sí, borrar", callback_data=f"nutr_confirm_{scope}_{fecha_enc}"),
        InlineKeyboardButton("Cancelar", callback_data="nutr_cancel"),
    ]])

def _respuesta_comida(datos: dict, fecha_str: str, es_ayer: bool, es_nueva: bool) -> str:
    t = datos["totales"]
    estado = "nueva entrada" if es_nueva else "sumado a lo anterior"
    dia = "Día anterior" if es_ayer else "Hoy"

    desglose = ""
    for a in datos.get("alimentos", []):
        desglose += (
            f"  <b>{a['nombre']}</b> ({a.get('cantidad_g', '?')}g)\n"
            f"    {a['calorias']:.0f} kcal | {a['proteinas']:.1f}g prot | "
            f"{a['carbohidratos']:.1f}g CH | {a['grasas']:.1f}g grasa\n"
        )

    return (
        f"{dia} — <b>{fecha_str}</b> <i>({estado})</i>\n\n"
        f"<b>{datos['descripcion_comida']}</b>\n\n"
        f"<b>Desglose:</b>\n{desglose}\n"
        f"<b>Total acumulado:</b>\n"
        f"  Calorías:      <b>{t['calorias']:.0f} kcal</b>\n"
        f"  Proteínas:     <b>{t['proteinas']:.1f} g</b>\n"
        f"  Carbohidratos: <b>{t['carbohidratos']:.1f} g</b>\n"
        f"  Grasas:        <b>{t['grasas']:.1f} g</b>\n"
        f"  Azúcar:        <b>{t['azucar']:.1f} g</b>\n"
        f"  Fibra:         <b>{t['fibra']:.1f} g</b>\n\n"
        f"<i>Excel actualizado.</i>"
    )

# ── Handlers públicos ─────────────────────────────────────────────────────────

async def handle_comida(mensaje: str) -> tuple[str, None]:
    """Analiza la comida con IA y guarda en el Excel."""
    fecha = _detectar_fecha(mensaje)
    es_ayer = (datetime.now() - fecha).days >= 1
    base = storage.cargar_base_nutricional()

    try:
        datos = ia.analizar_comida(mensaje, base)
    except Exception as e:
        logger.error(f"Error IA: {e}")
        return "No pude analizar la información nutricional. Inténtalo de nuevo.", None

    ok, es_nueva = storage.guardar_comida(datos, fecha)
    if not ok:
        return "Error al guardar en el Excel. Revisa que /data esté montado.", None

    return _respuesta_comida(datos, fecha.strftime("%d/%m/%Y"), es_ayer, es_nueva), None


async def handle_reset(mensaje: str) -> tuple[str, InlineKeyboardMarkup]:
    """Pide confirmación antes de borrar."""
    m = mensaje.lower()
    if any(p in m for p in ["todo", "registro", "excel", "cero", "completo"]):
        return (
            "<b>¿Seguro que quieres borrar TODO el registro?</b>\n\n"
            "Se eliminará el Excel completo. <i>No se puede deshacer.</i>",
            _teclado_reset(datetime.now().strftime("%d/%m/%Y"), "todo")
        )

    fecha = _detectar_fecha(mensaje)
    fecha_str = fecha.strftime("%d/%m/%Y")
    dia_label = "ayer" if (datetime.now() - fecha).days >= 1 else "hoy"
    return (
        f"<b>¿Seguro que quieres borrar el registro de {dia_label} ({fecha_str})?</b>\n\n"
        f"Se eliminará solo esa fila. <i>No se puede deshacer.</i>",
        _teclado_reset(fecha_str, "dia")
    )


async def handle_consulta(mensaje: str) -> tuple[str, None]:
    """Lee el Excel y pide a Claude que analice la consulta."""
    dias = _rango_consulta(mensaje)
    registros = storage.leer_registros(dias)

    if not registros:
        periodo = {1: "hoy", 7: "esta semana", 30: "este mes"}.get(dias, f"los últimos {dias} días")
        return f"No tengo datos para {periodo}. Cuéntame qué has comido y lo apunto.", None

    return ia.analizar_registro(mensaje, registros, dias), None


async def handle_callback(data: str) -> tuple[str, None]:
    """Maneja los botones de confirmación de reset."""
    if data == "nutr_cancel":
        return "Cancelado. El registro sigue intacto.", None

    if data.startswith("nutr_confirm_"):
        partes = data.split("_", 3)          # ['nutr', 'confirm', scope, fecha]
        scope = partes[2]
        fecha_str = partes[3].replace("-", "/") if len(partes) > 3 else ""

        if scope == "todo":
            ok = storage.borrar_todo()
            return ("<b>Registro completo borrado.</b> Excel vacío y listo.", None) if ok \
                else ("No pude borrar el Excel.", None)

        if scope == "dia":
            ok = storage.borrar_dia(fecha_str)
            return (f"<b>Registro de {fecha_str} eliminado.</b>", None) if ok \
                else (f"No encontré datos para {fecha_str}.", None)

    return "Acción no reconocida.", None