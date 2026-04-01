"""
ia.py — Capa de inteligencia artificial del agente de nutrición.

Responsabilidad única: comunicarse con Claude.
NO detecta intenciones. NO toca el Excel. NO sabe nada de Telegram.

Tres funciones públicas:
  - calcular_macros()    → analiza alimentos y devuelve valores nutricionales
  - analizar_historial() → analiza el registro y genera un resumen para el usuario
  - generar_menu()       → recibe el CSV de alimentos y genera un menú HTML personalizado

Protecciones incluidas:
  - Reintentos automáticos ante fallos de red (Bug 2)
  - Validación completa de todos los campos de totales (Bug 3)
  - Limpieza de bloques markdown en respuestas de Claude
"""

import json
import logging
import re
import time
from datetime import datetime

from anthropic import Anthropic, APIError, APITimeoutError

logger = logging.getLogger(__name__)
claude = Anthropic()

# Campos obligatorios en el objeto "totales"
_CAMPOS_TOTALES = ("calorias", "proteinas", "carbohidratos", "grasas", "azucar", "fibra")

# Configuración de reintentos
_MAX_REINTENTOS = 3
_ESPERA_BASE_SEG = 1  # espera exponencial: 1s, 2s, 4s


# ── Helpers internos ──────────────────────────────────────────────────────────

def _limpiar_json(texto: str) -> str:
    """Elimina bloques markdown que Claude pueda añadir por error."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.MULTILINE).strip()


def _llamar_claude_con_reintentos(*, model: str, max_tokens: int,
                                   system: str, messages: list) -> str:
    """
    Llama a la API de Claude con reintentos exponenciales ante fallos de red.
    Devuelve el texto de la respuesta o lanza ValueError tras agotar los intentos.
    """
    ultimo_error = None
    for intento in range(_MAX_REINTENTOS):
        try:
            response = claude.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return response.content[0].text.strip()
        except (APITimeoutError, APIError) as e:
            ultimo_error = e
            if intento < _MAX_REINTENTOS - 1:
                espera = _ESPERA_BASE_SEG * (2 ** intento)
                logger.warning(
                    "Fallo llamada Claude (intento %d/%d), reintentando en %ds: %s",
                    intento + 1, _MAX_REINTENTOS, espera, e,
                )
                time.sleep(espera)
            else:
                logger.error("Agotados los reintentos de Claude: %s", e)

    raise ValueError(f"Claude no respondió tras {_MAX_REINTENTOS} intentos: {ultimo_error}")


def _validar_totales(totales: dict) -> None:
    """
    Valida que el objeto totales tenga todos los campos obligatorios
    y que sus valores sean numéricos.
    """
    for campo in _CAMPOS_TOTALES:
        if campo not in totales:
            raise ValueError(f"Campo obligatorio ausente en totales: {campo!r}")
        try:
            float(totales[campo])
        except (TypeError, ValueError):
            raise ValueError(
                f"El campo {campo!r} en totales no es numérico: {totales[campo]!r}"
            )


# ── calcular_macros ───────────────────────────────────────────────────────────

_SYSTEM_MACROS = """Eres un experto en nutrición. Analiza los alimentos descritos y devuelve ÚNICAMENTE un JSON válido, sin texto adicional ni bloques markdown.

Formato obligatorio:
{
  "descripcion_comida": "Descripción breve de lo comido",
  "alimentos": [
    {
      "nombre": "nombre del alimento",
      "cantidad_g": 150,
      "calorias": 250.0,
      "proteinas": 20.0,
      "carbohidratos": 15.0,
      "grasas": 8.0,
      "azucar": 2.0,
      "fibra": 1.5
    }
  ],
  "totales": {
    "calorias": 250.0,
    "proteinas": 20.0,
    "carbohidratos": 15.0,
    "grasas": 8.0,
    "azucar": 2.0,
    "fibra": 1.5
  }
}

