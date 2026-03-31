"""
agente_nutricion.py — Agente de seguimiento nutricional para Lisa.
Detecta mensajes sobre comida, analiza macros/calorías y actualiza comidas.xlsx en Railway.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from anthropic import Anthropic

logger = logging.getLogger(__name__)

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Ruta del Excel en Railway (volumen persistente montado en /data)
EXCEL_PATH = Path(os.getenv("NUTRITION_EXCEL_PATH", "/data/comidas.xlsx"))

# ──────────────────────────────────────────────
# PALABRAS CLAVE para detección de mensajes de comida
# ──────────────────────────────────────────────
PALABRAS_COMIDA = [
    "comí", "comi", "desayuné", "desayune", "almorcé", "almorce",
    "merendé", "merende", "cené", "cene", "tomé", "tome", "bebí", "bebi",
    "desayuno", "almuerzo", "comida", "merienda", "cena", "snack",
    "he comido", "he desayunado", "he cenado", "he almorzado",
    "me he comido", "me tomé", "ayer comí", "ayer cené", "ayer desayuné",
]

def es_mensaje_nutricion(mensaje: str) -> bool:
    m = mensaje.lower()
    return any(p in m for p in PALABRAS_COMIDA)

def detectar_fecha(mensaje: str) -> datetime:
    """Devuelve la fecha a la que se refiere el mensaje (hoy o ayer)."""
    m = mensaje.lower()
    if any(p in m for p in ["ayer", "anoche", "ayer por"]):
        return datetime.now() - timedelta(days=1)
    return datetime.now()

# ──────────────────────────────────────────────
# BASE NUTRICIONAL LOCAL (base_nutricional.xlsx)
# ──────────────────────────────────────────────
def cargar_base_nutricional() -> dict:
    """Lee base_nutricional.xlsx si existe y devuelve dict {nombre: {calorias, proteinas...}}"""
    ruta = Path(os.getenv("BASE_NUTRICIONAL_PATH", "/data/base_nutricional.xlsx"))
    if not ruta.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_excel(ruta)
        df.columns = [c.strip().lower() for c in df.columns]
        base = {}
        for _, row in df.iterrows():
            nombre = str(row.get("alimento", row.get("nombre", ""))).strip().lower()
            if nombre:
                base[nombre] = {
                    "calorias":  float(row.get("calorias", row.get("kcal", 0)) or 0),
                    "proteinas": float(row.get("proteinas", row.get("proteína", 0)) or 0),
                    "carbohidratos": float(row.get("carbohidratos", row.get("hidratos", 0)) or 0),
                    "grasas":    float(row.get("grasas", row.get("grasa", 0)) or 0),
                    "azucar":    float(row.get("azucar", row.get("azúcar", 0)) or 0),
                    "fibra":     float(row.get("fibra", 0) or 0),
                }
        return base
    except Exception as e:
        logger.warning(f"No se pudo cargar base_nutricional: {e}")
        return {}

# ──────────────────────────────────────────────
# ANÁLISIS NUTRICIONAL VÍA CLAUDE + WEB SEARCH
# ──────────────────────────────────────────────
SYSTEM_NUTRICION = """Eres un experto en nutrición. Analiza la comida descrita y devuelve SOLO un JSON válido, sin texto adicional, sin markdown.

Formato obligatorio:
{
  "alimentos": [
    {
      "nombre": "nombre del alimento",
      "cantidad_g": 150,
      "calorias": 200,
      "proteinas": 15,
      "carbohidratos": 20,
      "grasas": 5,
      "azucar": 3,
      "fibra": 2
    }
  ],
  "totales": {
    "calorias": 200,
    "proteinas": 15,
    "carbohidratos": 20,
    "grasas": 5,
    "azucar": 3,
    "fibra": 2
  },
  "descripcion_comida": "Breve descripción de lo que se ha comido"
}

