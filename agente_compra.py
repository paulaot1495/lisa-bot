import os
import json
import logging
from anthropic import Anthropic
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────
# Railway Volume monta el disco en /data
# En local usará la carpeta del proyecto
EXCEL_PATH = os.getenv("EXCEL_PATH", "/data/lista_compra.xlsx")

claude = Anthropic()

# ─────────────────────────────────────────
# ESTILO PASTEL (tu paleta personal)
# ─────────────────────────────────────────
C_HEADER_BG  = "6B8CAE"
C_HEADER_FG  = "FFFFFF"
C_SECTION_BG = "A8C4D4"
C_SECTION_FG = "2C3E50"
C_ROW1_BG    = "EAF4FB"
C_ROW2_BG    = "F5FBFE"
C_TOTAL_BG   = "7DADA0"
C_TOTAL_FG   = "FFFFFF"
BORDER_COLOR = "BBCDD8"

thin   = Side(style='thin', color=BORDER_COLOR)
border = Border(left=thin, right=thin, top=thin, bottom=thin)

def apply(cell, bold=False, fg="000000", bg=None, align="center", size=10, italic=False):
    cell.font      = Font(name="Arial", bold=bold, size=size, color=fg, italic=italic)
    if bg:
        cell.fill  = PatternFill("solid", start_color=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center",
                                indent=1 if align == "left" else 0)
    cell.border    = border

# ─────────────────────────────────────────
# GESTIÓN DEL EXCEL
# ─────────────────────────────────────────
COLUMNAS = ["Producto", "Tienda", "Cantidad", "Prioridad"]

def leer_items() -> list[dict]:
    """Lee todos los items del Excel. Devuelve lista de dicts."""
    if not os.path.exists(EXCEL_PATH):
        return []
    wb = load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    items = []
    for row in ws.iter_rows(min_row=4, values_only=True):  # fila 1-3 son cabecera
        if row[0]:  # si hay producto
            items.append({
                "producto":  str(row[0]).strip(),
                "tienda":    str(row[1]).strip() if row[1] else "",
                "cantidad":  str(row[2]).strip() if row[2] else "1",
                "prioridad": str(row[3]).strip() if row[3] else "normal",
            })
    return items


def guardar_excel(items: list[dict]):
    """Recrea el Excel completo con el estilo pastel."""
    # Crear carpeta si no existe (necesario en Railway)
    os.makedirs(os.path.dirname(EXCEL_PATH), exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Lista Compra"

    # Anchos de columna
    ws.column_dimensions['A'].width = 28  # Producto
    ws.column_dimensions['B'].width = 20  # Tienda
    ws.column_dimensions['C'].width = 12  # Cantidad
    ws.column_dimensions['D'].width = 14  # Prioridad

    # FILA 1 — Título fusionado
    ws.merge_cells("A1:D1")
    ws["A1"] = "🛒 Lista de la Compra"
    apply(ws["A1"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=13)
    ws.row_dimensions[1].height = 28

    # FILA 2 — vacía
    ws.row_dimensions[2].height = 6

    # FILA 3 — Cabeceras
    for col, nombre in enumerate(COLUMNAS, start=1):
        cell = ws.cell(row=3, column=col, value=nombre.upper())
        apply(cell, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=11)
    ws.row_dimensions[3].height = 20

    # FILAS DE DATOS — agrupadas por tienda
    tiendas = {}
    for item in items:
        tiendas.setdefault(item["tienda"], []).append(item)

    row_num = 4
    for tienda, productos in sorted(tiendas.items()):
        # Fila de sección (nombre de la tienda)
        ws.merge_cells(f"A{row_num}:D{row_num}")
        ws[f"A{row_num}"] = f"📍 {tienda.upper()}"
        apply(ws[f"A{row_num}"], bold=True, fg=C_SECTION_FG, bg=C_SECTION_BG, align="left", size=10)
        ws.row_dimensions[row_num].height = 18
        row_num += 1

        # Productos de esa tienda
        for i, item in enumerate(productos):
            bg = C_ROW1_BG if i % 2 == 0 else C_ROW2_BG
            valores = [item["producto"], item["tienda"], item["cantidad"], item["prioridad"]]
            for col, val in enumerate(valores, start=1):
                cell = ws.cell(row=row_num, column=col, value=val)
                aln = "left" if col == 1 else "center"
                apply(cell, fg="000000", bg=bg, align=aln)
            ws.row_dimensions[row_num].height = 16
            row_num += 1

    # FILA TOTAL
    ws.merge_cells(f"A{row_num}:C{row_num}")
    ws[f"A{row_num}"] = f"TOTAL: {len(items)} productos"
    apply(ws[f"A{row_num}"], bold=True, fg=C_TOTAL_FG, bg=C_TOTAL_BG, size=11)
    ws[f"D{row_num}"] = ""
    apply(ws[f"D{row_num}"], bg=C_TOTAL_BG)
    ws.row_dimensions[row_num].height = 20

    wb.save(EXCEL_PATH)


# ─────────────────────────────────────────
# CLAUDE PARSEA EL TEXTO DEL USUARIO
# ─────────────────────────────────────────
def parsear_mensaje(mensaje: str) -> dict:
    """
    Usa Claude para entender qué quiere el usuario y extraer datos.
    Devuelve un dict con: accion, items (lista), tienda, producto
    """
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        system="""Eres un parser de listas de la compra. 
Analiza el mensaje y devuelve SOLO un JSON válido, sin explicaciones ni backticks.

Acciones posibles:
- "añadir": el usuario quiere añadir productos
- "eliminar": el usuario ha comprado algo o quiere borrarlo
- "ver_tienda": quiere ver qué comprar en una tienda concreta
- "ver_todo": quiere ver toda la lista
- "limpiar_tienda": ha hecho la compra entera de una tienda

Para "añadir", extrae lista de items con: producto, tienda, cantidad, prioridad (urgente/normal).
Si no especifica cantidad, usa "1". Si no especifica prioridad, usa "normal".
Si no especifica tienda, usa "sin tienda".

Formato de respuesta:
{
  "accion": "añadir",
  "items": [
    {"producto": "leche", "tienda": "mercadona", "cantidad": "2", "prioridad": "normal"}
  ]
}

Para eliminar/ver_tienda/limpiar_tienda incluye también:
{
  "accion": "eliminar",
  "productos": ["leche", "pan"],
  "tienda": "mercadona"
}""",
        messages=[{"role": "user", "content": mensaje}]
    )

    texto = resp.content[0].text.strip()
    # Limpiar posibles backticks si Claude los pone
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)