Reglas:
- Valores para la cantidad descrita (NO por 100g)
- Sin cantidad especificada → porción estándar razonable
- Usa la base nutricional si el alimento aparece; si no, usa tu conocimiento
- Los totales deben ser la suma exacta de todos los alimentos
- Si digo que he comido una galleta son 10g
- Todos los valores numéricos deben ser números (float), nunca strings
- Redondea a 1 decimal. Calorías en kcal, resto en gramos
- Si hay varios alimentos, inclúyelos todos en la lista"""


def calcular_macros(mensaje: str, base_nutricional: dict) -> dict:
    """
    Llama a Claude para analizar los alimentos del mensaje y calcular macros.

    Args:
        mensaje:          Texto del usuario (ya limpio de ruido conversacional).
        base_nutricional: Valores nutricionales por alimento (por 100g).

    Returns:
        Dict con "descripcion_comida", "alimentos" y "totales" validados.

    Raises:
        ValueError: Si Claude devuelve JSON inválido, incompleto o con campos no numéricos.
    """
    contexto = ""
    if base_nutricional:
        contexto = (
            f"\n\nBASE NUTRICIONAL DISPONIBLE (valores por 100g):\n"
            f"{json.dumps(base_nutricional, ensure_ascii=False, indent=2)}"
        )

    raw = _llamar_claude_con_reintentos(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=_SYSTEM_MACROS,
        messages=[{
            "role": "user",
            "content": f"Analiza esta comida y calcula los macros:{contexto}\n\nMensaje: {mensaje}",
        }],
    )

    try:
        datos = json.loads(_limpiar_json(raw))
    except json.JSONDecodeError as e:
        logger.error("JSON inválido en calcular_macros: %s\nRaw: %s", e, raw)
        raise ValueError(f"Respuesta no parseable de Claude: {e}") from e

    for campo in ("descripcion_comida", "alimentos", "totales"):
        if campo not in datos:
            raise ValueError(f"Campo obligatorio ausente en respuesta de Claude: {campo!r}")

    if not isinstance(datos["alimentos"], list):
        raise ValueError(f"'alimentos' debe ser una lista, recibido: {type(datos['alimentos'])}")

    _validar_totales(datos["totales"])
    return datos


# ── analizar_historial ────────────────────────────────────────────────────────

_SYSTEM_HISTORIAL = """Eres Lisa, una AI Manager especializada en nutrición.
Normalmente las calorias que debo consumir son de una persona de 56kg y 165cm que quiere perder grasa y ganar músculo. 
Máximo de 1500 kcal de objetivo y priorizando proteina
Recibes el historial nutricional del usuario y debes analizarlo de forma clara, concisa y útil.

Formato de respuesta:
- Usa <b>negrita</b> e <i>cursiva</i> <u> subrayado </b> HTML. Nunca asteriscos ni guiones bajos ni ningun simbolo extraño. Quiero que los mensajes de respuesta
Sean visualmente bonitos y esten ordenados. usa subrayado negrita, subrayado y cursiva. Ten en cuenta que todas las respuestas llegaran a telegram para el formato
- Guiones simples para listas.
- Respuestas concisas y accionables.

Si hay datos de un solo día: haz el resumen de ese día.
Si hay varios días: incluye medias, el día con más y menos calorías, y tendencias.
Termina siempre con una observación práctica y útil."""


def analizar_historial(mensaje: str, registros: list[dict]) -> str:
    """
    Llama a Claude para analizar el historial nutricional y responder la consulta.

    Args:
        mensaje:   Consulta del usuario (ya limpia de ruido conversacional).
        registros: Lista de registros del Excel (output de storage.leer_registros).

    Returns:
        Texto HTML con el análisis, listo para enviar por Telegram.

    Raises:
        ValueError: Si Claude devuelve una respuesta vacía o falla la llamada.
    """
    hoy    = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        f"Fecha de hoy: {hoy}\n"
        f"Consulta del usuario: \"{mensaje}\"\n\n"
        f"Historial nutricional:\n"
        f"{json.dumps(registros, ensure_ascii=False, indent=2)}\n\n"
        f"Analiza los datos y responde la consulta."
    )

    respuesta = _llamar_claude_con_reintentos(
        model="claude-haiku-4-5",
        max_tokens=800,
        system=_SYSTEM_HISTORIAL,
        messages=[{"role": "user", "content": prompt}],
    )

    if not respuesta:
        raise ValueError("Claude devolvió una respuesta vacía")

    return respuesta


# ── generar_menu ──────────────────────────────────────────────────────────────

_SYSTEM_MENU = """Eres un creador de recetas healthy, nutricionista experto y chef creativo que siempre esta al tanto de las ultimas tendencias en recetas sanas. Genera un menú personalizado en HTML.