Reglas:
- Todos los valores son por la cantidad descrita (no por 100g)
- Si no se especifica cantidad, usa una porción estándar razonable
- Usa la base nutricional proporcionada cuando el alimento aparezca; si no, usa tus conocimientos
- Redondea a 1 decimal
- calorias en kcal, todo lo demás en gramos"""

async def analizar_nutricion(mensaje: str, base_nutricional: dict) -> dict:
    """Llama a Claude para analizar la comida y extraer macros."""
    base_str = ""
    if base_nutricional:
        base_str = f"\n\nBASE NUTRICIONAL DISPONIBLE (por 100g):\n{json.dumps(base_nutricional, ensure_ascii=False, indent=2)}"

    prompt = f"Analiza esta comida y extrae los valores nutricionales:{base_str}\n\nMensaje del usuario: {mensaje}"

    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=SYSTEM_NUTRICION,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    # Limpiar posibles backticks
    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
    return json.loads(raw)

# ──────────────────────────────────────────────
# EXCEL: LEER Y ESCRIBIR
# ──────────────────────────────────────────────
COLUMNAS = [
    "Fecha", "Descripción",
    "Calorías (kcal)", "Proteínas (g)", "Carbohidratos (g)",
    "Grasas (g)", "Azúcar (g)", "Fibra (g)"
]

COL_IDX = {c: i+1 for i, c in enumerate(COLUMNAS)}  # 1-indexed para openpyxl

C_HEADER_BG  = "6B8CAE"
C_HEADER_FG  = "FFFFFF"
C_ROW1_BG    = "EAF4FB"
C_ROW2_BG    = "F5FBFE"
C_TOTAL_BG   = "7DADA0"
C_TOTAL_FG   = "FFFFFF"
BORDER_COLOR = "BBCDD8"

def _get_styles():
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    thin = Side(style='thin', color=BORDER_COLOR)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def apply(cell, bold=False, fg="000000", bg=None, align="center", size=10, italic=False):
        cell.font = Font(name="Arial", bold=bold, size=size, color=fg, italic=italic)
        if bg:
            cell.fill = PatternFill("solid", start_color=bg)
        cell.alignment = Alignment(
            horizontal=align, vertical="center",
            indent=1 if align == "left" else 0
        )
        cell.border = border
    return apply

def crear_excel_nuevo():
    """Crea comidas.xlsx con cabeceras y estilo pastel."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Comidas"
    apply = _get_styles()

    # Fila 1: título fusionado
    ws.merge_cells(f"A1:{chr(64+len(COLUMNAS))}1")
    c = ws["A1"]
    c.value = "📊 Registro Nutricional"
    apply(c, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=13)
    ws.row_dimensions[1].height = 28

    # Fila 2: vacía
    ws.row_dimensions[2].height = 6

    # Fila 3: cabeceras
    for i, col in enumerate(COLUMNAS, 1):
        cell = ws.cell(row=3, column=i, value=col)
        apply(cell, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=11)

    # Anchos de columna
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 35
    for col_letter in "CDEFGH":
        ws.column_dimensions[col_letter].width = 18

    EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(EXCEL_PATH)
    return wb

def cargar_o_crear_excel():
    from openpyxl import load_workbook, Workbook
    if not EXCEL_PATH.exists():
        return crear_excel_nuevo(), True  # (wb, es_nuevo)
    wb = load_workbook(EXCEL_PATH)
    return wb, False

def fila_para_fecha(ws, fecha_str: str):
    """Devuelve el número de fila existente para esa fecha, o None."""
    for row in ws.iter_rows(min_row=4, max_col=1):
        cell = row[0]
        val = cell.value
        if val and str(val).strip() == fecha_str:
            return cell.row
    return None

def siguiente_fila_disponible(ws) -> int:
    """Última fila con datos + 1 (mínimo 4)."""
    max_row = 3
    for row in ws.iter_rows(min_row=4, max_col=1):
        if row[0].value is not None:
            max_row = row[0].row
    return max(4, max_row + 1)

