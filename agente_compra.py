import os
import json
import logging
from dotenv import load_dotenv
from anthropic import Anthropic
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

logger = logging.getLogger(__name__)

EXCEL_PATH = os.getenv("EXCEL_PATH", "/data/lista_compra.xlsx")
claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─────────────────────────────────────────
# ESTILO PASTEL
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
# EXCEL: LEER Y GUARDAR
# ─────────────────────────────────────────
def leer_items() -> list[dict]:
    if not os.path.exists(EXCEL_PATH):
        return []
    wb = load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    items = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        if row[0]:
            items.append({
                "producto":  str(row[0]).strip(),
                "tienda":    str(row[1]).strip() if row[1] else "sin tienda",
                "cantidad":  str(row[2]).strip() if row[2] else "1",
                "prioridad": str(row[3]).strip() if row[3] else "normal",
            })
    return items


def guardar_excel(items: list[dict]):
    os.makedirs(os.path.dirname(os.path.abspath(EXCEL_PATH)), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista Compra"

    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 14

    ws.merge_cells("A1:D1")
    ws["A1"] = "Lista de la Compra"
    apply(ws["A1"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=13)
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 6

    for col, nombre in enumerate(["Producto", "Tienda", "Cantidad", "Prioridad"], start=1):
        cell = ws.cell(row=3, column=col, value=nombre.upper())
        apply(cell, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=11)
    ws.row_dimensions[3].height = 20

    tiendas = {}
    for item in items:
        tiendas.setdefault(item["tienda"], []).append(item)

    row_num = 4
    for tienda, productos in sorted(tiendas.items()):
        ws.merge_cells(f"A{row_num}:D{row_num}")
        ws[f"A{row_num}"] = tienda.upper()
        apply(ws[f"A{row_num}"], bold=True, fg=C_SECTION_FG, bg=C_SECTION_BG, align="left", size=10)
        ws.row_dimensions[row_num].height = 18
        row_num += 1

        for i, item in enumerate(productos):
            bg = C_ROW1_BG if i % 2 == 0 else C_ROW2_BG
            for col, val in enumerate([item["producto"], item["tienda"], item["cantidad"], item["prioridad"]], start=1):
                cell = ws.cell(row=row_num, column=col, value=val)
                apply(cell, fg="000000", bg=bg, align="left" if col == 1 else "center")
            ws.row_dimensions[row_num].height = 16
            row_num += 1

    ws.merge_cells(f"A{row_num}:C{row_num}")
    ws[f"A{row_num}"] = f"TOTAL: {len(items)} productos"
    apply(ws[f"A{row_num}"], bold=True, fg=C_TOTAL_FG, bg=C_TOTAL_BG, size=11)
    apply(ws.cell(row=row_num, column=4, value=""), bg=C_TOTAL_BG)
    ws.row_dimensions[row_num].height = 20

    wb.save(EXCEL_PATH)


# ─────────────────────────────────────────
# VISTAS FORMATEADAS EN HTML PARA TELEGRAM
# Nunca asteriscos. Solo <b>, <i>, <code>
# ─────────────────────────────────────────
def formato_vista_completa(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "Tu lista está vacía.\n\n<i>Dime qué necesitas y lo añado.</i>", None

    tiendas = {}
    for item in items:
        tiendas.setdefault(item["tienda"], []).append(item)

    urgentes_total = sum(1 for i in items if i["prioridad"] == "urgente")

    lineas = [
        "🛒 <b>LISTA DE LA COMPRA</b>",
        f"<i>{len(items)} productos · {len(tiendas)} tienda(s)</i>",
        "",
    ]

    for tienda, productos in sorted(tiendas.items()):
        lineas.append(f"📍 <b>{tienda.upper()}</b>")
        urgentes = [p for p in productos if p["prioridad"] == "urgente"]
        normales  = [p for p in productos if p["prioridad"] != "urgente"]
        for p in urgentes:
            lineas.append(f"  🔴 <b>{p['producto']}</b>   ×{p['cantidad']}")
        for p in normales:
            lineas.append(f"  ⚪ {p['producto']}   ×{p['cantidad']}")
        lineas.append("")

    if urgentes_total:
        lineas.append("<i>🔴 urgente · ⚪ normal</i>")

    texto = "\n".join(lineas)
    botones = [
        [
            InlineKeyboardButton("🔴 Solo urgentes", callback_data="filtro_urgentes"),
            InlineKeyboardButton("📍 Por tienda",    callback_data="filtro_tiendas"),
        ]
    ]
    return texto, InlineKeyboardMarkup(botones)


def formato_vista_tienda(tienda: str, items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    filtrados = [i for i in items if tienda.lower() in i["tienda"].lower()]

    if not filtrados:
        return f"No tienes nada pendiente en <b>{tienda.upper()}</b>.", None

    urgentes = [p for p in filtrados if p["prioridad"] == "urgente"]
    normales  = [p for p in filtrados if p["prioridad"] != "urgente"]

    lineas = [
        f"📍 <b>{tienda.upper()}</b>",
        f"<i>{len(filtrados)} productos pendientes</i>",
        "",
    ]

    if urgentes:
        lineas.append("🔴 <b>URGENTE</b>")
        for p in urgentes:
            lineas.append(f"  <b>{p['producto']}</b>   ×{p['cantidad']}")
        lineas.append("")

    if normales:
        lineas.append("⚪ <b>NORMAL</b>")
        for p in normales:
            lineas.append(f"  {p['producto']}   ×{p['cantidad']}")

    texto = "\n".join(lineas)
    botones = [
        [InlineKeyboardButton("✅ Compra hecha — borrar tienda", callback_data=f"limpiar_{tienda.lower()}")],
        [InlineKeyboardButton("📋 Ver toda la lista",            callback_data="filtro_todo")],
    ]
    return texto, InlineKeyboardMarkup(botones)


def formato_vista_urgentes(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    urgentes = [i for i in items if i["prioridad"] == "urgente"]

    if not urgentes:
        return "No tienes nada urgente pendiente. 🎉", None

    tiendas = {}
    for item in urgentes:
        tiendas.setdefault(item["tienda"], []).append(item)

    lineas = [
        "🔴 <b>URGENTE</b>",
        f"<i>{len(urgentes)} productos</i>",
        "",
    ]

    for tienda, productos in sorted(tiendas.items()):
        lineas.append(f"📍 <b>{tienda.upper()}</b>")
        for p in productos:
            lineas.append(f"  <b>{p['producto']}</b>   ×{p['cantidad']}")
        lineas.append("")

    texto = "\n".join(lineas)
    botones = [[InlineKeyboardButton("📋 Ver toda la lista", callback_data="filtro_todo")]]
    return texto, InlineKeyboardMarkup(botones)


def formato_vista_por_tiendas(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "La lista está vacía.", None

    tiendas = {}
    for item in items:
        tiendas.setdefault(item["tienda"], []).append(item)

    lineas = ["📍 <b>RESUMEN POR TIENDAS</b>", ""]

    botones_tienda = []
    for tienda, productos in sorted(tiendas.items()):
        urgentes = sum(1 for p in productos if p["prioridad"] == "urgente")
        badge = f"  🔴×{urgentes}" if urgentes else ""
        lineas.append(f"<b>{tienda.upper()}</b>{badge}  —  {len(productos)} productos")
        botones_tienda.append(
            InlineKeyboardButton(f"📍 {tienda.capitalize()}", callback_data=f"tienda_{tienda.lower()}")
        )

    lineas.append("")
    lineas.append("<i>Pulsa una tienda para ver su lista</i>")
    texto = "\n".join(lineas)

    filas = [botones_tienda[i:i+2] for i in range(0, len(botones_tienda), 2)]
    filas.append([InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")])
    return texto, InlineKeyboardMarkup(filas)


# ─────────────────────────────────────────
# CLAUDE PARSEA EL MENSAJE
# ─────────────────────────────────────────
def parsear_mensaje(mensaje: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        system="""Eres un parser de listas de la compra. Devuelve SOLO JSON válido sin backticks ni explicaciones.

Acciones posibles: añadir | eliminar | ver_tienda | ver_todo | ver_urgentes | limpiar_tienda

Para "añadir": extrae items con producto, tienda (si no dice tienda usa "sin tienda"), cantidad (default "1"), prioridad (urgente/normal, default "normal").

Ejemplos de respuesta:
{"accion": "añadir", "items": [{"producto": "leche", "tienda": "mercadona", "cantidad": "2", "prioridad": "normal"}]}
{"accion": "ver_tienda", "tienda": "mercadona"}
{"accion": "eliminar", "productos": ["leche"]}
{"accion": "limpiar_tienda", "tienda": "mercadona"}
{"accion": "ver_todo"}
{"accion": "ver_urgentes"}""",
        messages=[{"role": "user", "content": mensaje}]
    )
    texto = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)


# ─────────────────────────────────────────
# AGENTE PRINCIPAL
# ─────────────────────────────────────────
async def agente_compra(mensaje: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Devuelve (texto_html, teclado) para enviar con parse_mode=HTML."""
    try:
        parsed         = parsear_mensaje(mensaje)
        accion         = parsed.get("accion", "ver_todo")
        items_actuales = leer_items()

        if accion == "añadir":
            nuevos = parsed.get("items", [])
            if not nuevos:
                return "No entendí qué quieres añadir. Prueba: <i>leche x2 en Mercadona</i>", None
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
                return "Esos productos ya estaban en la lista.", None
            lineas = ["✅ <b>Añadido a la lista:</b>", ""]
            for i in añadidos:
                emoji = "🔴" if i["prioridad"] == "urgente" else "⚪"
                lineas.append(f"  {emoji} <b>{i['producto']}</b>   ×{i['cantidad']}   <i>({i['tienda']})</i>")
            botones = [[InlineKeyboardButton("📋 Ver lista completa", callback_data="filtro_todo")]]
            return "\n".join(lineas), InlineKeyboardMarkup(botones)

        elif accion == "eliminar":
            productos_borrar = [p.lower() for p in parsed.get("productos", [])]
            antes = len(items_actuales)
            items_actuales = [i for i in items_actuales if i["producto"].lower() not in productos_borrar]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)
            if borrados == 0:
                return "No encontré esos productos en la lista.", None
            botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
            return f"🗑 <b>{borrados} producto(s) eliminado(s).</b>", InlineKeyboardMarkup(botones)

        elif accion == "limpiar_tienda":
            tienda = parsed.get("tienda", "").lower()
            antes = len(items_actuales)
            items_actuales = [i for i in items_actuales if i["tienda"].lower() != tienda]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)
            botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
            return (
                f"✅ <b>Compra de {tienda.capitalize()} completada.</b>\n"
                f"<i>{borrados} productos eliminados.</i>",
                InlineKeyboardMarkup(botones)
            )

        elif accion == "ver_urgentes":
            return formato_vista_urgentes(items_actuales)

        elif accion == "ver_tienda":
            tienda = parsed.get("tienda", "")
            return formato_vista_tienda(tienda, items_actuales)

        else:
            return formato_vista_completa(items_actuales)

    except json.JSONDecodeError:
        return "No entendí el mensaje. Prueba: <i>añade leche y pan de Mercadona</i>", None
    except Exception as e:
        logger.error(f"Error en agente_compra: {e}")
        return "Hubo un error procesando tu lista. Inténtalo de nuevo.", None


# ─────────────────────────────────────────
# MANEJADOR DE BOTONES INLINE
# ─────────────────────────────────────────
async def manejar_callback_compra(data: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Recibe callback_data del botón y devuelve la vista correspondiente."""
    items_actuales = leer_items()

    if data == "filtro_todo":
        return formato_vista_completa(items_actuales)

    elif data == "filtro_urgentes":
        return formato_vista_urgentes(items_actuales)

    elif data == "filtro_tiendas":
        return formato_vista_por_tiendas(items_actuales)

    elif data.startswith("tienda_"):
        tienda = data.replace("tienda_", "")
        return formato_vista_tienda(tienda, items_actuales)

    elif data.startswith("limpiar_"):
        tienda = data.replace("limpiar_", "")
        antes = len(items_actuales)
        items_nuevos = [i for i in items_actuales if i["tienda"].lower() != tienda]
        borrados = antes - len(items_nuevos)
        guardar_excel(items_nuevos)
        botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
        return (
            f"✅ <b>Compra de {tienda.capitalize()} completada.</b>\n"
            f"<i>{borrados} productos eliminados.</i>",
            InlineKeyboardMarkup(botones)
        )

    return "Acción no reconocida.", None