DATOS QUE RECIBES:
- Un CSV con el historial de alimentos del usuario (solo fecha y nombre del alimento)
- La petición del usuario con los macros objetivo y número de días
- El modo: "habitual" o "innovador"

TU PROCESO (hazlo internamente, no lo muestres):
1. Lee el CSV y normaliza los nombres: "pechuga pollo plancha" y "pollo a la plancha" → "pollo"
2. Agrupa por nombre normalizado y cuenta frecuencias
3. Identifica los alimentos más habituales del usuario
4. Genera el menú usando esos datos
5. Usa tu conocimiento nutricional para calcular los macros de cada alimento y comida

REGLAS DEL MENÚ:
- Organiza cada día en: Desayuno, Almuerzo, Merienda, Cena
- Decide qué va en cada comida según el tipo de alimento (no te lo dirán)
- Incluye cantidades en gramos para cada alimento
- Prioriza verduras, frutas y proteina.
- Calcula tú los macros de cada comida (kcal, proteínas, CH, grasas) usando tu conocimiento
- El total diario debe aproximarse a los macros objetivo del usuario (±10%)
- Modo habitual: usa principalmente los alimentos frecuentes del usuario
- Modo innovador: ~50% alimentos frecuentes del usuario, ~50% recetas creativas nuevas

FORMATO DE SALIDA:
Devuelve ÚNICAMENTE el HTML completo de la página, sin texto adicional ni bloques markdown.
El HTML debe ser una página web bonita, moderna y legible:
- Diseño limpio con paleta verde/azul saludable
- Cards por día con secciones visuales para cada comida
- Tabla de macros al final de cada día
- Resumen total de macros al final del menú
- Tipografía clara, jerarquía visual bien definida
- Responsive (que se vea bien en móvil)
- Todo el CSS inline o en un bloque <style> en el <head>"""


def generar_menu(
    mensaje: str,
    csv_alimentos: str,
    modo: str,
    dias: int,
) -> str:
    """
    Genera un menú personalizado en HTML a partir del CSV de alimentos.

    Claude recibe el CSV bruto (fecha, alimento) y hace él mismo la normalización,
    agrupación por frecuencia y cálculo de macros con su conocimiento nutricional.

    Args:
        mensaje:       Petición del usuario con macros objetivo y número de días.
        csv_alimentos: Contenido del CSV (output de storage.leer_csv_alimentos).
        modo:          "habitual" | "innovador"
        dias:          Número de días del menú.

    Returns: String con el HTML completo de la página.
    Raises:  ValueError si Claude falla o devuelve respuesta vacía.
    """
    hoy = datetime.now().strftime("%d/%m/%Y")

    prompt = (
        f"Fecha de hoy: {hoy}\n"
        f"Petición: \"{mensaje}\"\n"
        f"Días solicitados: {dias}\n"
        f"Modo: {modo}\n\n"
        f"CSV con historial de alimentos del usuario:\n"
        f"```csv\n{csv_alimentos}\n```\n\n"
        f"Genera el menú en HTML."
    )

    html = _llamar_claude_con_reintentos(
        model="claude-sonnet-4-5",  # Sonnet: mejor calidad para HTML complejo
        max_tokens=4096,
        system=_SYSTEM_MENU,
        messages=[{"role": "user", "content": prompt}],
    )

    if not html or len(html) < 200:
        raise ValueError("Claude devolvió un HTML vacío o demasiado corto")

    # Limpiar bloques markdown por si Claude los añade
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip(), flags=re.MULTILINE).strip()

    return html