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
# CATEGORÍAS Y SUS EMOJIS
# ─────────────────────────────────────────
CATEGORIAS = {
    "alimentación":       "🥦",
    "higiene personal":   "🧴",
    "limpieza hogar":     "🧹",
    "farmacia y salud":   "💊",
    "tecnología":         "💻",
    "electrodomésticos":  "🔌",
    "mobiliario":         "🛋",
    "textil y ropa":      "👕",
    "papelería y oficina":"📎",
    "otros":              "📦",
}

def emoji_categoria(cat: str) -> str:
    return CATEGORIAS.get(cat.lower(), "📦")


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
    ignorar = {"total", "lista de la compra", "producto", "tienda", "cantidad", "prioridad", "categoría"}
    items = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        if not row[0]:
            continue
        producto = str(row[0]).strip()
        if producto.lower() in ignorar or producto.lower().startswith("total:"):
            continue
        tienda = str(row[1]).strip() if row[1] else ""
        if not tienda:
            continue  # filas de sección fusionada — sin tienda en col B
        items.append({
            "producto":   producto,
            "tienda":     tienda,
            "cantidad":   str(row[2]).strip() if row[2] else "1",
            "prioridad":  str(row[3]).strip() if row[3] else "normal",
            "categoria":  str(row[4]).strip().lower() if row[4] else "otros",
        })
    return items