def escribir_fila(ws, row_num: int, fecha_str: str, datos: dict, es_nueva_fila: bool):
    """Escribe o actualiza una fila con los datos nutricionales."""
    apply = _get_styles()
    bg = C_ROW1_BG if row_num % 2 == 0 else C_ROW2_BG

    NUM_FMT = "#,##0.0"

    def set_cell(col_name, value, fmt=None, align="center"):
        col = COL_IDX[col_name]
        cell = ws.cell(row=row_num, column=col, value=value)
        apply(cell, fg="000000", bg=bg, align=align)
        if fmt:
            cell.number_format = fmt
        return cell

    if es_nueva_fila:
        set_cell("Fecha", fecha_str, align="center")
        set_cell("Descripción", datos["descripcion_comida"], align="left")
        set_cell("Calorías (kcal)",     datos["totales"]["calorias"],       NUM_FMT)
        set_cell("Proteínas (g)",       datos["totales"]["proteinas"],      NUM_FMT)
        set_cell("Carbohidratos (g)",   datos["totales"]["carbohidratos"],  NUM_FMT)
        set_cell("Grasas (g)",          datos["totales"]["grasas"],         NUM_FMT)
        set_cell("Azúcar (g)",          datos["totales"]["azucar"],         NUM_FMT)
        set_cell("Fibra (g)",           datos["totales"]["fibra"],          NUM_FMT)
    else:
        # Sumar a los valores existentes
        campos_numericos = [
            ("Calorías (kcal)",    "calorias"),
            ("Proteínas (g)",      "proteinas"),
            ("Carbohidratos (g)",  "carbohidratos"),
            ("Grasas (g)",         "grasas"),
            ("Azúcar (g)",         "azucar"),
            ("Fibra (g)",          "fibra"),
        ]
        for col_name, key in campos_numericos:
            col = COL_IDX[col_name]
            cell = ws.cell(row=row_num, column=col)
            actual = float(cell.value or 0)
            nuevo = actual + datos["totales"][key]
            cell.value = round(nuevo, 1)
            apply(cell, fg="000000", bg=bg)
            cell.number_format = NUM_FMT

        # Actualizar descripción
        col_desc = COL_IDX["Descripción"]
        cell_desc = ws.cell(row=row_num, column=col_desc)
        desc_actual = str(cell_desc.value or "")
        cell_desc.value = desc_actual + " + " + datos["descripcion_comida"]
        apply(cell_desc, fg="000000", bg=bg, align="left")

    ws.row_dimensions[row_num].height = 20

def actualizar_excel(datos: dict, fecha: datetime) -> tuple[bool, bool]:
    """
    Actualiza el Excel con los datos nutricionales.
    Devuelve (ok, es_nueva_fila).
    """
    try:
        wb, _ = cargar_o_crear_excel()
        ws = wb["Comidas"]
        fecha_str = fecha.strftime("%d/%m/%Y")

        fila_existente = fila_para_fecha(ws, fecha_str)
        es_nueva = fila_existente is None

        if es_nueva:
            row_num = siguiente_fila_disponible(ws)
        else:
            row_num = fila_existente

        escribir_fila(ws, row_num, fecha_str, datos, es_nueva)
        wb.save(EXCEL_PATH)
        return True, es_nueva
    except Exception as e:
        logger.error(f"Error actualizando Excel: {e}")
        return False, False

# ──────────────────────────────────────────────
# PUNTO DE ENTRADA PRINCIPAL
# ──────────────────────────────────────────────
async def agente_nutricion(mensaje: str) -> str:
    """
    Analiza el mensaje de comida, actualiza el Excel y devuelve respuesta HTML para Telegram.
    """
    fecha = detectar_fecha(mensaje)
    fecha_str = fecha.strftime("%d/%m/%Y")
    es_ayer = (datetime.now() - fecha).days >= 1

    # 1. Cargar base nutricional
    base = cargar_base_nutricional()

    # 2. Analizar con Claude
    try:
        datos = await analizar_nutricion(mensaje, base)
    except Exception as e:
        logger.error(f"Error en análisis nutricional: {e}")
        return "❌ No pude analizar la información nutricional. Inténtalo de nuevo."

    # 3. Actualizar Excel
    ok, es_nueva_fila = actualizar_excel(datos, fecha)

    if not ok:
        return "❌ Error al guardar en el Excel. Revisa que /data esté montado correctamente."

    # 4. Construir respuesta
    t = datos["totales"]
    accion = "📅 Añadido al día anterior" if es_ayer else "✅ Registrado"
    estado = "nueva entrada" if es_nueva_fila else "actualizado (sumado a lo anterior)"

    lineas_alimentos = ""
    for a in datos.get("alimentos", []):
        lineas_alimentos += f"  - {a['nombre']} ({a.get('cantidad_g', '?')}g) → {a['calorias']} kcal\n"

    respuesta = (
        f"{accion} — <b>{fecha_str}</b> ({estado})\n\n"
        f"<b>🍽 {datos['descripcion_comida']}</b>\n\n"
        f"<b>📊 Totales del registro:</b>\n"
        f"- 🔥 Calorías: <b>{t['calorias']:.0f} kcal</b>\n"
        f"- 💪 Proteínas: <b>{t['proteinas']:.1f} g</b>\n"
        f"- 🌾 Carbohidratos: <b>{t['carbohidratos']:.1f} g</b>\n"
        f"- 🧈 Grasas: <b>{t['grasas']:.1f} g</b>\n"
        f"- 🍬 Azúcar: <b>{t['azucar']:.1f} g</b>\n"
        f"- 🌿 Fibra: <b>{t['fibra']:.1f} g</b>\n\n"
        f"<i>💾 Excel actualizado correctamente.</i>"
    )
    return respuesta