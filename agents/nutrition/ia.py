"""
ia.py — Capa de inteligencia artificial del agente de nutrición.

Responsabilidad única: comunicarse con Claude.
No sabe nada del Excel ni de Telegram.

Claude recibe el mensaje + contexto y devuelve un JSON estructurado
con la intención detectada y los datos necesarios para ejecutarla.
"""

import json
import logging
import re
from datetime import datetime

from anthropic import Anthropic

logger = logging.getLogger(__name__)
claude = Anthropic()

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """Eres un experto en nutrición integrado en un asistente personal.

Recibes un mensaje del usuario junto con su historial nutricional y una base de datos de alimentos.
Tu trabajo es interpretar la intención y devolver ÚNICAMENTE un JSON válido, sin texto adicional ni bloques markdown.

═══════════════════════════════════════
INTENCIONES POSIBLES Y SU JSON
═══════════════════════════════════════

1. REGISTRAR una comida:
{
  "intencion": "registrar",
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

2. CONSULTAR el historial:
{
  "intencion": "consultar",
  "respuesta": "Texto HTML con el análisis. Usa <b>negrita</b> e <i>cursiva</i>. Sin asteriscos."
}

3. BORRAR el registro de un día:
{
  "intencion": "borrar_dia"
}

4. BORRAR todo el registro:
{
  "intencion": "borrar_todo"
}

═══════════════════════════════════════
REGLAS PARA REGISTRAR
═══════════════════════════════════════
- Todos los valores nutricionales son para la cantidad descrita (NO por 100g)
- Si no se especifica cantidad, usa una porción estándar razonable
- Si el alimento aparece en la BASE NUTRICIONAL, úsala; si no, usa tu conocimiento, investiga en internet y coge datos de fuentes FIABLES.
- Los totales deben ser la suma exacta de todos los alimentos
- Si digo que he comido una galleta son 10g
- Redondea a 1 decimal. Calorías en kcal, el resto en gramos

═══════════════════════════════════════
REGLAS PARA CONSULTAR
═══════════════════════════════════════
- Analiza el historial proporcionado y responde de forma concisa y accionable
- Incluye medias, el día con más/menos calorías y tendencias si hay varios días
- Si no hay historial, indícalo claramente
- Formato HTML: <b>negrita</b>, <i>cursiva</i>, guiones para listas. Sin asteriscos."""


# ── Función pública ───────────────────────────────────────────────────────────

def interpretar(
    mensaje: str,
    base_nutricional: dict,
    historial: list[dict],
) -> tuple[str, dict]:
    """
    Envía el mensaje a Claude con el contexto completo.

    Args:
        mensaje:          Texto original del usuario.
        base_nutricional: Dict con valores nutricionales por alimento (por 100g).
        historial:        Lista de registros de los últimos N días.

    Returns:
        (intencion, datos) donde intencion es una de:
        "registrar" | "consultar" | "borrar_dia" | "borrar_todo"
        y datos contiene el resto del JSON devuelto por Claude.

    Raises:
        ValueError: Si Claude devuelve un JSON no parseable.
    """
    # Construir contexto adicional
    contexto_partes = []

    if base_nutricional:
        contexto_partes.append(
            f"BASE NUTRICIONAL (valores por 100g):\n"
            f"{json.dumps(base_nutricional, ensure_ascii=False, indent=2)}"
        )

    if historial:
        hoy = datetime.now().strftime("%d/%m/%Y")
        contexto_partes.append(
            f"Fecha de hoy: {hoy}\n"
            f"HISTORIAL NUTRICIONAL (últimos días):\n"
            f"{json.dumps(historial, ensure_ascii=False, indent=2)}"
        )

    contexto = "\n\n".join(contexto_partes)
    prompt   = f"Mensaje del usuario: {mensaje}"
    if contexto:
        prompt += f"\n\n{contexto}"

    # Llamada a Claude
    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Limpiar posibles bloques markdown que Claude añada por error
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        datos = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Claude devolvió JSON inválido: %s\nRaw: %s", e, raw)
        raise ValueError(f"Respuesta no parseable de Claude: {e}") from e

    intencion = datos.pop("intencion", None)
    if intencion not in ("registrar", "consultar", "borrar_dia", "borrar_todo"):
        raise ValueError(f"Intención desconocida: {intencion!r}")

    return intencion, datos