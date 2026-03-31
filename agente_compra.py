import os
import json
import logging
from collections import defaultdict
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
    "alimentación":        "🥦",
    "higiene personal":    "🧴",
    "limpieza hogar":      "🧹",
    "farmacia y salud":    "💊",
    "tecnología":          "💻",
    "electrodomésticos":   "🔌",
    "mobiliario":          "🛋",
    "textil y ropa":       "👕",
    "papelería y oficina": "📎",
    "otros":               "📦",
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
            continue
        items.append({
            "producto":  producto,
            "tienda":    tienda,
            "cantidad":  str(row[2]).strip() if row[2] else "1",
            "prioridad": str(row[3]).strip() if row[3] else "normal",
            "categoria": str(row[4]).strip().lower() if row[4] else "otros",
        })
    return items


def guardar_excel(items: list[dict]):
    os.makedirs(os.path.dirname(os.path.abspath(EXCEL_PATH)), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista Compra"

    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 10
    ws.column_dimensions['D'].width = 12
    ws.column_dimensions['E'].width = 20

    ws.merge_cells("A1:E1")
    ws["A1"] = "Lista de la Compra"
    apply(ws["A1"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=13)
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 6

    for col, nombre in enumerate(["Producto", "Tienda", "Cantidad", "Prioridad", "Categoría"], start=1):
        cell = ws.cell(row=3, column=col, value=nombre.upper())
        apply(cell, bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, size=11)
    ws.row_dimensions[3].height = 20

    por_categoria = defaultdict(lambda: defaultdict(list))
    for item in items:
        por_categoria[item["categoria"]][item["tienda"]].append(item)

    row_num = 4
    for categoria in sorted(por_categoria.keys()):
        ws.merge_cells(f"A{row_num}:E{row_num}")
        ws[f"A{row_num}"] = f"{emoji_categoria(categoria)}  {categoria.upper()}"
        apply(ws[f"A{row_num}"], bold=True, fg=C_HEADER_FG, bg=C_HEADER_BG, align="left", size=11)
        ws.row_dimensions[row_num].height = 20
        row_num += 1

        for tienda in sorted(por_categoria[categoria].keys()):
            ws.merge_cells(f"A{row_num}:E{row_num}")
            ws[f"A{row_num}"] = f"    📍 {tienda.upper()}"
            apply(ws[f"A{row_num}"], bold=True, fg=C_SECTION_FG, bg=C_SECTION_BG, align="left", size=10)
            ws.row_dimensions[row_num].height = 18
            row_num += 1

            for i, item in enumerate(por_categoria[categoria][tienda]):
                bg = C_ROW1_BG if i % 2 == 0 else C_ROW2_BG
                for col, val in enumerate(
                    [item["producto"], item["tienda"], item["cantidad"], item["prioridad"], item["categoria"]],
                    start=1
                ):
                    cell = ws.cell(row=row_num, column=col, value=val)
                    apply(cell, fg="000000", bg=bg, align="left" if col == 1 else "center")
                ws.row_dimensions[row_num].height = 16
                row_num += 1

    ws.merge_cells(f"A{row_num}:D{row_num}")
    ws[f"A{row_num}"] = f"TOTAL: {len(items)} productos"
    apply(ws[f"A{row_num}"], bold=True, fg=C_TOTAL_FG, bg=C_TOTAL_BG, size=11)
    apply(ws.cell(row=row_num, column=5, value=""), bg=C_TOTAL_BG)
    ws.row_dimensions[row_num].height = 20
    wb.save(EXCEL_PATH)


# ─────────────────────────────────────────
# CLAUDE PARSEA EL MENSAJE
# ─────────────────────────────────────────
def parsear_mensaje(mensaje: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        system="""Eres un parser inteligente de listas de la compra. Devuelve SOLO JSON válido sin backticks ni explicaciones.

Acciones posibles:
- añadir: añadir productos a la lista
- eliminar: borrar uno o varios productos concretos ("ya compré la leche", "quita el pan")
- limpiar_tienda: borrar todos los productos de una tienda ("ya hice la compra de Mercadona", "limpia Mercadona")
- limpiar_categoria: borrar todos los productos de una categoría ("limpia los muebles", "ya compré todo lo de alimentación")
- actualizar: cambiar datos de un producto existente (tienda, cantidad, prioridad) ("el sofá cámbialo a Sklum", "la leche ponla como urgente", "necesito 3 yogures en vez de 1")
- ver_categoria: ver productos de una categoría
- ver_categorias: ver productos de varias categorías a la vez
- ver_tienda: ver productos de una tienda
- ver_todo: ver lista completa
- ver_urgentes: ver solo urgentes
- limpiar_tienda: borrar toda una tienda

Categorías válidas (en minúsculas exactas):
alimentación | higiene personal | limpieza hogar | farmacia y salud | tecnología | electrodomésticos | mobiliario | textil y ropa | papelería y oficina | otros

REGLAS DE CATEGORIZACIÓN:
- alimentación: comida, bebida, ingredientes, snacks
- higiene personal: cuidado corporal, cosmética, dental, champú, maquillaje, perfume
- limpieza hogar: detergentes, bayetas, fregonas, lavavajillas, ambientadores, esponjas
- farmacia y salud: medicamentos, vitaminas, tiritas, termómetros, suplementos
- tecnología: electrónica, cables, pilas, bombillas inteligentes
- electrodomésticos: aparatos con motor o calor (tostadora, aspiradora, batidora)
- mobiliario: muebles, estanterías, sillas, mesas, camas, sofás, almacenaje
- textil y ropa: ropa, calzado, ropa de cama, toallas, cortinas, cojines
- papelería y oficina: papel, bolígrafos, carpetas, post-its, tijeras
- otros: lo que no encaje claramente

Casos dudosos: "rin" → limpieza hogar | "velas decorativas" → otros | "velas relax" → higiene personal | "tuppers" → otros | "colchón" → mobiliario

Formatos de respuesta según acción:

Añadir:
{"accion": "añadir", "items": [{"producto": "leche", "tienda": "mercadona", "cantidad": "2", "prioridad": "normal", "categoria": "alimentación"}]}

Eliminar productos concretos:
{"accion": "eliminar", "productos": ["leche", "pan"]}

Limpiar tienda entera:
{"accion": "limpiar_tienda", "tienda": "mercadona"}

Limpiar categoría entera:
{"accion": "limpiar_categoria", "categoria": "mobiliario"}

Actualizar un producto (solo incluye los campos que cambian):
{"accion": "actualizar", "producto": "sofá", "cambios": {"tienda": "sklum", "cantidad": "1", "prioridad": "urgente"}}

Ver categoría:
{"accion": "ver_categoria", "categoria": "alimentación"}

Ver varias categorías:
{"accion": "ver_categorias", "categorias": ["alimentación", "higiene personal"]}

Ver tienda:
{"accion": "ver_tienda", "tienda": "mercadona"}

Ver todo:
{"accion": "ver_todo"}

Ver urgentes:
{"accion": "ver_urgentes"}""",
        messages=[{"role": "user", "content": mensaje}]
    )
    texto = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)


# ─────────────────────────────────────────
# VISTAS HTML PARA TELEGRAM
# ─────────────────────────────────────────
def _botones_navegacion() -> list:
    return [
        InlineKeyboardButton("📂 Categorías", callback_data="filtro_categorias"),
        InlineKeyboardButton("📍 Tiendas",    callback_data="filtro_tiendas"),
    ]


def formato_vista_completa(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "Tu lista está vacía.\n\n<i>Dime qué necesitas y lo añado.</i>", None

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
        lineas.append(f"{emoji_categoria(categoria)} <b>{categoria.upper()}</b>")
        for tienda in sorted(por_categoria[categoria].keys()):
            lineas.append(f"  📍 <i>{tienda.capitalize()}</i>")
            for p in [x for x in por_categoria[categoria][tienda] if x["prioridad"] == "urgente"]:
                lineas.append(f"    🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
            for p in [x for x in por_categoria[categoria][tienda] if x["prioridad"] != "urgente"]:
                lineas.append(f"    ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")
    if urgentes_total:
        lineas.append("<i>🔴 urgente · ⚪ normal</i>")

    botones = [
        _botones_navegacion(),
        [InlineKeyboardButton("🔴 Solo urgentes", callback_data="filtro_urgentes")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_por_categorias(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "La lista está vacía.", None

    por_cat = defaultdict(list)
    for item in items:
        por_cat[item["categoria"]].append(item)

    lineas = ["📂 <b>RESUMEN POR CATEGORÍAS</b>", ""]
    botones_cat = []
    for cat in sorted(por_cat.keys()):
        emoji = emoji_categoria(cat)
        urgentes = sum(1 for p in por_cat[cat] if p["prioridad"] == "urgente")
        badge = f"  🔴×{urgentes}" if urgentes else ""
        lineas.append(f"{emoji} <b>{cat.upper()}</b>{badge}  —  {len(por_cat[cat])} productos")
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

    por_tienda = defaultdict(list)
    for item in filtrados:
        por_tienda[item["tienda"]].append(item)

    emoji = emoji_categoria(categoria)
    lineas = [f"{emoji} <b>{categoria.upper()}</b>", f"<i>{len(filtrados)} productos</i>", ""]
    for tienda in sorted(por_tienda.keys()):
        lineas.append(f"📍 <i>{tienda.capitalize()}</i>")
        for p in [x for x in por_tienda[tienda] if x["prioridad"] == "urgente"]:
            lineas.append(f"  🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
        for p in [x for x in por_tienda[tienda] if x["prioridad"] != "urgente"]:
            lineas.append(f"  ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    botones = [
        _botones_navegacion(),
        [InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_multicategoria(categorias: list[str], items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    filtrados = [i for i in items if i["categoria"].lower() in [c.lower() for c in categorias]]
    if not filtrados:
        return f"No tienes nada en esas categorías.", None

    por_categoria = defaultdict(lambda: defaultdict(list))
    for item in filtrados:
        por_categoria[item["categoria"]][item["tienda"]].append(item)

    nombres = " · ".join([f"{emoji_categoria(c)} {c}" for c in sorted(categorias)])
    lineas = [f"<b>{nombres.upper()}</b>", f"<i>{len(filtrados)} productos</i>", ""]
    for cat in sorted(por_categoria.keys()):
        lineas.append(f"{emoji_categoria(cat)} <b>{cat.upper()}</b>")
        for tienda in sorted(por_categoria[cat].keys()):
            lineas.append(f"  📍 <i>{tienda.capitalize()}</i>")
            for p in [x for x in por_categoria[cat][tienda] if x["prioridad"] == "urgente"]:
                lineas.append(f"    🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
            for p in [x for x in por_categoria[cat][tienda] if x["prioridad"] != "urgente"]:
                lineas.append(f"    ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    botones = [
        _botones_navegacion(),
        [InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_tiendas(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return "La lista está vacía.", None

    por_tienda = defaultdict(list)
    for item in items:
        por_tienda[item["tienda"]].append(item)

    lineas = ["📍 <b>RESUMEN POR TIENDAS</b>", ""]
    botones_tienda = []
    for tienda in sorted(por_tienda.keys()):
        urgentes = sum(1 for p in por_tienda[tienda] if p["prioridad"] == "urgente")
        badge = f"  🔴×{urgentes}" if urgentes else ""
        lineas.append(f"<b>{tienda.upper()}</b>{badge}  —  {len(por_tienda[tienda])} productos")
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

    por_categoria = defaultdict(list)
    for item in filtrados:
        por_categoria[item["categoria"]].append(item)

    lineas = [f"📍 <b>{tienda.upper()}</b>", f"<i>{len(filtrados)} productos pendientes</i>", ""]
    for cat in sorted(por_categoria.keys()):
        lineas.append(f"{emoji_categoria(cat)} <i>{cat.capitalize()}</i>")
        for p in [x for x in por_categoria[cat] if x["prioridad"] == "urgente"]:
            lineas.append(f"  🔴 <b>{p['producto']}</b>  ×{p['cantidad']}")
        for p in [x for x in por_categoria[cat] if x["prioridad"] != "urgente"]:
            lineas.append(f"  ⚪ {p['producto']}  ×{p['cantidad']}")
        lineas.append("")

    botones = [
        [InlineKeyboardButton("✅ Compra hecha — borrar tienda", callback_data=f"limpiar_{tienda.lower()}")],
        _botones_navegacion(),
        [InlineKeyboardButton("📋 Ver todo", callback_data="filtro_todo")],
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(botones)


def formato_vista_urgentes(items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    urgentes = [i for i in items if i["prioridad"] == "urgente"]
    if not urgentes:
        return "No tienes nada urgente pendiente. 🎉", None

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

        # ── AÑADIR ──────────────────────────────────────────
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
                prior = "🔴" if i["prioridad"] == "urgente" else "⚪"
                lineas.append(
                    f"  {prior} <b>{i['producto']}</b>  ×{i['cantidad']}\n"
                    f"      {emoji_categoria(i.get('categoria','otros'))} <i>{i.get('categoria','otros')} · {i['tienda']}</i>"
                )
            botones = [[InlineKeyboardButton("📋 Ver lista completa", callback_data="filtro_todo")]]
            return "\n".join(lineas), InlineKeyboardMarkup(botones)

        # ── ELIMINAR PRODUCTOS CONCRETOS ────────────────────
        elif accion == "eliminar":
            productos_borrar = [p.lower() for p in parsed.get("productos", [])]
            antes = len(items_actuales)
            items_actuales = [i for i in items_actuales if i["producto"].lower() not in productos_borrar]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)
            if borrados == 0:
                return "No encontré esos productos en la lista.", None
            nombres = ", ".join(parsed.get("productos", []))
            botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
            return f"🗑 <b>Eliminado:</b> <i>{nombres}</i>", InlineKeyboardMarkup(botones)

        # ── LIMPIAR TIENDA ENTERA ───────────────────────────
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

        # ── LIMPIAR CATEGORÍA ENTERA ────────────────────────
        elif accion == "limpiar_categoria":
            categoria = parsed.get("categoria", "").lower()
            antes = len(items_actuales)
            items_actuales = [i for i in items_actuales if i["categoria"].lower() != categoria]
            borrados = antes - len(items_actuales)
            guardar_excel(items_actuales)
            emoji = emoji_categoria(categoria)
            botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
            return (
                f"✅ {emoji} <b>{categoria.capitalize()} limpiado.</b>\n"
                f"<i>{borrados} productos eliminados.</i>",
                InlineKeyboardMarkup(botones)
            )

        # ── ACTUALIZAR PRODUCTO ─────────────────────────────
        elif accion == "actualizar":
            nombre_buscar = parsed.get("producto", "").lower()
            cambios       = parsed.get("cambios", {})

            # Buscar el producto (búsqueda flexible)
            encontrado = None
            for item in items_actuales:
                if nombre_buscar in item["producto"].lower() or item["producto"].lower() in nombre_buscar:
                    encontrado = item
                    break

            if not encontrado:
                return (
                    f"No encontré <b>{parsed.get('producto','')}</b> en la lista.\n"
                    f"<i>¿Quizás está con otro nombre?</i>",
                    None
                )

            nombre_original = encontrado["producto"]
            cambios_aplicados = []

            if "tienda" in cambios:
                encontrado["tienda"] = cambios["tienda"].lower()
                cambios_aplicados.append(f"tienda → <i>{cambios['tienda']}</i>")
            if "cantidad" in cambios:
                encontrado["cantidad"] = cambios["cantidad"]
                cambios_aplicados.append(f"cantidad → <i>×{cambios['cantidad']}</i>")
            if "prioridad" in cambios:
                encontrado["prioridad"] = cambios["prioridad"]
                emoji_p = "🔴" if cambios["prioridad"] == "urgente" else "⚪"
                cambios_aplicados.append(f"prioridad → {emoji_p} <i>{cambios['prioridad']}</i>")
            if "categoria" in cambios:
                encontrado["categoria"] = cambios["categoria"].lower()
                cambios_aplicados.append(f"categoría → <i>{cambios['categoria']}</i>")

            guardar_excel(items_actuales)
            resumen = "\n  ".join(cambios_aplicados)
            botones = [[InlineKeyboardButton("📋 Ver lista", callback_data="filtro_todo")]]
            return (
                f"✏️ <b>{nombre_original}</b> actualizado:\n  {resumen}",
                InlineKeyboardMarkup(botones)
            )

        # ── VISTAS ──────────────────────────────────────────
        elif accion == "ver_urgentes":
            return formato_vista_urgentes(items_actuales)

        elif accion == "ver_tienda":
            return formato_vista_tienda(parsed.get("tienda", ""), items_actuales)

        elif accion == "ver_categoria":
            return formato_vista_categoria(parsed.get("categoria", "otros"), items_actuales)

        elif accion == "ver_categorias":
            return formato_vista_multicategoria(parsed.get("categorias", []), items_actuales)

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