def guardar_excel(items: list[dict]):
    os.makedirs(os.path.dirname(os.path.abspath(EXCEL_PATH)), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista Compra"

    ws.column_dimensions['A'].width = 28  # Producto
    ws.column_dimensions['B'].width = 20  # Tienda
    ws.column_dimensions['C'].width = 10  # Cantidad
    ws.column_dimensions['D'].width = 12  # Prioridad
    ws.column_dimensions['E'].width = 20  # Categoría

    # Título
    ws.merge_cells("A1:E1")
    ws["A1"] = "Lista de la Compra"
    apply(ws["A1"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=13)
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 6

    # Cabeceras
    for col, nombre in enumerate(["Producto", "Tienda", "Cantidad", "Prioridad", "Categoría"], start=1):
        cell = ws.cell(row=3, column=col, value=nombre.upper())
        apply(cell, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=11)
    ws.row_dimensions[3].height = 20

    # Agrupar por categoría → tienda
    from collections import defaultdict
    por_categoria = defaultdict(lambda: defaultdict(list))
    for item in items:
        por_categoria[item["categoria"]][item["tienda"]].append(item)

    row_num = 4
    for categoria in sorted(por_categoria.keys()):
        # Fila de sección: categoría
        ws.merge_cells(f"A{row_num}:E{row_num}")
        emoji = emoji_categoria(categoria)
        ws[f"A{row_num}"] = f"{emoji}  {categoria.upper()}"
        apply(ws[f"A{row_num}"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, align="left", size=11)
        ws.row_dimensions[row_num].height = 20
        row_num += 1

        for tienda in sorted(por_categoria[categoria].keys()):
            # Subsección: tienda
            ws.merge_cells(f"A{row_num}:E{row_num}")
            ws[f"A{row_num}"] = f"    📍 {tienda.upper()}"
            apply(ws[f"A{row_num}"], bold=True, fg=C_SECTION_FG, bg=C_SECTION_BG, align="left", size=10)
            ws.row_dimensions[row_num].height = 18
            row_num += 1

            productos = por_categoria[categoria][tienda]
            for i, item in enumerate(productos):
                bg = C_ROW1_BG if i % 2 == 0 else C_ROW2_BG
                valores = [item["producto"], item["tienda"], item["cantidad"],
                           item["prioridad"], item["categoria"]]
                for col, val in enumerate(valores, start=1):
                    cell = ws.cell(row=row_num, column=col, value=val)
                    apply(cell, fg="000000", bg=bg, align="left" if col == 1 else "center")
                ws.row_dimensions[row_num].height = 16
                row_num += 1

    # Total
    ws.merge_cells(f"A{row_num}:D{row_num}")
    ws[f"A{row_num}"] = f"TOTAL: {len(items)} productos"
    apply(ws[f"A{row_num}"], bold=True, fg=C_TOTAL_FG, bg=C_TOTAL_BG, size=11)
    apply(ws.cell(row=row_num, column=5, value=""), bg=C_TOTAL_BG)
    ws.row_dimensions[row_num].height = 20

    wb.save(EXCEL_PATH)


# ─────────────────────────────────────────
# CLAUDE PARSEA EL MENSAJE
# Una sola llamada: extrae datos Y categoriza
# ─────────────────────────────────────────
def parsear_mensaje(mensaje: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        system="""Eres un parser inteligente de listas de la compra. Devuelve SOLO JSON válido sin backticks ni explicaciones.

Acciones posibles: añadir | eliminar | ver_categoria | ver_tienda | ver_todo | ver_urgentes | limpiar_tienda

Para "añadir" extrae cada producto con:
- producto: nombre limpio y en minúsculas
- tienda: en minúsculas (si no dice tienda usa "sin tienda")
- cantidad: número como string (default "1")
- prioridad: "urgente" o "normal" (default "normal")
- categoria: una de estas exactamente en minúsculas:
  alimentación | higiene personal | limpieza hogar | farmacia y salud |
  tecnología | electrodomésticos | mobiliario | textil y ropa | papelería y oficina | otros

REGLAS DE CATEGORIZACIÓN — razona con contexto, no de forma mecánica:
- alimentación: comida, bebida, ingredientes, snacks, condimentos
- higiene personal: cuidado corporal, cosmética, higiene bucal, desodorante, champú, maquillaje, perfume
- limpieza hogar: productos de limpieza, bayetas, fregonas, detergente ropa, lavavajillas, ambientadores
- farmacia y salud: medicamentos, vitaminas, tiritas, termómetros, anticonceptivos, suplementos
- tecnología: dispositivos electrónicos, cables, accesorios tech, pilas, bombillas inteligentes
- electrodomésticos: aparatos para el hogar con motor o calor (tostadora, aspiradora, batidora...)
- mobiliario: muebles, estanterías, sillas, mesas, camas, almacenaje
- textil y ropa: ropa, calzado, ropa de cama, toallas, cortinas, cojines
- papelería y oficina: papel, bolígrafos, carpetas, tóner, post-its, tijeras
- otros: cualquier cosa que no encaje claramente en las anteriores

Casos dudosos — razona:
- "velas": si son decorativas → otros; si son para aromaterapia/relax → higiene personal
- "rin": detergente → limpieza hogar
- "tuppers": almacenaje cocina → otros
- "colchón": mobiliario
- "bombillas normales": tecnología
- "esponjas": limpieza hogar
- "termómetro": farmacia y salud

Ejemplos de respuesta:
{"accion": "añadir", "items": [{"producto": "leche de almendra", "tienda": "mercadona", "cantidad": "2", "prioridad": "normal", "categoria": "alimentación"}]}
{"accion": "ver_tienda", "tienda": "mercadona"}
{"accion": "ver_categoria", "categoria": "alimentación"}
{"accion": "eliminar", "productos": ["leche"]}
{"accion": "limpiar_tienda", "tienda": "mercadona"}
{"accion": "ver_todo"}
{"accion": "ver_urgentes"}""",
        messages=[{"role": "user", "content": mensaje}]
    )
    texto = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)


# ─────────────────────────────────────────
# VISTAS FORMATEADAS EN HTML PARA TELEGRAM
# ─────────────────────────────────────────
def _boton_vistas() -> list:
    return [
        InlineKeyboardButton("📂 Por categoría", callback_data="filtro_categorias"),
        InlineKeyboardButton("📍 Por tienda",    callback_data="filtro_tiendas"),
    ]

def formato_vista_completa(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "Tu lista está vacía.\n\n<i>Dime qué necesitas y lo añado.</i>", None

    # Agrupar por categoría → tienda
    from collections import defaultdict
    por_categoria = defaultdict(lambda: defaultdict(list))
    for item in items:
        por_categoria[item["categoria"]][item["tienda"]].append(item)

    urgentes_total = sum(1 for i in items if i["prioridad"] == "urgente")

    lineas = [
        "🛒 <b>LISTA DE LA COMPRA</b>",
        f"<i>{len(items)} productos · {len(por_categoria)} categorías</i>",
        "",
    ]

    for categoria in sorted(por_categoria.keys()):
        emoji = emoji_categoria(categoria)
        lineas.append(f"{emoji} <b>{categoria.upper()}</b>")

        for tienda in sorted(por_categoria[categoria].keys()):
            lineas.append(f"  📍 <i>{tienda.capitalize()}</i>")
            urgentes = [p for p in por_categoria[categoria][tienda] if p["prioridad"] == "urgente"]
            normales  = [p for p in por_categoria[categoria][tienda] if p["prioridad"] != "urgente"]
            for p in urgentes:
                lineas.append(f"    🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
            for p in normales:
                lineas.append(f"    ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    if urgentes_total:
        lineas.append("<i>🔴 urgente · ⚪ normal</i>")

    botones = [
        _boton_vistas(),
        [InlineKeyboardButton("🔴 Solo urgentes", callback_data="filtro_urgentes")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_por_categorias(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "La lista está vacía.", None

    from collections import defaultdict
    por_categoria = defaultdict(list)
    for item in items:
        por_categoria[item["categoria"]].append(item)

    lineas = ["📂 <b>RESUMEN POR CATEGORÍAS</b>", ""]
    botones_cat = []

    for cat in sorted(por_categoria.keys()):
        emoji = emoji_categoria(cat)
        productos = por_categoria[cat]
        urgentes = sum(1 for p in productos if p["prioridad"] == "urgente")
        badge = f"  🔴×{urgentes}" if urgentes else ""
        lineas.append(f"{emoji} <b>{cat.upper()}</b>{badge}  —  {len(productos)} productos")
        botones_cat.append(
            InlineKeyboardButton(f"{emoji} {cat.capitalize()}", callback_data=f"categoria_{cat}")
        )

    lineas.append("\n<i>Pulsa una categoría para ver su detalle</i>")
    filas = [botones_cat[i:i+2] for i in range(0, len(botones_cat), 2)]
    filas.append([InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")])
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


def formato_vista_categoria(categoria: str, items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    filtrados = [i for i in items if i["categoria"].lower() == categoria.lower()]
    if not filtrados:
        return f"No tienes nada en <b>{categoria}</b>.", None

    from collections import defaultdict
    por_tienda = defaultdict(list)
    for item in filtrados:
        por_tienda[item["tienda"]].append(item)

    emoji = emoji_categoria(categoria)
    lineas = [
        f"{emoji} <b>{categoria.upper()}</b>",
        f"<i>{len(filtrados)} productos</i>",
        "",
    ]

    for tienda in sorted(por_tienda.keys()):
        lineas.append(f"📍 <i>{tienda.capitalize()}</i>")
        urgentes = [p for p in por_tienda[tienda] if p["prioridad"] == "urgente"]
        normales  = [p for p in por_tienda[tienda] if p["prioridad"] != "urgente"]
        for p in urgentes:
            lineas.append(f"  🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
        for p in normales:
            lineas.append(f"  ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    botones = [
        [InlineKeyboardButton("📂 Ver categorías", callback_data="filtro_categorias")],
        [InlineKeyboardButton("📋 Ver todo",        callback_data="filtro_todo")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_tiendas(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "La lista está vacía.", None

    from collections import defaultdict
    por_tienda = defaultdict(list)
    for item in items:
        por_tienda[item["tienda"]].append(item)

    lineas = ["📍 <b>RESUMEN POR TIENDAS</b>", ""]
    botones_tienda = []

    for tienda in sorted(por_tienda.keys()):
        productos = por_tienda[tienda]
        urgentes = sum(1 for p in productos if p["prioridad"] == "urgente")
        badge = f"  🔴×{urgentes}" if urgentes else ""
        lineas.append(f"<b>{tienda.upper()}</b>{badge}  —  {len(productos)} productos")
        botones_tienda.append(
            InlineKeyboardButton(f"📍 {tienda.capitalize()}", callback_data=f"tienda_{tienda.lower()}")
        )

    lineas.append("\n<i>Pulsa una tienda para ver su lista</i>")
    filas = [botones_tienda[i:i+2] for i in range(0, len(botones_tienda), 2)]
    filas.append([InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")])
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


def formato_vista_tienda(tienda: str, items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    filtrados = [i for i in items if tienda.lower() in i["tienda"].lower()]
    if not filtrados:
        return f"No tienes nada pendiente en <b>{tienda.upper()}</b>.", None

    from collections import defaultdict
    por_categoria = defaultdict(list)
    for item in filtrados:
        por_categoria[item["categoria"]].append(item)

    lineas = [
        f"📍 <b>{tienda.upper()}</b>",
        f"<i>{len(filtrados)} productos pendientes</i>",
        "",
    ]

    for cat in sorted(por_categoria.keys()):
        emoji = emoji_categoria(cat)
        lineas.append(f"{emoji} <i>{cat.capitalize()}</i>")
        urgentes = [p for p in por_categoria[cat] if p["prioridad"] == "urgente"]
        normales  = [p for p in por_categoria[cat] if p["prioridad"] != "urgente"]
        for p in urgentes:
            lineas.append(f"  🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
        for p in normales:
            lineas.append(f"  ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    botones = [
        [InlineKeyboardButton("✅ Compra hecha — borrar tienda", callback_data=f"limpiar_{tienda.lower()}")],
        [InlineKeyboardButton("📍 Ver tiendas", callback_data="filtro_tiendas"),
         InlineKeyboardButton("📋 Ver todo",    callback_data="filtro_todo")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_urgentes(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    urgentes = [i for i in items if i["prioridad"] == "urgente"]
    if not urgentes:
        return "No tienes nada urgente pendiente. 🎉", None

    from collections import defaultdict
    por_tienda = defaultdict(list)
    for item in urgentes:
        por_tienda[item["tienda"]].append(item)

    lineas = ["🔴 <b>URGENTE</b>", f"<i>{len(urgentes)} productos</i>", ""]
    for tienda in sorted(por_tienda.keys()):
        lineas.append(f"📍 <b>{tienda.upper()}</b>")
        for p in por_tienda[tienda]:
            lineas.append(f"  <b>{p['producto']}</b>  ×{p['cantidad']}  <i>({p['categoria']})</i>")
        lineas.append("")

    botones = [[InlineKeyboardButton("📋 Ver toda la lista", callback_data="filtro_todo")]]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


# ─────────────────────────────────────────
# AGENTE PRINCIPAL
# ─────────────────────────────────────────
async def agente_compra(mensaje: str) -> tuple[str, InlineKeyboardMarkup | None]:
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
                emoji = emoji_categoria(i.get("categoria", "otros"))
                prior = "🔴" if i["prioridad"] == "urgente" else "⚪"
                lineas.append(
                    f"  {prior} <b>{i['producto']}</b>  ×{i['cantidad']}\n"
                    f"      {emoji} <i>{i.get('categoria', 'otros')} · {i['tienda']}</i>"
                )

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
            return formato_vista_tienda(parsed.get("tienda", ""), items_actuales)

        elif accion == "ver_categoria":
            return formato_vista_categoria(parsed.get("categoria", "otros"), items_actuales)

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
    items_actuales = leer_items()

    if data == "filtro_todo":
        return formato_vista_completa(items_actuales)
    elif data == "filtro_urgentes":
        return formato_vista_urgentes(items_actuales)
    elif data == "filtro_tiendas":
        return formato_vista_tiendas(items_actuales)
    elif data == "filtro_categorias":
        return formato_vista_por_categorias(items_actuales)
    elif data.startswith("tienda_"):
        return formato_vista_tienda(data.replace("tienda_", ""), items_actuales)
    elif data.startswith("categoria_"):
        return formato_vista_categoria(data.replace("categoria_", ""), items_actuales)
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