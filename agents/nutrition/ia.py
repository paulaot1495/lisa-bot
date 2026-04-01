"""
ia.py — Llamadas a Claude para el agente de nutrición.
"""

import re
import json
import logging
from datetime import datetime

from anthropic import Anthropic

logger = logging.getLogger(__name__)
claude = Anthropic()

_SYSTEM = """Eres un experto en nutricion. Recibes un mensaje del usuario y el historial de su registro.

Devuelve SOLO un JSON valido, sin texto adicional ni markdown, con este formato:

{
  "intencion": "registrar" | "consultar" | "borrar_dia" | "borrar_todo",

  // Si intencion == "registrar":
  "alimentos": [
    {"nombre": "...", "cantidad_g": 150, "calorias": 200, "proteinas": 15, "carbohidratos": 20, "grasas": 5, "azucar": 3, "fibra": 2}
  ],
  "totales": {"calorias": 200, "proteinas": 15, "carbohidratos": 20, "grasas": 5, "azucar": 3, "fibra": 2},
  "descripcion_comida": "Breve descripcion",

  // Si intencion == "consultar":
  "respuesta": "Texto HTML con el analisis para el usuario"
}

Reglas para registrar:
- Valores por la cantidad descrita (no por 100g)
- Sin cantidad → porcion estandar razonable
- Usa la base nutricional si el alimento aparece; si no, usa tu conocimiento
- Redondea a 1 decimal. Calorias en kcal, resto en gramos

Reglas para consultar:
- Analiza el historial y responde con <b>negrita</b> e <i>cursiva</i> HTML, sin asteriscos
- Se concisa y accionable"""


def interpretar(mensaje: str, base_nutricional: dict, historial: list[dict]) -> tuple[str, dict]:
    """
    Llama a Claude con el mensaje, la base nutricional y el historial.
    Devuelve (intencion, datos).
    """
    contexto = ""
    if base_nutricional:
        contexto += f"\nBASE NUTRICIONAL (por 100g):\n{json.dumps(base_nutricional, ensure_ascii=False)}"
    if historial:
        hoy = datetime.now().strftime("%d/%m/%Y")
        contexto += f"\n\nFecha de hoy: {hoy}\nHISTORIAL (últimos 30 días):\n{json.dumps(historial, ensure_ascii=False)}"

    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"Mensaje: {mensaje}{contexto}"}]
    )
    raw = re.sub(r"```json\s*|\s*```", "", resp.content[0].text).strip()
    datos = json.loads(raw)
    return datos.pop("intencion"), datos