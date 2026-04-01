"""
agent.py — Agente de nutrición.

Responsabilidad: orquestar ia.py y storage.py para responder al usuario.

Detección de intención: palabras clave (determinista, sin IA)
Cálculo de macros:      ia.py (Claude, solo cuando es necesario)
Persistencia:           storage.py (Excel)

Flujo:
  run(mensaje)
    → _limpiar_mensaje()     ← elimina ruido conversacional antes de pasar a Claude
    → _detectar_intencion()  ← palabras clave, sin Claude
    → si "registrar"         → ia.calcular_macros() + storage.guardar_comida()
    → si "consultar"         → ia.analizar_historial() + storage.leer_registros()
    → si "borrar_dia"        → pedir confirmación (sin Claude)
    → si "borrar_todo"       → pedir confirmación (sin Claude)
"""

import logging
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import ia, storage

logger = logging.getLogger(__name__)

AgentResponse = tuple[str, InlineKeyboardMarkup | None]


# ── Limpieza del mensaje (Bug 1) ──────────────────────────────────────────────

# Frases conversacionales que el usuario añade para dirigirse al agente
# pero que no aportan información nutricional
_RUIDO_CONVERSACIONAL = [
    r"d[íi]le al (?:bot|agente) de nutrici[oó]n que",
    r"d[íi]le a la gente de nutrici[oó]n que",
    r"(?:bot|agente) de nutrici[oó]n[,:]?\s*",
    r"dile que",
    r"por favor[,:]?\s*",
    r"oye[,:]?\s*",
    r"mira[,:]?\s*",
    r"eh[,:]?\s*",
]
_PATRON_RUIDO = re.compile(
    "|".join(_RUIDO_CONVERSACIONAL),
    flags=re.IGNORECASE,
)

def _limpiar_mensaje(mensaje: str) -> str:
    """
    Elimina el ruido conversacional del mensaje antes de pasarlo a Claude.
    'dile al bot de nutrición que hoy he comido pasta' → 'hoy he comido pasta'
    """
    limpio = _PATRON_RUIDO.sub("", mensaje).strip()
    # Eliminar comas o espacios sobrantes al inicio
    return limpio.lstrip(", ").strip()


# ── Detección de intención (palabras clave, determinista) ─────────────────────

_BORRAR_TODO = [
    "borra todo", "borra el excel", "borra el registro",
    "elimina todo", "limpia todo", "limpia el excel",
    "resetea todo", "empezar de cero", "empieza de cero",
    "borra todo el historial", "elimina todo el historial",
    "limpiar todo", "borrar todo", "resetear todo",
    "reset total", "borrar registro completo",
    # Tercera persona
    "que borre todo", "que elimine todo", "que limpie todo",
    "que resetee todo", "que borre el registro", "que elimine el registro",
    "que borre el excel", "que limpie el excel",
]

_BORRAR_DIA = [
    "borra lo de hoy", "borra lo de ayer",
    "borra el registro de hoy", "borra el registro de ayer",
    "elimina lo de hoy", "elimina lo de ayer",
    "quita lo de hoy", "quita lo de ayer",
    "resetea hoy", "resetea ayer",
    "empieza de cero hoy", "empieza de cero ayer",
    "borra hoy", "borra ayer",
    "elimina hoy", "elimina ayer",
    "borrar hoy", "borrar ayer",
    # Tercera persona
    "que borre lo de hoy", "que borre lo de ayer",
    "que borre hoy", "que borre ayer",
    "que elimine lo de hoy", "que elimine lo de ayer",
    "que elimine hoy", "que elimine ayer",
    "que limpie hoy", "que limpie ayer",
    "que resetee hoy", "que resetee ayer",
    "que quite lo de hoy", "que quite lo de ayer",
]

_CONSULTAR = [
    # Primera persona
    "qué he comido", "que he comido",
    "qué llevo", "que llevo",
    "cuánto llevo", "cuanto llevo",
    "mis macros", "mis calorías", "mis calorias",
    "resumen", "historial", "mi registro",
    "cómo voy", "como voy",
    "qué he tomado", "que he tomado",
    "revísame", "revisame", "revisar",
    "muéstrame", "muestrame", "enséñame", "ensenname",
    "cuántas calorías", "cuantas calorias",
    "estadísticas", "estadisticas",
    "análisis", "analisis",
    "qué he desayunado", "que he desayunado",
    "qué he almorzado", "que he almorzado",
    "qué he cenado", "que he cenado",
    "dime lo que", "ver registro",
    "media semanal", "resumen semanal",
    "resumen del mes", "resumen mensual",
    # Tercera persona y subjuntivo (lo que queda tras limpiar el ruido)
    "me muestre", "me enseñe", "me ense\u00f1e", "me indique",
    "me diga", "me explique", "me dé", "me de",
    "muestre", "enseñe", "indique", "explique",
    "qué ha comido", "que ha comido",
    "qué lleva", "que lleva",
    "cuánto lleva", "cuanto lleva",
    "sus macros", "sus calorías", "sus calorias",
    "cómo va", "como va",
    "qué ha tomado", "que ha tomado",
    "qué ha desayunado", "que ha desayunado",
    "qué ha almorzado", "que ha almorzado",
    "qué ha cenado", "que ha cenado",
]
 
