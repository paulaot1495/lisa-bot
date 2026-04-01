"""
storage.py — Lectura y escritura del Excel nutricional.
Sin lógica de IA ni de agente.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
import os

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

logger = logging.getLogger(__name__)
EXCEL_PATH = Path(os.getenv("NUTRITION_EXCEL_PATH", "/data/comidas.xlsx"))

COLUMNAS = ["Fecha", "Descripcion", "Calorias (kcal)", "Proteinas (g)", "Carbohidratos (g)", "Grasas (g)", "Azucar (g)", "Fibra (g)"]
COL_IDX = {c: i + 1 for i, c in enumerate(COLUMNAS)}

# ── Estilos ──────────────────────────────────────────────────────────────────

def _border():
    s = Side(style="thin", color="BBCDD8")
    return Border(left=s, right=s, top=s, bottom=s)

def _style(cell, bold=False, fg="000000", bg=None, align="center"):
    cell.font = Font(name="Arial", bold=bold, size=10, color=fg)
    if bg:
        cell.fill = PatternFill("solid", start_color=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center", indent=1 if align == "left" else 0)
    cell.border = _border()

# ── Crear / cargar ────────────────────────────────────────────────────────────

def _crear_excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "Comidas"

    ws.merge_cells(f"A1:{chr(64 + len(COLUMNAS))}1")
    c = ws["A1"]
    c.value = "Registro Nutricional"
    _style(c, bold=True, fg="FFFFFF", bg="6B8CAE")
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 6

    for i, col in enumerate(COLUMNAS, 1):
        cell = ws.cell(row=3, column=i, value=col)
        _style(cell, bold=True, fg="FFFFFF", bg="6B8CAE")

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 40
    for letter in "CDEFGH":
        ws.column_dimensions[letter].width = 18

    EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(EXCEL_PATH)
    return wb

def _cargar():
    if not EXCEL_PATH.exists():
        return _crear_excel()
    return load_workbook(EXCEL_PATH)

# ── Leer ──────────────────────────────────────────────────────────────────────

def leer_registros(dias: int = 7) -> list[dict]:
    """Devuelve los registros de los últimos N días (0 = todos)."""
    if not EXCEL_PATH.exists():
        return []
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name="Comidas", header=2)
        df = df.dropna(subset=[df.columns[0]])
        limite = datetime.now() - timedelta(days=dias) if dias > 0 else None
        registros = []
        for _, row in df.iterrows():
            try:
                fecha_dt = datetime.strptime(str(row.iloc[0]).strip(), "%d/%m/%Y")
            except ValueError:
                continue
            if limite and fecha_dt < limite:
                continue
            registros.append({
                "fecha": row.iloc[0],
                "descripcion": str(row.iloc[1] or ""),
                "calorias": float(row.iloc[2] or 0),
                "proteinas": float(row.iloc[3] or 0),
                "carbohidratos": float(row.iloc[4] or 0),
                "grasas": float(row.iloc[5] or 0),
                "azucar": float(row.iloc[6] or 0),
                "fibra": float(row.iloc[7] or 0),
            })
        return sorted(registros, key=lambda x: datetime.strptime(x["fecha"], "%d/%m/%Y"))
    except Exception as e:
        logger.error(f"Error leyendo Excel: {e}")
        return []

# ── Escribir ──────────────────────────────────────────────────────────────────

def _fila_fecha(ws, fecha_str: str):
    for row in ws.iter_rows(min_row=4, max_col=1):
        if str(row[0].value or "").strip() == fecha_str:
            return row[0].row
    return None

def _siguiente_fila(ws) -> int:
    max_row = 3
    for row in ws.iter_rows(min_row=4, max_col=1):
        if row[0].value is not None:
            max_row = row[0].row
    return max(4, max_row + 1)

def guardar_comida(datos: dict, fecha: datetime) -> tuple[bool, bool]:
    """
    Guarda o acumula los datos en el Excel.
    Devuelve (ok, es_nueva_fila).
    """
    try:
        wb = _cargar()
        ws = wb["Comidas"]
        fecha_str = fecha.strftime("%d/%m/%Y")
        fila = _fila_fecha(ws, fecha_str)
        es_nueva = fila is None
        row_num = _siguiente_fila(ws) if es_nueva else fila
        bg = "EAF4FB" if row_num % 2 == 0 else "F5FBFE"
        NUM_FMT = "#,##0.0"

        if es_nueva:
            valores = [
                ("Fecha", fecha_str, None, "center"),
                ("Descripcion", datos["descripcion_comida"], None, "left"),
                ("Calorias (kcal)", datos["totales"]["calorias"], NUM_FMT, "center"),
                ("Proteinas (g)", datos["totales"]["proteinas"], NUM_FMT, "center"),
                ("Carbohidratos (g)", datos["totales"]["carbohidratos"], NUM_FMT, "center"),
                ("Grasas (g)", datos["totales"]["grasas"], NUM_FMT, "center"),
                ("Azucar (g)", datos["totales"]["azucar"], NUM_FMT, "center"),
                ("Fibra (g)", datos["totales"]["fibra"], NUM_FMT, "center"),
            ]
            for col_name, value, fmt, align in valores:
                cell = ws.cell(row=row_num, column=COL_IDX[col_name], value=value)
                _style(cell, bg=bg, align=align)
                if fmt:
                    cell.number_format = fmt
        else:
            # Acumular numéricos
            for col_name, key in [
                ("Calorias (kcal)", "calorias"), ("Proteinas (g)", "proteinas"),
                ("Carbohidratos (g)", "carbohidratos"), ("Grasas (g)", "grasas"),
                ("Azucar (g)", "azucar"), ("Fibra (g)", "fibra"),
            ]:
                cell = ws.cell(row=row_num, column=COL_IDX[col_name])
                cell.value = round(float(cell.value or 0) + datos["totales"][key], 1)
                _style(cell, bg=bg)
                cell.number_format = "#,##0.0"
            # Concatenar descripción
            cell_desc = ws.cell(row=row_num, column=COL_IDX["Descripcion"])
            cell_desc.value = str(cell_desc.value or "") + " + " + datos["descripcion_comida"]
            _style(cell_desc, bg=bg, align="left")

        ws.row_dimensions[row_num].height = 20
        wb.save(EXCEL_PATH)
        return True, es_nueva
    except Exception as e:
        logger.error(f"Error guardando Excel: {e}")
        return False, False

# ── Borrar ────────────────────────────────────────────────────────────────────

def borrar_dia(fecha_str: str) -> bool:
    """Elimina la fila de una fecha concreta."""
    try:
        wb = _cargar()
        ws = wb["Comidas"]
        fila = _fila_fecha(ws, fecha_str)
        if fila is None:
            return False
        ws.delete_rows(fila)
        wb.save(EXCEL_PATH)
        return True
    except Exception as e:
        logger.error(f"Error borrando fila: {e}")
        return False

def borrar_todo() -> bool:
    """Elimina el Excel completo y crea uno vacío."""
    try:
        if EXCEL_PATH.exists():
            EXCEL_PATH.unlink()
        _crear_excel()
        return True
    except Exception as e:
        logger.error(f"Error reseteando Excel: {e}")
        return False

def cargar_base_nutricional() -> dict:
    ruta = Path(os.getenv("BASE_NUTRICIONAL_PATH", "/data/base_nutricional.xlsx"))
    if not ruta.exists():
        return {}
    try:
        df = pd.read_excel(ruta)
        df.columns = [c.strip().lower() for c in df.columns]
        base = {}
        for _, row in df.iterrows():
            nombre = str(row.get("alimento", row.get("nombre", ""))).strip().lower()
            if nombre:
                base[nombre] = {
                    "calorias": float(row.get("calorias", row.get("kcal", 0)) or 0),
                    "proteinas": float(row.get("proteinas", row.get("proteina", 0)) or 0),
                    "carbohidratos": float(row.get("carbohidratos", row.get("hidratos", 0)) or 0),
                    "grasas": float(row.get("grasas", row.get("grasa", 0)) or 0),
                    "azucar": float(row.get("azucar", 0) or 0),
                    "fibra": float(row.get("fibra", 0) or 0),
                }
        return base
    except Exception as e:
        logger.warning(f"No se pudo cargar base_nutricional: {e}")
        return {}