# ─────────────────────────────────────────
# LÓGICA PRINCIPAL DEL AGENTE
# ─────────────────────────────────────────
async def agente_compra(mensaje: str) -> str:
    """
    Punto de entrada principal. Recibe el mensaje del usuario
    y devuelve una respuesta en texto para Telegram.
    """
    try:
        parsed = parsear_mensaje(mensaje)
        accion = parsed.get("accion", "ver_todo")
        items_actuales = leer_items()

        # ── AÑADIR ──────────────────────────────
        if accion == "añadir":
            nuevos = parsed.get("items", [])
            if not nuevos:
                return "No entendí qué quieres añadir. Dime por ejemplo: *'leche x2 en mercadona'*"

            # Evitar duplicados exactos
            existentes = {(i["producto"].lower(), i["tienda"].lower()) for i in items_actuales}
            añadidos = []
            for item in nuevos:
                key = (item["producto"].lower(), item["tienda"].lower())
                if key not in existentes:
                    items_actuales.append(item)
                    añadidos.append(item)
                    existentes.add(key)

            guardar_excel(items_actuales)

            if not añadidos:
                return "Esos productos ya estaban en la lista 👀"

            lineas = [f"  ✅ {i['cantidad']}x *{i['producto']}* — {i['tienda']} ({i['prioridad']})" for i in añadidos]
            return f"Añadido a la lista:\n" + "\n".join(lineas)

        # ── ELIMINAR ────────────────────────────
        elif accion == "eliminar":
            productos_borrar = [p.lower() for p in parsed.get("productos", [])]
            antes = len(items_actuales)
            items_actuales = [
                i for i in items_actuales
                if i["producto"].lower() not in productos_borrar
            ]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)

            if borrados == 0:
                return "No encontré esos productos en la lista."
            return f"🗑️ Eliminados {borrados} productos. Lista actualizada."

        # ── LIMPIAR TIENDA ───────────────────────
        elif accion == "limpiar_tienda":
            tienda = parsed.get("tienda", "").lower()
            antes = len(items_actuales)
            items_actuales = [i for i in items_actuales if i["tienda"].lower() != tienda]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)
            return f"✅ Compra de *{tienda}* completada. {borrados} productos eliminados."

        # ── VER POR TIENDA ───────────────────────
        elif accion == "ver_tienda":
            tienda = parsed.get("tienda", "").lower()
            filtrados = [i for i in items_actuales if tienda in i["tienda"].lower()]
            if not filtrados:
                return f"No tienes nada pendiente en *{tienda}*."

            urgentes = [i for i in filtrados if i["prioridad"] == "urgente"]
            normales = [i for i in filtrados if i["prioridad"] != "urgente"]

            lineas = [f"🛒 *{tienda.upper()}* — {len(filtrados)} productos:\n"]
            if urgentes:
                lineas.append("🔴 *Urgente:*")
                lineas += [f"  • {i['cantidad']}x {i['producto']}" for i in urgentes]
            if normales:
                lineas.append("⚪ *Normal:*")
                lineas += [f"  • {i['cantidad']}x {i['producto']}" for i in normales]
            return "\n".join(lineas)

        # ── VER TODO ─────────────────────────────
        else:
            if not items_actuales:
                return "La lista está vacía. 🎉 Dime qué necesitas comprar."

            tiendas = {}
            for item in items_actuales:
                tiendas.setdefault(item["tienda"], []).append(item)

            lineas = [f"📋 *Lista completa — {len(items_actuales)} productos:*\n"]
            for tienda, productos in sorted(tiendas.items()):
                lineas.append(f"\n📍 *{tienda.upper()}*")
                for p in productos:
                    emoji = "🔴" if p["prioridad"] == "urgente" else "⚪"
                    lineas.append(f"  {emoji} {p['cantidad']}x {p['producto']}")

            return "\n".join(lineas)

    except json.JSONDecodeError:
        return "No entendí bien el mensaje. Prueba con: *'añade leche y pan de mercadona'*"
    except Exception as e:
        logger.error(f"Error en agente_compra: {e}")
        return "⚠️ Hubo un error procesando tu lista. Inténtalo de nuevo."