_REGISTRAR = [
    # Primera persona
    "he comido", "he desayunado", "he cenado",
    "he almorzado", "he merendado", "he bebido",
    "comí", "desayuné", "almorcé", "cené", "merendé", "bebí",
    "me he comido", "me tomé", "me he tomado",
    "acabo de comer", "acabo de desayunar", "acabo de cenar",
    "para desayuno", "para almuerzo", "para cena", "para merienda",
    "de desayuno", "de almuerzo", "de cena", "de merienda",
    "añade", "apunta", "registra", "anota",
    "ayer comí", "ayer desayuné", "ayer almorcé", "ayer cené",
    # Tercera persona y subjuntivo
    "que apunte", "que registre", "que anote", "que añada",
    "apunte", "registre", "anote", "añada",
    "ha comido", "ha desayunado", "ha cenado",
    "ha almorzado", "ha merendado", "ha bebido",
]


def _detectar_intencion(mensaje: str) -> str:
    """
    Detecta la intención del mensaje usando palabras clave.
    Orden de prioridad: registrar > consultar > borrar_dia > borrar_todo
    Devuelve "desconocido" si no hay coincidencia.
    """
    m = mensaje.lower()
    if any(p in m for p in _REGISTRAR):
        return "registrar"
    if any(p in m for p in _CONSULTAR):
        return "consultar"
    if any(p in m for p in _BORRAR_DIA):
        return "borrar_dia"
    if any(p in m for p in _BORRAR_TODO):
        return "borrar_todo"
    return "desconocido"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detectar_fecha(mensaje: str) -> datetime:
    if any(p in mensaje.lower() for p in ["ayer", "anoche"]):
        return datetime.now() - timedelta(days=1)
    return datetime.now()


def _rango_consulta(mensaje: str) -> int:
    m = mensaje.lower()
    if any(p in m for p in ["mes", "mensual", "30 días", "30 dias"]):
        return 30
    if any(p in m for p in ["semana", "semanal", "7 días", "7 dias"]):
        return 7
    if "ayer" in m:
        return 2
    return 1


def _teclado_confirmacion(fecha_str: str, scope: str) -> InlineKeyboardMarkup:
    fecha_enc = fecha_str.replace("/", "-")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sí, borrar", callback_data=f"nutr_confirm_{scope}_{fecha_enc}"),
        InlineKeyboardButton("❌ Cancelar",   callback_data="nutr_cancel"),
    ]])


def _formatear_registro(datos: dict, fecha_str: str, es_ayer: bool, es_nueva: bool) -> str:
    t      = datos["totales"]
    dia    = "Día anterior" if es_ayer else "Hoy"
    estado = "nueva entrada" if es_nueva else "sumado a lo anterior"
    registros_hoy = storage.leer_registros(dias=1)
    total_hoy = registros_hoy[-1] if registros_hoy else datos["totales"]

    desglose = ""
    for a in datos.get("alimentos", []):
        desglose += (
            f"  <b>{a['nombre']}</b> ({a.get('cantidad_g', '?')}g)\n"
            f"    {a['calorias']:.0f} kcal  |  "
            f"{a['proteinas']:.1f}g prot  |  "
            f"{a['carbohidratos']:.1f}g CH  |  "
            f"{a['grasas']:.1f}g grasa\n"
        )

    return (
        f"{dia} — <b>{fecha_str}</b> <i>({estado})</i>\n\n"
        f"<b>{datos['descripcion_comida']}</b>\n\n"
        f"<b>Desglose por alimento:</b>\n{desglose}\n"
        f"<b>Suma total de la ingesta:</b>\n"
        f"  Calorías:       <b>{t['calorias']:.0f} kcal</b>\n"
        f"  Proteínas:      <b>{t['proteinas']:.1f} g</b>\n"
        f"  Carbohidratos:  <b>{t['carbohidratos']:.1f} g</b>\n"
        f"  Grasas:         <b>{t['grasas']:.1f} g</b>\n"
        f"  Azúcar:         <b>{t['azucar']:.1f} g</b>\n"
        f"  Fibra:          <b>{t['fibra']:.1f} g</b>\n\n"
        f"<i>✅ Guardado en el Excel.</i>"
        f"<b>Calorías totales del día: :</b>{total_hoy['calorias']:.0f} kcal</b>\n"\n
    )


# ── Punto de entrada principal ────────────────────────────────────────────────

async def run(mensaje: str) -> AgentResponse:
    """
    Punto de entrada único que main.py llama cuando el usuario quiere nutrición.

    La intención se detecta con palabras clave (sin IA).
    Claude solo se invoca para calcular macros (registrar) o analizar datos (consultar).
    """
    # Limpiar ruido conversacional antes de cualquier procesamiento
    mensaje_limpio = _limpiar_mensaje(mensaje)

    intencion = _detectar_intencion(mensaje_limpio)
    fecha     = _detectar_fecha(mensaje_limpio)
    es_ayer   = (datetime.now() - fecha).days >= 1

    # ── Registrar ─────────────────────────────────────────────────────────────
    if intencion == "registrar":
        base = storage.cargar_base_nutricional()
        try:
            datos = ia.calcular_macros(mensaje_limpio, base)
        except ValueError as e:
            logger.error("Error calculando macros: %s", e)
            return (
                "No pude analizar los alimentos. Intenta ser más específico.\n"
                "<i>Ejemplo: «he comido 200g de pollo con arroz»</i>",
                None,
            )
        ok, es_nueva = storage.guardar_comida(datos, fecha)
        if not ok:
            return (
                "❌ Error al guardar en el Excel. "
                "Revisa que el volumen <code>/data</code> esté montado en Railway.",
                None,
            )
        return _formatear_registro(datos, fecha.strftime("%d/%m/%Y"), es_ayer, es_nueva), None

    # ── Consultar ─────────────────────────────────────────────────────────────
    if intencion == "consultar":
        dias      = _rango_consulta(mensaje_limpio)
        registros = storage.leer_registros(dias)
        if not registros:
            periodo = {1: "hoy", 2: "estos días", 7: "esta semana", 30: "este mes"}.get(
                dias, f"los últimos {dias} días"
            )
            return f"No tengo datos registrados para {periodo}. ¡Cuéntame qué has comido!", None
        try:
            respuesta = ia.analizar_historial(mensaje_limpio, registros)
        except ValueError as e:
            logger.error("Error analizando historial: %s", e)
            return "No pude analizar tu historial. Inténtalo de nuevo.", None
        return respuesta, None

    # ── Borrar día (pide confirmación) ────────────────────────────────────────
    if intencion == "borrar_dia":
        fecha_str = fecha.strftime("%d/%m/%Y")
        dia_label = "ayer" if es_ayer else "hoy"
        return (
            f"<b>¿Seguro que quieres borrar el registro de {dia_label} ({fecha_str})?</b>\n\n"
            f"Se eliminará solo esa fila del Excel.\n"
            f"<i>Esta acción no se puede deshacer.</i>",
            _teclado_confirmacion(fecha_str, "dia"),
        )

    # ── Borrar todo (pide confirmación) ───────────────────────────────────────
    if intencion == "borrar_todo":
        return (
            "<b>¿Seguro que quieres borrar TODO el registro nutricional?</b>\n\n"
            "Se eliminará el Excel completo y se creará uno nuevo vacío.\n"
            "<i>Esta acción no se puede deshacer.</i>",
            _teclado_confirmacion(datetime.now().strftime("%d/%m/%Y"), "todo"),
        )

    # ── Intención no reconocida ───────────────────────────────────────────────
    return (
        "No entendí qué querías hacer. Puedes:\n\n"
        "- <i>«He comido pollo con arroz»</i> → registrar\n"
        "- <i>«Qué llevo hoy»</i> → consultar macros\n"
        "- <i>«Borra lo de hoy»</i> → borrar el día\n"
        "- <i>«Borra todo el registro»</i> → limpiar todo",
        None,
    )


# ── Callbacks de botones inline ───────────────────────────────────────────────

async def handle_callback(data: str) -> AgentResponse:
    """Gestiona las confirmaciones de borrado."""
    if data == "nutr_cancel":
        return "Cancelado. El registro no se ha modificado. 👍", None

    if data.startswith("nutr_confirm_"):
        partes    = data.split("_", 3)
        scope     = partes[2]
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
                f"No encontré datos para {fecha_str}. Puede que ya estuviera vacío.",
                None,
            )

    return "Acción de callback no reconocida.", None