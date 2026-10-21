"""
Exportador XLSX estructurado para vigencias de pedidos CIPSA.

Genera un archivo .xlsx con 8 hojas:
- RESUMEN: KPIs globales + tabla por categoria.
- POR_CLIENTE: agrupado por COD_CLIENTE + NOM_CLIENTE.
- POR_VENDEDOR: agrupado por ID_VENDEDOR + NOM_VENDEDOR.
- POR_PRODUCTO: agrupado por SKU con cobertura de stock.
- STOCK_DESPACHO: resumen pedido completo vs despachado vs disponible.
- DETALLE: todas las filas con formulas Excel en columnas calculadas.
- ALERTAS_QC: SKUs con saldo > 5000 ordenados por saldo descendente.

El nombre del archivo usa el patron pedidos_vigencias_YYYYMMDD_HHMMSS.xlsx.
Formato: header fill #10B981, fuente blanca negrita, freeze panes y
auto-ancho de columnas.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Estilos de encabezado (marca CIPSA)
_HEADER_FILL = PatternFill(start_color="10B981", end_color="10B981", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center")

# Estilo corporativo: banda de titulo y formatos numericos CIPSA
_TITLE_FILL = PatternFill(start_color="0B6B47", end_color="0B6B47", fill_type="solid")
_TITLE_FONT = Font(color="FFFFFF", bold=True, size=13)
_SUBTITLE_FONT = Font(color="1F2937", italic=True, size=10)
_SECTIONS_FILL = PatternFill(start_color="34D399", end_color="34D399", fill_type="solid")
_SECTIONS_FONT = Font(color="06281C", bold=True, size=10)
_SUBTOTAL_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
_SUBTOTAL_FONT = Font(color="06281C", bold=True)
_CURRENCY = '"S/" #,##0.00'
_CURRENCY_0 = '"S/" #,##0'
_NUMBER = "#,##0.00"
_NUMBER_0 = "#,##0"
_PCT = "0.0"

_QC_THRESHOLD = 5000


def _banda_titulo(ws, ncols: int, titulo: str, subtitulo: str = "") -> None:
    """Banda corporativa: titulo en fila 1 y bajada en fila 2."""
    ws.cell(row=1, column=1, value=titulo)
    ws.cell(row=1, column=1).font = _TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(ncols, 2))
    for col in range(1, max(ncols, 2) + 1):
        ws.cell(row=1, column=col).fill = _TITLE_FILL
    if subtitulo:
        ws.cell(row=2, column=1, value=subtitulo)
        ws.cell(row=2, column=1).font = _SUBTITLE_FONT
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(ncols, 2))


def _formato_por_columna(ws, mapa: dict[str, str], desde: int = 2, fila_enc: int = 1) -> None:
    """Aplica formato de celda (moneda/numero/porcentaje) por nombre de columna.

    `mapa` = {nombre_columna: formato}. Busca la columna en la fila de
    encabezado `fila_enc` y aplica el formato desde `desde` hasta la ultima
    fila con datos.
    """
    if ws.max_row < desde:
        return
    encabezados = {
        str(ws.cell(row=fila_enc, column=c).value): c for c in range(1, ws.max_column + 1)
    }
    for nombre, fmt in mapa.items():
        col = encabezados.get(nombre)
        if not col:
            continue
        for row in range(desde, ws.max_row + 1):
            ws.cell(row=row, column=col).number_format = fmt


# Columnas monetarias / numericas del reporte de accion (formato automatico).
_MAPA_FORMATOS = {
    "despachable_hoy": _CURRENCY,
    "si_se_aprueba": _CURRENCY,
    "val_atencion": _CURRENCY,
    "val_pendiente": _CURRENCY,
    "monto_hoy": _CURRENCY,
    "monto_total": _CURRENCY,
    "valor": _CURRENCY,
    "valor_pedido": _CURRENCY,
    "valor_atendido": _CURRENCY,
    "cant_a_despachar": _NUMBER_0,
    "kg_a_despachar": _NUMBER,
    "kg_hoy": _NUMBER,
    "kg_saldo": _NUMBER,
    "kg_cobertura": _PCT,
    "peso_kg": _NUMBER,
    "stock_VES": _NUMBER_0,
    "stock_121": _NUMBER_0,
    "a_trasladar": _NUMBER_0,
    "trasladable": _NUMBER_0,
    "saldo": _NUMBER_0,
    "faltante_total": _NUMBER_0,
    "fuera_de_alcance_121": _NUMBER_0,
    "pedido": _NUMBER_0,
    "despacho": _NUMBER_0,
    "cajas": _NUMBER,
    "pct_cubierto": _PCT,
    "pct_cant": _PCT,
    "pct_cant_pedido": _PCT,
    "pct_cubierto_pedido": _PCT,
    "POR_VIGENCIA": _PCT,
    "VIGENCIA": _NUMBER,
    "dias": _NUMBER_0,
    "score_sustituto": "0.000",
    "sustituto_stock": _NUMBER_0,
    "pedido_und": _NUMBER_0,
    "entregado_und": _NUMBER_0,
    "saldo_und": _NUMBER_0,
    "pct_avance": _PCT,
    "NUEVO_sal": _NUMBER_0,
    "NUEVO_ped": _NUMBER_0,
    "IMPORTADO_sal": _NUMBER_0,
    "IMPORTADO_ped": _NUMBER_0,
    "TRADICIONAL_sal": _NUMBER_0,
    "TRADICIONAL_ped": _NUMBER_0,
    "NACIONAL_sal": _NUMBER_0,
    "NACIONAL_ped": _NUMBER_0,
}


def _formatos_corporativos(ws, desde: int = 2, fila_enc: int = 1) -> None:
    """Aplica el mapa de formatos automatico por nombre de columna."""
    _formato_por_columna(ws, _MAPA_FORMATOS, desde=desde, fila_enc=fila_enc)


def _default_filename() -> str:
    """Nombre de archivo con timestamp: pedidos_vigencias_YYYYMMDD_HHMMSS.xlsx."""
    return f"pedidos_vigencias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"


def _style_header(ws, ncols: int, fila: int = 1) -> None:
    """Aplica el formato del encabezado a la fila dera de la hoja."""
    for col in range(1, ncols + 1):
        cell = ws.cell(row=fila, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN


def _abrir_hoja(wb, nombre: str, titulo: str, subtitulo: str, headers: list[str]) -> "object":
    """Hoja corporativa: banda de titulo (fila 1-2) y encabezados (fila 3).

    Devuelve la hoja ya formateada; el contenido empieza en la fila 4 y
    `_finish_sheet` debe llamarse con fila_enc=3.
    """
    ws = wb.create_sheet(nombre)
    _banda_titulo(ws, len(headers), titulo, subtitulo)
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col, value=h)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
    return ws


def _auto_width(ws) -> None:
    """Ajusta el ancho de columnas segun el contenido (max 40)."""
    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        max_len = 0
        for cell in col_cells:
            val = cell.value
            if val is not None:
                length = len(str(val))
                max_len = max(max_len, length)
        ws.column_dimensions[letter].width = min(max_len + 3, 40)


def export_to_xlsx(df: pd.DataFrame, output_path: str | Path | None = None) -> Path:
    """Genera el XLSX con 8 hojas y retorna la ruta del archivo creado.

    Recibe el DataFrame enriquecido (con categoria, estado_linea, un_bx,
    saldo, cajas, valor_saldo) producido por el pipeline de ingesta.
    """
    output_path = Path(output_path or _default_filename())
    wb = Workbook()

    _write_resumen(wb, df)
    _write_por_cliente(wb, df)
    _write_por_vendedor(wb, df)
    _write_por_producto(wb, df)
    _write_stock_despacho(wb, df)
    _write_detalle(wb, df)
    _write_alertas_qc(wb, df)
    _write_hojas_por_vendedor(wb, df)

    wb.save(output_path)
    return output_path


# ---------------------------------------------------------------
# Hoja RESUMEN
# ---------------------------------------------------------------
def _write_resumen(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.active
    ws.title = "RESUMEN"

    # KPIs globales
    kpis = _global_kpis(df)
    ws["A1"] = "KPI"
    ws["B1"] = "Valor"
    rows_kpi = [
        ("Total Items", kpis["total_items"]),
        ("Total Pedido (units)", kpis["total_pedido"]),
        ("Total Despachado (units)", kpis["total_despachado"]),
        ("Saldo Pendiente (units)", kpis["saldo_total"]),
        ("Cajas Pendientes", kpis["cajas_total"]),
        ("Valor Total S/", kpis["valor_total"]),
        ("Clientes", kpis["n_clientes"]),
        ("Vendedores", kpis["n_vendedores"]),
        ("Almacenes", kpis["n_almacenes"]),
    ]
    r = 2
    for label, value in rows_kpi:
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=value)
        r += 1

    # Tabla por categoria con formulas Excel
    r += 1
    ws.cell(row=r, column=1, value="Categoria")
    ws.cell(row=r, column=2, value="Items")
    ws.cell(row=r, column=3, value="Pedido")
    ws.cell(row=r, column=4, value="Despachado")
    ws.cell(row=r, column=5, value="Saldo")
    ws.cell(row=r, column=6, value="Cajas")
    ws.cell(row=r, column=7, value="Valor S/")
    _style_header(ws, 7)
    r += 1
    if "categoria" in df.columns:
        by_cat = (
            df.groupby("categoria", dropna=False)
            .agg(
                items=("CAN_PEDIDO", "size"),
                pedido=("CAN_PEDIDO", "sum"),
                despachado=("CAN_DESPACHO", "sum"),
                saldo=("saldo", "sum"),
                cajas=("cajas", "sum"),
                valor=("valor_saldo", "sum"),
            )
            .reset_index()
        )
        for _, row in by_cat.iterrows():
            ws.cell(row=r, column=1, value=str(row["categoria"]))
            ws.cell(row=r, column=2, value=int(row["items"]))
            ws.cell(row=r, column=3, value=row["pedido"])
            ws.cell(row=r, column=4, value=row["despachado"])
            ws.cell(row=r, column=5, value=row["saldo"])
            ws.cell(row=r, column=6, value=row["cajas"])
            ws.cell(row=r, column=7, value=row["valor"])
            r += 1

    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja POR_CLIENTE
# ---------------------------------------------------------------
def _write_por_cliente(wb: Workbook, df: pd.DataFrame) -> None:
    """Hoja resumen por cliente con saldo pendiente y valor."""
    ws = wb.create_sheet("POR_CLIENTE")
    headers = [
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "Items",
        "Pedidos",
        "Saldo",
        "Cajas",
        "Valor S/",
        "Cond_Pago",
    ]
    ws.append(headers)
    _style_header(ws, len(headers))
    if "COD_CLIENTE" in df.columns and "NOM_CLIENTE" in df.columns:
        # Columna de pedidos: ID_PEDIDO si existe, fallback a NRO_DOCUMENTO
        pedidos_col = (
            "ID_PEDIDO"
            if "ID_PEDIDO" in df.columns
            else ("NRO_DOCUMENTO" if "NRO_DOCUMENTO" in df.columns else None)
        )
        agg_kwargs = {
            "items": ("CAN_PEDIDO", "size"),
            "saldo": ("saldo", "sum") if "saldo" in df else ("CAN_PEDIDO", "sum"),
            "cajas": ("cajas", "sum") if "cajas" in df else ("CAN_PEDIDO", lambda x: 0),
            "valor": ("valor_saldo", "sum")
            if "valor_saldo" in df
            else ("PEDIDO_IMPORTE_ARITCULO", "sum"),
            "cond": ("CONDICION_PAGO", lambda s: s.mode().iloc[0] if not s.mode().empty else ""),
        }
        if pedidos_col:
            agg_kwargs["pedidos"] = (pedidos_col, "nunique")
        g = df.groupby(["COD_CLIENTE", "NOM_CLIENTE"], dropna=False).agg(**agg_kwargs).reset_index()
        if not pedidos_col:
            g["pedidos"] = 0
        for _, row in g.iterrows():
            ws.append(
                [
                    str(row["COD_CLIENTE"]),
                    str(row["NOM_CLIENTE"]),
                    int(row["items"]),
                    int(row["pedidos"]),
                    row["saldo"],
                    row["cajas"],
                    row["valor"],
                    str(row["cond"]),
                ]
            )
    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja POR_VENDEDOR
# ---------------------------------------------------------------
def _write_por_vendedor(wb: Workbook, df: pd.DataFrame) -> None:
    """Hoja resumen por vendedor con alertas y pedidos original vs atendido."""
    ws = wb.create_sheet("POR_VENDEDOR")
    headers = [
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "Items",
        "Pedidos",
        "Saldo",
        "Valor S/",
        "% Atendido",
        "Aprobados",
        "Ingresados",
    ]
    ws.append(headers)
    _style_header(ws, len(headers))
    if "ID_VENDEDOR" in df.columns and "NOM_VENDEDOR" in df.columns:
        # Columna de pedidos: ID_PEDIDO si existe, fallback a NRO_DOCUMENTO
        pedidos_col = (
            "ID_PEDIDO"
            if "ID_PEDIDO" in df.columns
            else ("NRO_DOCUMENTO" if "NRO_DOCUMENTO" in df.columns else None)
        )
        agg_kwargs = {
            "items": ("CAN_PEDIDO", "size"),
            "saldo": ("saldo", "sum") if "saldo" in df else ("CAN_PEDIDO", "sum"),
            "valor": ("valor_saldo", "sum")
            if "valor_saldo" in df
            else ("PEDIDO_IMPORTE_ARITCULO", "sum"),
            "total_pedido": ("CAN_PEDIDO", "sum"),
            "total_despacho": ("CAN_DESPACHO", "sum"),
        }
        if pedidos_col:
            agg_kwargs["pedidos"] = (pedidos_col, "nunique")
        if "PEDIDO_ESTADO" in df.columns:
            agg_kwargs["aprobados"] = ("PEDIDO_ESTADO", lambda s: (s == "APROBADO").sum())
            agg_kwargs["ingresados"] = ("PEDIDO_ESTADO", lambda s: (s == "INGRESADO").sum())
        g = (
            df.groupby(["ID_VENDEDOR", "NOM_VENDEDOR"], dropna=False)
            .agg(**agg_kwargs)
            .reset_index()
        )
        if not pedidos_col:
            g["pedidos"] = 0
        if "PEDIDO_ESTADO" not in df.columns:
            g["aprobados"] = 0
            g["ingresados"] = 0
        g["por_atendido"] = (g["total_despacho"] / g["total_pedido"].replace(0, 1) * 100).round(1)
        for _, row in g.iterrows():
            ws.append(
                [
                    str(row["ID_VENDEDOR"]),
                    str(row["NOM_VENDEDOR"]),
                    int(row["items"]),
                    int(row["pedidos"]),
                    row["saldo"],
                    row["valor"],
                    f"{row['por_atendido']:.1f}%",
                    int(row["aprobados"]),
                    int(row["ingresados"]),
                ]
            )
    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja POR_VENDEDOR
# ---------------------------------------------------------------
def _write_por_vendedor(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("POR_VENDEDOR")
    headers = ["ID_VENDEDOR", "NOM_VENDEDOR", "Items", "Pedido", "Saldo", "Cajas", "Valor S/"]
    ws.append(headers)
    _style_header(ws, len(headers))
    if "ID_VENDEDOR" in df.columns and "NOM_VENDEDOR" in df.columns:
        g = (
            df.groupby(["ID_VENDEDOR", "NOM_VENDEDOR"], dropna=False)
            .agg(
                items=("CAN_PEDIDO", "size"),
                pedido=("CAN_PEDIDO", "sum"),
                saldo=("saldo", "sum"),
                cajas=("cajas", "sum"),
                valor=("valor_saldo", "sum"),
            )
            .reset_index()
        )
        for _, row in g.iterrows():
            ws.append(
                [
                    str(row["ID_VENDEDOR"]),
                    str(row["NOM_VENDEDOR"]),
                    int(row["items"]),
                    row["pedido"],
                    row["saldo"],
                    row["cajas"],
                    row["valor"],
                ]
            )
    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja POR_PRODUCTO
# ---------------------------------------------------------------
def _write_por_producto(wb: Workbook, df: pd.DataFrame) -> None:
    """Hoja con saldo agrupado por SKU/producto y cobertura de stock."""
    ws = wb.create_sheet("POR_PRODUCTO")
    headers = [
        "SKU",
        "NOM_ARTICULO",
        "Categoria",
        "Estado_Linea",
        "Lineas",
        "Pedido",
        "Despachado",
        "Saldo",
        "Cajas",
        "Valor S/",
        "% Atendido",
    ]
    has_stock = "stock_api_disponible" in df.columns
    if has_stock:
        headers.append("Stock_Disponible")
        headers.append("Cobertura")
    ws.append(headers)
    _style_header(ws, len(headers))

    if "SKU" in df.columns or "ID_ARTICULO" in df.columns:
        sku_col = "SKU" if "SKU" in df.columns else "ID_ARTICULO"
        nom_col = "NOM_ARTICULO" if "NOM_ARTICULO" in df.columns else "nombre_catalogo"
        cat_col = "categoria" if "categoria" in df.columns else None
        est_col = "estado_linea" if "estado_linea" in df.columns else None

        group_cols = [sku_col]
        if nom_col in df.columns:
            group_cols.append(nom_col)

        agg = {"Lineas": ("CAN_PEDIDO", "size")}
        if cat_col and cat_col in df.columns:
            agg["Categoria"] = (cat_col, "first")
        if est_col and est_col in df.columns:
            agg["Estado_Linea"] = (est_col, "first")
        agg["Pedido"] = ("CAN_PEDIDO", "sum")
        agg["Despachado"] = ("CAN_DESPACHO", "sum")
        agg["Saldo"] = ("saldo", "sum")
        agg["Cajas"] = ("cajas", "sum")
        agg["Valor S/"] = ("valor_saldo", "sum")

        prods = df.groupby(group_cols, dropna=False).agg(**agg).reset_index()
        prods["% Atendido"] = (prods["Despachado"] / prods["Pedido"].replace(0, 1) * 100).round(1)

        if has_stock:
            stock_map = {}
            for sku, grp in df.groupby(sku_col):
                stock_val = grp["stock_api_disponible"].iloc[0]
                if isinstance(stock_val, dict):
                    stock_map[sku] = sum(stock_val.values())
                else:
                    stock_map[sku] = 0
            prods["Stock_Disponible"] = prods[sku_col].map(stock_map).fillna(0).astype(int)
            prods["Cobertura"] = prods.apply(
                lambda r: (
                    "Cubierto"
                    if r["Stock_Disponible"] >= r["Saldo"]
                    else ("Parcial" if r["Stock_Disponible"] > 0 else "Sin Stock")
                ),
                axis=1,
            )

        prods = prods.sort_values("Saldo", ascending=False).reset_index(drop=True)

        for _, row in prods.iterrows():
            values = [
                str(row.get(sku_col, "")),
                str(row.get(nom_col, "")) if nom_col in df.columns else "",
                str(row.get("Categoria", "")),
                str(row.get("Estado_Linea", "")),
                int(row.get("Lineas", 0)),
                row.get("Pedido", 0),
                row.get("Despachado", 0),
                row.get("Saldo", 0),
                row.get("Cajas", 0),
                row.get("Valor S/", 0),
                row.get("% Atendido", 0),
            ]
            if has_stock:
                values.append(int(row.get("Stock_Disponible", 0)))
                values.append(str(row.get("Cobertura", "")))
            ws.append(values)

    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja STOCK_DESPACHO
# ---------------------------------------------------------------
def _write_stock_despacho(wb: Workbook, df: pd.DataFrame) -> None:
    """Hoja resumen: pedido completo vs despachado vs disponible para enviar."""
    ws = wb.create_sheet("STOCK_DESPACHO")

    kpis = _global_kpis(df)

    # Resumen general
    ws["A1"] = "Concepto"
    ws["B1"] = "Valor"
    _style_header(ws, 2)

    resumen_rows = [
        ("Total Pedido (completo)", kpis["total_pedido"]),
        ("Total Despachado", kpis["total_despachado"]),
        ("Saldo Pendiente (debemos)", kpis["saldo_total"]),
        ("% Despacho", round(kpis["total_despachado"] / max(kpis["total_pedido"], 1) * 100, 1)),
        ("% Pendiente", round(kpis["saldo_total"] / max(kpis["total_pedido"], 1) * 100, 1)),
    ]
    r = 2
    for label, value in resumen_rows:
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=value)
        r += 1

    # Stock disponible (API o calculado)
    has_stock = "stock_api_disponible" in df.columns or "stock_real" in df.columns
    if has_stock:
        r += 1
        ws.cell(row=r, column=1, value="Concepto Stock")
        ws.cell(row=r, column=2, value="Valor")
        _style_header(ws, 2)
        r += 1

        stock_total = 0
        unidades_envio = 0
        faltante = 0
        skus_con_stock = 0
        skus_sin_stock = 0

        sku_col = "SKU" if "SKU" in df.columns else "ID_ARTICULO"
        if "stock_api_disponible" in df.columns:
            for sku, grp in df.groupby(sku_col) if sku_col in df.columns else []:
                stock_val = grp["stock_api_disponible"].iloc[0]
                if isinstance(stock_val, dict):
                    s = sum(stock_val.values())
                else:
                    s = float(stock_val) if pd.notna(stock_val) else 0
                stock_total += s
                saldo_sku = grp["saldo"].sum()
                unidades_envio += min(s, saldo_sku) if s > 0 else 0
                if s > 0:
                    skus_con_stock += 1
                else:
                    skus_sin_stock += 1
        elif "stock_real" in df.columns and sku_col in df.columns:
            for sku, grp in df.groupby(sku_col):
                s = grp["stock_real"].sum()
                stock_total += s
                saldo_sku = grp["saldo"].sum()
                unidades_envio += min(s, saldo_sku) if s > 0 else 0
                if s > 0:
                    skus_con_stock += 1
                else:
                    skus_sin_stock += 1
        faltante = max(kpis["saldo_total"] - unidades_envio, 0)

        stock_rows = [
            ("Stock Total Disponible", stock_total),
            ("Unidades podemos enviar", unidades_envio),
            ("Falta producir/comprar", faltante),
            ("SKUs con Stock", skus_con_stock),
            ("SKUs sin Stock", skus_sin_stock),
        ]
        for label, value in stock_rows:
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=value)
            r += 1

    # Desglose por almacen
    r += 1
    alm_col = "NOM_ALMACEN" if "NOM_ALMACEN" in df.columns else None
    if alm_col:
        ws.cell(row=r, column=1, value="Almacen")
        ws.cell(row=r, column=2, value="Items")
        ws.cell(row=r, column=3, value="Pedido")
        ws.cell(row=r, column=4, value="Saldo")
        ws.cell(row=r, column=5, value="Cajas")
        ws.cell(row=r, column=6, value="Valor S/")
        _style_header(ws, 6)
        r += 1

        by_alm = (
            df.groupby(alm_col, dropna=False)
            .agg(
                Items=("CAN_PEDIDO", "size"),
                Pedido=("CAN_PEDIDO", "sum"),
                Saldo=("saldo", "sum"),
                Cajas=("cajas", "sum"),
                Valor=("valor_saldo", "sum"),
            )
            .reset_index()
            .sort_values("Valor", ascending=False)
        )
        for _, row in by_alm.iterrows():
            ws.cell(row=r, column=1, value=str(row[alm_col]))
            ws.cell(row=r, column=2, value=int(row["Items"]))
            ws.cell(row=r, column=3, value=row["Pedido"])
            ws.cell(row=r, column=4, value=row["Saldo"])
            ws.cell(row=r, column=5, value=row["Cajas"])
            ws.cell(row=r, column=6, value=row["Valor"])
            r += 1

    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja DETALLE (con formulas Excel)
# ---------------------------------------------------------------
def _write_detalle(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("DETALLE")

    # Columnas de origen que se exportan como datos crudos
    raw_cols = [
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "ID_ARTICULO",
        "NOM_ARTICULO",
        "linea",
        "categoria",
        "estado_linea",
        "NOM_ALMACEN",
        "CONDICION_PAGO",
        "PEDIDO_ESTADO",
        "ID_PLANILLA_ANTICIPO",
        "NOM_ESTADO_PLANILLA_ANTICIPO",
        "un_bx",
        "PRE_ARTICULO",
        "PEDIDO_IMPORTE_ARITCULO",
    ]
    raw_cols = [c for c in raw_cols if c in df.columns]

    headers = raw_cols + [
        "CAN_PEDIDO",
        "CAN_DESPACHO",
        "saldo",
        "por_atendido",
        "cajas",
        "valor_saldo",
        "es_linea_valida",
        "es_prototipo",
        "val_atencion",
        "val_pendiente",
    ]
    ws.append(headers)
    n_raw = len(raw_cols)

    # Indices de columnas (1-based) dentro de la hoja
    d = n_raw + 1  # CAN_PEDIDO
    e = n_raw + 2  # CAN_DESPACHO
    f = n_raw + 3  # saldo
    g = n_raw + 4  # por_atendido
    h = n_raw + 5  # cajas
    i = n_raw + 6  # valor_saldo

    # Indice de un_bx y PRE_ARTICULO dentro de raw_cols
    ubx_col = raw_cols.index("un_bx") + 1 if "un_bx" in raw_cols else None
    precio_col = raw_cols.index("PRE_ARTICULO") + 1 if "PRE_ARTICULO" in raw_cols else None

    for _, row in df.iterrows():
        values = [str(row.get(c, "") if row.get(c) is not None else "") for c in raw_cols]
        pedido = float(row.get("CAN_PEDIDO", 0) or 0)
        despacho = float(row.get("CAN_DESPACHO", 0) or 0)
        values += [
            pedido,
            despacho,
            "",
            "",
            "",
            "",
            bool(row.get("es_linea_valida", False)),
            bool(row.get("es_prototipo", False)),
            float(row.get("val_atencion", 0) or 0),
            float(row.get("val_pendiente", 0) or 0),
        ]
        ws.append(values)

        r = ws.max_row
        # Letras de columnas reales en la hoja
        col_pedido = get_column_letter(d)  # CAN_PEDIDO
        col_despacho = get_column_letter(e)  # CAN_DESPACHO
        col_saldo = get_column_letter(f)  # saldo
        # Formulas Excel para campos calculados (modificables por el usuario)
        # saldo = CAN_PEDIDO - CAN_DESPACHO
        ws.cell(row=r, column=f, value=f"={col_pedido}{r}-{col_despacho}{r}")
        # por_atendido = CAN_DESPACHO / CAN_PEDIDO * 100
        ws.cell(
            row=r, column=g, value=f"=IF({col_pedido}{r}=0,0,{col_despacho}{r}/{col_pedido}{r}*100)"
        )
        # cajas = saldo / un_bx
        if ubx_col:
            ubx_letter = get_column_letter(ubx_col)
            ws.cell(
                row=r, column=h, value=f"=IF({ubx_letter}{r}=0,0,{col_saldo}{r}/{ubx_letter}{r})"
            )
        # valor_saldo = (saldo / CAN_PEDIDO) * PRE_ARTICULO
        if precio_col:
            precio_letter = get_column_letter(precio_col)
            ws.cell(
                row=r,
                column=i,
                value=f"=IF({col_pedido}{r}=0,0,{col_saldo}{r}/{col_pedido}{r}*{precio_letter}{r})",
            )

    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hoja ALERTAS_QC
# ---------------------------------------------------------------
def _write_alertas_qc(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("ALERTAS_QC")
    headers = ["SKU", "NOM_ARTICULO", "Categoria", "Saldo", "Cajas"]
    ws.append(headers)
    _style_header(ws, len(headers))
    if "NOM_ALMACEN" in df.columns and "saldo" in df.columns:
        ves = df[df["NOM_ALMACEN"].astype(str).str.upper().str.contains("VES", na=False)]
        alerts = ves[ves["saldo"] > _QC_THRESHOLD].sort_values("saldo", ascending=False)
        # Usar ID_ARTICULO si SKU no existe
        sku_col = "SKU" if "SKU" in df.columns else "ID_ARTICULO"
        alerts = alerts.drop_duplicates(subset=[sku_col]).head(1000)
        for _, row in alerts.iterrows():
            ws.append(
                [
                    str(row.get(sku_col, "")),
                    str(row.get("NOM_ARTICULO", "")),
                    str(row.get("categoria", "")),
                    row.get("saldo", 0),
                    row.get("cajas", 0),
                ]
            )
    ws.freeze_panes = "A2"
    _auto_width(ws)


# ---------------------------------------------------------------
# Hojas individuales por vendedor
# ---------------------------------------------------------------
def _write_hojas_por_vendedor(wb: Workbook, df: pd.DataFrame) -> None:
    """Crea una hoja por cada vendedor con su detalle completo."""
    if "ID_VENDEDOR" not in df.columns:
        return

    # Columnas a incluir por vendedor
    cols = [
        "ID_PEDIDO",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_ARTICULO",
        "NOM_ARTICULO",
        "CAN_PEDIDO",
        "CAN_DESPACHO",
        "saldo",
        "PEDIDO_IMPORTE_ARITCULO",
        "PEDIDO_ESTADO",
        "CONDICION_PAGO",
        "NOM_ALMACEN",
    ]
    cols = [c for c in cols if c in df.columns]

    # Top vendedores por saldo (limitar a 20 para no crear demasiadas hojas)
    if "saldo" not in df:
        df["saldo"] = df["CAN_PEDIDO"] - df["CAN_DESPACHO"]

    top_vendedores = (
        df.groupby("ID_VENDEDOR")["saldo"].sum().sort_values(ascending=False).head(20).index
    )

    for vend_id in top_vendedores:
        vend_df = df[df["ID_VENDEDOR"] == vend_id]
        nom_vend = (
            vend_df["NOM_VENDEDOR"].iloc[0][:20] if "NOM_VENDEDOR" in vend_df else str(vend_id)
        )

        # Nombre de hoja (max 31 chars para Excel)
        sheet_name = f"{vend_id}_{nom_vend}"[:31]
        ws = wb.create_sheet(sheet_name)

        # Headers
        headers = [c for c in cols]
        ws.append(headers)
        _style_header(ws, len(headers))

        # Filas
        for _, row in vend_df.iterrows():
            ws.append(
                [
                    str(row.get(c, ""))
                    if not isinstance(row.get(c), (int, float))
                    else row.get(c, 0)
                    for c in cols
                ]
            )

        ws.freeze_panes = "A2"
        _auto_width(ws)


# ---------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------
def _global_kpis(df: pd.DataFrame) -> dict:
    pedido = float(df["CAN_PEDIDO"].sum()) if "CAN_PEDIDO" in df else 0.0
    despacho = float(df["CAN_DESPACHO"].sum()) if "CAN_DESPACHO" in df else 0.0
    saldo = float(df["saldo"].sum()) if "saldo" in df else pedido - despacho
    return {
        "total_items": len(df),
        "total_pedido": round(pedido, 2),
        "total_despachado": round(despacho, 2),
        "saldo_total": round(saldo, 2),
        "cajas_total": round(float(df["cajas"].sum()), 2) if "cajas" in df else None,
        "valor_total": round(float(df["valor_saldo"].sum()), 2) if "valor_saldo" in df else None,
        "n_clientes": int(df["COD_CLIENTE"].nunique()) if "COD_CLIENTE" in df else 0,
        "n_vendedores": int(df["ID_VENDEDOR"].nunique()) if "ID_VENDEDOR" in df else 0,
        "n_almacenes": int(df["NOM_ALMACEN"].nunique()) if "NOM_ALMACEN" in df else 0,
    }


# ---------------------------------------------------------------
# Reporte de acciones (reaccion rapida vendedor->cliente->pedido->SKU)
# ---------------------------------------------------------------
_QC_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_QC_AMBER = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
_QC_RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

_ESTADO_COLOR = {
    "ENTREGA_TOTAL": "C6EFCE",
    "PARCIAL": "FFEB9C",
    "TRASLADO": "FFEB9C",
    "OBSERVACION": "FFEB9C",
    "SIN_COBERTURA": "FFC7CE",
    "BLOQUEADO_ESTADO": "FFC7CE",
}
_PRIO_COLOR = {"P1": "C6EFCE", "P2": "E2EFDA", "P3": "FFEB9C", "P4": "FCE4D6", "P5": "FFC7CE"}
_CAMBIO_COLOR = {
    "ATENDIDO": "C6EFCE",
    "AVANCE": "E2EFDA",
    "NUEVO": "FFEB9C",
    "SIN_CAMBIO": "F2F2F2",
    "REGRESO": "FFC7CE",
}
# Alerta de sustituto (columna final del detalle por SKU).
_SUSTITUTO_COLOR = {
    "CERTEZA": "C6EFCE",
    "CURADO": "BDD7EE",
    "HOMOLOGO_DIRECTO": "FFEB9C",
    "MISMO_SEGMENTO": "FCE4D6",
    "REQUIERE_CRITERIO": "FFC7CE",
}
# Prioridad comercial (columna aparte; no toca P1-P5).
_PRIO_COMERCIAL_COLOR = {
    "1-ANTICIPO": "C6EFCE",
    "2-CANJE": "D9EAD3",
    "3-LETRA": "FFF2CC",
    "4-CONTADO": "F2F2F2",
    "5-FACTURA+OTRAS": "F2F2F2",
}
# Tramite pendiente (requiere).
_REQUIERE_COLOR = {
    "APROBAR_PEDIDO": "FFC7CE",
    "APROBAR_PLANILLA": "FCE4D6",
    "SOLICITAR_OC": "FFEB9C",
}


def _header_index(ws, name: str, fila: int = 1) -> int | None:
    """Indice 1-based de una columna por nombre de cabecera."""
    for cell in ws[fila]:
        if str(cell.value or "").strip().lower() == name.strip().lower():
            return cell.column
    return None


def _add_status_format(ws, max_row: int, desde: int = 2) -> None:
    """Formato condicional discreto por estado / prioridad / cambio."""
    if max_row < desde:
        return
    for col_name, mapping in (
        ("estado_accion", _ESTADO_COLOR),
        ("prio_sugerida", _PRIO_COLOR),
        ("cambio", _CAMBIO_COLOR),
        ("nivel_confianza", _SUSTITUTO_COLOR),
        ("prioridad_comercial_etq", _PRIO_COMERCIAL_COLOR),
        ("requiere", _REQUIERE_COLOR),
    ):
        col = _header_index(ws, col_name, fila=desde - 1)
        if not col:
            continue
        letter = get_column_letter(col)
        for value, color in mapping.items():
            ws.conditional_formatting.add(
                f"{letter}{desde}:{letter}{max_row}",
                FormulaRule(
                    formula=[f'${letter}{desde}="{value}"'],
                    fill=PatternFill(start_color=color, end_color=color, fill_type="solid"),
                ),
            )


def _finish_sheet(ws, max_row: int, fila_enc: int = 1) -> None:
    """Cierre comun: autofilter, formato numerico y formato de estado.

    `fila_enc` es la fila del encabezado (1 por defecto; 3 si la hoja tiene
    banda de titulo con `_abrir_hoja`).
    """
    if ws.max_row < fila_enc:
        return
    ncols = ws.max_column
    if ncols:
        ws.auto_filter.ref = f"A{fila_enc}:{get_column_letter(ncols)}{max(ws.max_row, fila_enc)}"
    _formatos_corporativos(ws, desde=fila_enc + 1, fila_enc=fila_enc)
    _add_status_format(ws, max(ws.max_row, fila_enc), desde=fila_enc + 1)


def export_reporte_acciones(
    df: pd.DataFrame,
    familia: str = "ANTICIPO",
    umbral: float = 1200.0,
    umbral_planilla: int = 10,
    stock_age_hours: float | None = None,
    snapshot_base: str | None = None,
    guardar_foto: bool = True,
    incluir_detalle: bool = False,
    detalle_solo_pendientes: bool = True,
    dias: int = 0,
    lineas: list[str] | None = None,
    categorias: list[str] | None = None,
    estados: list[str] | None = None,
    allowlist_rechazados: pd.DataFrame | None = None,
    allowlist_resumen: dict | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Reporte de acciones por familia de condicion de pago (9 hojas).

    1. LEEME         guia de lectura
    2. PANEL          cierre del dia: KPIs + bullets + ranking de vendedores
    3. POR_VENDEDOR   drill vendedor -> cliente -> pedido con subtotales
    4. PEDIDOS        tabla unica de pedidos (accionables + bloqueados)
    5. DESPACHO_HOY   lineas libres hoy (las que carga el camion)
    6. TRASLADO_121   guias 121 -> VES (una fila por SKU, reparto FIFO)
    7. COBRANZA       planillas de anticipo no aprobadas con dias
    8. SANEAMIENTO    sin cobertura + fuera del funnel + fuera de allowlist
    9. FOTO_DIA       comparacion contra la foto anterior (sin marcado manual)

    Recorte y segmentacion: `dias` acota por antiguedad del pedido y
    `lineas`/`categorias`/`estados` filtran antes del funnel (por eso se
    aplican al analitico y no a las hojas). `incluir_detalle` agrega la hoja
    de auditoria con formulas vivas.

    Filtro estricto de allowlist: las filas descartadas llegan en
    `allowlist_rechazados` y se reportan en SANEAMIENTO (tipo
    FUERA_DE_ALLOWLIST) para que el descarte sea auditable.
    `allowlist_resumen` alimenta el KPI del PANEL.

    Stock por SKU unico + FIFO: el reparto entre pedidos respeta antiguedad y
    nunca promete mas de lo que hay en VES ni en 121.
    """
    from src.core.analytics import PedidosAnalytics
    from src.core.photo import foto_del_dia
    from src.core.snapshot import SnapshotManager

    fam = str(familia or "ANTICIPO").strip().upper()
    output_path = Path(
        output_path or f"reaccion_{fam.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    wb = Workbook()
    # Bloques de lectura: A operacion hoy, B saneamiento semanal, C control.
    _BLOQUE_A = {
        "PEDIDOS",
        "POR_VENDEDOR",
        "AVANCE_PEDIDO",
        "POR_CLIENTE",
        "DETALLE_PEDIDO",
        "DESPACHO_HOY",
        "TRASLADO_121",
        "COBRANZA",
    }
    an = PedidosAnalytics(df)
    # Recorte por antiguedad y segmentacion antes del funnel (no solo hojas).
    if dias and dias > 0:
        an = an.filtrar_dias(dias)
    if lineas or categorias or estados:
        an = an.filtrar_segmento(lineas, categorias, estados)
    resumen = an.resumen_pedidos_familia(fam)
    entrega = an.get_val_atencion(fam)
    pendiente = an.get_val_pendiente(fam)

    # Foto del dia: se compara contra la foto guardada y se guarda la de hoy.
    try:
        from src.config.settings import DATA_DIR as _DATA_DIR

        snap = SnapshotManager(_DATA_DIR)
        base = snapshot_base or snap.latest_label()
        foto, foto_resumen = foto_del_dia(df, snap, base)
    except Exception:
        foto, foto_resumen = pd.DataFrame(), {"base": None}
    if guardar_foto:
        try:
            from src.config.settings import DATA_DIR as _DATA_DIR

            SnapshotManager(_DATA_DIR).save_snapshot(
                df, label=f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
        except Exception:
            pass

    pedidos = _pedidos_unificados(an, fam, umbral)
    despacho_hoy = _despacho_hoy(entrega, resumen, umbral)

    # Motor de sustitucion (EAN-first): llena sustituto_sugerido/nivel_confianza
    # SOLO en las filas descontinuadas. El manual (sustitutos.csv) pisa todo.
    try:
        from src.core.catalogo_productos import detectar_catalogo_productos
        from src.core.sustitutos import cargar_sustitutos_csv, enriquecer_con_sustitutos

        _cat_p = None
        try:
            from src.core.catalogo_productos import get_catalogo_productos

            _ruta_cat = detectar_catalogo_productos(Path.home() / "Desktop")
            if _ruta_cat:
                _cp = get_catalogo_productos(str(_ruta_cat))
                if _cp.cargar():
                    _cat_p = _cp.productos
        except Exception:
            _cat_p = None
        _cur = cargar_sustitutos_csv(Path(__file__).resolve().parents[2] / "sustitutos.csv")
        df = enriquecer_con_sustitutos(df, universo=df, productos=_cat_p, curados=_cur)
        # Propagar a los frames ya derivados (mismo orden de indice que df).
        for _frame in (entrega, pendiente):
            if _frame is not None and len(_frame) and "sustituto_sugerido" not in _frame.columns:
                cols = [
                    "sustituto_sugerido",
                    "nivel_confianza",
                    "score_sustituto",
                    "razon_sustituto",
                    "sustituto_origen",
                    "sustituto_stock",
                ]
                if "SKU" in _frame.columns and "SKU" in df.columns:
                    _map = df.drop_duplicates("SKU").set_index("SKU")
                    for c in cols:
                        if c in _map.columns:
                            _frame[c] = _frame["SKU"].map(_map[c])
    except Exception as _exc:  # noqa: BLE001
        print(f"[AVISO] Motor de sustitutos no disponible: {_exc}")

    _write_leeme(wb, fam, umbral)
    # KPI del filtro estricto: valor descartado + procedencia del maestro.
    _al_resumen = dict(allowlist_resumen or {})
    if allowlist_rechazados is not None and len(allowlist_rechazados):
        _al_resumen["valor_rechazado"] = round(
            float(
                pd.to_numeric(allowlist_rechazados.get("valor_saldo", 0), errors="coerce")
                .fillna(0)
                .sum()
            ),
            2,
        )
    try:
        from src.core.catalogo_unico import get_catalogo as _get_cat

        _cat = _get_cat()
        if _cat.cargar():
            _al_resumen["maestro"] = f"{_cat.origen} | allowlist {len(_cat.allowlist)} lineas"
    except Exception:
        pass
    _write_panel(
        wb,
        fam,
        df,
        resumen,
        despacho_hoy,
        pendiente,
        umbral,
        an,
        umbral_planilla,
        stock_age_hours,
        entrega,
        allowlist_resumen=_al_resumen or None,
        allowlist_rechazados=allowlist_rechazados,
    )
    _write_drill_vendedor(wb, an, fam, umbral)
    _write_pedidos(wb, pedidos)
    _write_avance_pedido(wb, an, fam)
    _write_por_cliente(wb, an, fam)
    _write_despacho_hoy(wb, fam, despacho_hoy, resumen, umbral)
    _write_traslado(wb, pendiente)
    _write_cobranza(wb, an, umbral_planilla)
    # EXCEPCIONES: revision manual + fuera de allowlist + colados.
    # Los "colados" son SKUs que aparecen en el embudo aceptado Y en el
    # rechazado: si el filtro de allowlist no es consistente, hay que
    # verlo explicito (no se pierde en silencio).
    _colados = _skus_colados(df, allowlist_rechazados)
    _write_excepciones(wb, df, allowlist_rechazados, _colados)
    _write_saneamiento(wb, pendiente, df, allowlist_rechazados)
    _write_ya_entregado(wb, df, fam)
    # DETALLE_PEDIDO: destino del hipervinculo (fila por SKU con su sustituto).
    _write_detalle_pedido(wb, df, fam)
    _write_foto_dia(wb, foto, foto_resumen)
    if incluir_detalle:
        if detalle_solo_pendientes:
            det = (
                df[pd.to_numeric(df.get("saldo", 0), errors="coerce").fillna(0) > 0]
                if "saldo" in df.columns
                else df
            )
        else:
            det = df
        _write_detalle(wb, det)

    _TAB_COLOR = {
        "LEEME": "0070C0",
        "PANEL": "808080",
        "FOTO_DIA": "808080",
        "DETALLE": "808080",
        "YA_ENTREGADO": "808080",
        "SANEAMIENTO": "FFC000",
        "EXCEPCIONES": "FF0000",
    }
    for ws in wb.worksheets:
        if ws.title in _BLOQUE_A:
            ws.sheet_properties.tabColor = "00B050"
        elif ws.title == "SANEAMIENTO":
            ws.sheet_properties.tabColor = "FFC000"
        elif ws.title in _TAB_COLOR:
            ws.sheet_properties.tabColor = _TAB_COLOR[ws.title]
    # Recalculo completo al abrir: las formulas de DETALLE se evaluan en Excel
    # (openpyxl no evalua; sin esto pueden verse ceros hasta recalc manual).
    try:
        wb.calculation.fullCalcOnLoad = True
    except Exception:
        pass

    wb.save(output_path)
    return output_path


def _leeme_rows(fam: str, umbral: float) -> list[tuple[str, str]]:
    """Filas de la portada LEEME (reutilizable para parchar reportes)."""
    return [
        (f"REPORTE DE ACCIONES - {fam} (umbral S/ {umbral:,.0f})", ""),
        ("", ""),
        ("COMO SE LEE (5 minutos)", ""),
        (
            "1. PANEL",
            "El cierre del dia. LAS TRES MEDIDAS DE LA DEUDA (no se confunden): "
            "1) Saldo pendiente: lo que se debe segun la fuente de vigencias. "
            "2) Saldo fisicamente cubrible: lo que podria cubrirse con stock utilizable (VES + 121), antes de mirar autorizaciones. "
            "3) Saldo liberado: lo que ademas cumple cobertura VES y autorizacion (planilla + pedido aprobados). "
            "Ademas: desglose por estado de linea (Nuevo/Tradicional/Importado/Nacional), saldo sin estado (SKUs descontinuados o nuevos, ver EXCEPCIONES), cuanto se entrega hoy, cuanto esta condicionado a planilla, guias 121 y cobranza. Mas top 3 vendedores y quick wins.",
        ),
        (
            "2. POR_VENDEDOR",
            "Drill vendedor -> cliente -> pedido con subtotales (como la tabla dinamica del prototipo VBA). Ordena la carga de camiones por vendedor y su monto a despachar.",
        ),
        (
            "3. PEDIDOS",
            "Tabla unica de pedidos (accionables + bloqueados), ordenada por vendedor. Filtrar por estado_accion: ENTREGA_TOTAL / PARCIAL / TRASLADO / OBSERVACION / SIN_COBERTURA / BLOQUEADO_ESTADO. Llave: ID_PEDIDO (la OC viene vacia 63% de veces). Columnas de segmento: lineas / categorias / estados_linea (para filtrar sin partir el libro). "
            "PROXIMO AL CIERRE con numeros: skus_faltantes (cuantos SKU sin cubrir), unidades_faltantes (cuantas unidades) y detalle_faltantes (que SKU y cuantas unidades: '011262:60; 011861:11; ...'). Con un porcentaje solo no se puede actuar: hay que saber QUE falta.",
        ),
        (
            "4. AVANCE_PEDIDO",
            "Comparativa pedido vs entregado vs saldo, UNA FILA POR PEDIDO Y estado_linea. La columna pedido es un HIPERVINCULO: un clic y saltas a DETALLE_PEDIDO para ver que SKU se debe. Filtrar por pedido (bloques contiguos) o por pedido_raiz (agrupa C2185 y C2185A).",
        ),
        (
            "5. POR_CLIENTE",
            "Vendedor x cliente: pedido / entregado / saldo y el desglose por estado_linea (NUEVO / IMPORTADO / TRADICIONAL / NACIONAL). Para responder 'del vendedor 052, al cliente xxx, cuanto tradicional y cuanto nuevo le debemos'.",
        ),
        (
            "6. DETALLE_PEDIDO",
            "Una fila por SKU (destino del hipervinculo). La ULTIMA columna, nivel_confianza, es la alerta de sustituto: VERDE = mismo EAN (certeza), AMARILLO = homologo probable, NARANJA = mismo segmento, ROJO = requiere tu criterio. La columna sustituto_sugerido dice que poner en lugar del SKU.",
        ),
        (
            "7. DESPACHO_HOY",
            "Lista del camion: solo lineas libres (stock VES confirmado y planilla no bloqueante), ordenadas por rank_monto. Cada fila es un SKU a cargar con su cant_a_despachar, peso_kg (capacidad de furgon) y ean13 (picking).",
        ),
        (
            "8. TRASLADO_121",
            "Solicitud de traslado masivo 121 -> VES. La banda superior es el TOTAL SOLICITUD (unidades y soles); una fila por SKU con a_trasladar (nunca mas del stock 121), valor_traslado, pedidos_cerrar_100 y detalle_fifo (que pedido se lleva que parte, el mas antiguo primero). "
            "Columnas de numeros: saldo_total (lo que se debe), stock_ves (lo que hay en el almacen de venta), stock_121 (lo que hay en QC), cajas_121 (stock_121 / un_bx, el factor de empaque), a_trasladar (lo que se pide mover). "
            "alerta_121: TRASLADABLE (hasta 1 caja) | TRASLADABLE + OBSERVACION (mas de 1 caja: hay que contar fisico antes de firmar) | OBSERVACION (sobra stock en 121 y no hay faltante). Las filas con OBSERVACION van resaltadas.",
        ),
        (
            "9. COBRANZA",
            "Planillas ANTICIPO no aprobadas con dias (proxy: dias desde PEDIDO_FECHA; el ERP no trae fecha de planilla) y accion escalar/seguimiento.",
        ),
        (
            "10. EXCEPCIONES",
            "Saldos que requieren revision humana (nada se pierde). tipo=REVISION_MANUAL: SKU con saldo pero SIN linea o SIN categoria en el maestro; el saldo se conserva (la deuda es real) y se deriva a negociacion comercial. tipo=FUERA_DE_ALLOWLIST: SKU cuya linea no esta entre las 24 core; se reporta para auditar que ningun producto se este colando en el embudo. tipo=COLADO: SKU presente a la vez en el embudo aceptado y en el rechazado (fallo de integridad del filtro).",
        ),
        (
            "11. SANEAMIENTO",
            "tipo=SIN_COBERTURA: a producir/comprar. tipo=FUERA_DE_FUNNEL: causa (alta en maestro Render / linea sin codigo / codigo fuera de la lista valida). tipo=FUERA_DE_ALLOWLIST: descartado por el filtro estricto de lineas (con unidades y valor).",
        ),
        (
            "12. YA_ENTREGADO",
            "Pedidos cerrados (saldo 0). No hacen ruido en las hojas de accion pero NO se descartan: quedan aqui para consulta (cuanto se entrego, cuando, a quien).",
        ),
        (
            "13. FOTO_DIA",
            "Foto de HOY contra la foto anterior: pedidos atendidos, con avance, nuevos y retrocesos. El avance se mide solo, sin marcar nada.",
        ),
        (
            "DETALLE (opcional)",
            "Auditoria fila por fila con formulas vivas. Se genera solo con incluir_detalle=True.",
        ),
        ("", ""),
        ("PRIORIDAD COMERCIAL Y TRAMITES", ""),
        (
            "Orden comercial",
            "prioridad_comercial (columna aparte; NO toca la escala P1-P5, que "
            "sigue midiendo cobertura de stock): 1-ANTICIPO -> 2-CANJE -> "
            "3-LETRA -> 4-CONTADO -> 5-FACTURA+OTRAS. Filtrar/ordenar por ella.",
        ),
        (
            "requiere (tramite)",
            "Que le falta al pedido para poder enviarse: APROBAR_PEDIDO (esta "
            "INGRESADO, no APROBADO), APROBAR_PLANILLA (anticipo con planilla "
            "INGRESADO) o SOLICITAR_OC (falta la orden de compra: aviso, NO "
            "bloquea). Vacio = listo para enviar.",
        ),
        (
            "Planilla por condicion",
            "Solo ANTICIPO trae planilla en el ERP. En CANJE / LETRA / CONTADO / "
            "FACTURA el campo viene vacio y NO se interpreta como bloqueo: no "
            "requieren planilla. Antes se asumia; ahora es explicito.",
        ),
        (
            "tiene_oc",
            "SI/NO segun PEDIDO_ORD_COMPRA. Falta en ~63% de los pedidos; por eso "
            "es un aviso y no un bloqueo del despacho.",
        ),
        (
            "pedido_raiz / es_complemento",
            "pedido_raiz agrupa el pedido base y su complemento (A1308 y A1308A -> "
            "A1308; C2185 y C2185A -> C2185). es_complemento=SI marca el sufijo.",
        ),
        ("", ""),
        ("SUSTITUTOS (alerta por SKU)", ""),
        (
            "Donde",
            "En DETALLE_PEDIDO y DESPACHO_HOY, como columnas al final: "
            "sustituto_sugerido, nivel_confianza, score_sustituto, "
            "razon_sustituto, sustituto_origen, sustituto_stock.",
        ),
        (
            "Niveles",
            "CERTEZA (mismo EAN: dato duro), HOMOLOGO_DIRECTO (probable), "
            "MISMO_SEGMENTO (mismo linea+grupo+caja), REQUIERE_CRITERIO (sin "
            "candidato: decidir a mano), CURADO (sustitutos.csv manual, pisa todo).",
        ),
        (
            "Curar a mano",
            "Crea sustitutos.csv junto al proyecto con las columnas "
            "sku_origen,sku_reemplazo,motivo,aprobado_por. Solo hace falta curar "
            "los REQUIERE_CRITERIO: el EAN ya resuelve los casos de version.",
        ),
        ("", ""),
        ("FILTRO ESTRICTO DE LINEAS (ALLOWLIST)", ""),
        (
            "Regla",
            "Solo pasa al embudo lo que pertenece a una linea autorizada (24 lineas core). La linea manda: si resuelve a un codigo no autorizado se descarta, y una linea vacia tambien. El grupo NO rescata.",
        ),
        (
            "Que se descarta",
            "Lineas industriales, CIPTECH, materia prima, economato y demas no autorizadas. Todo lo descartado queda en SANEAMIENTO (tipo=FUERA_DE_ALLOWLIST) con unidades y valor: nada se pierde en silencio.",
        ),
        (
            "De donde sale la allowlist",
            "Del catalogo unico (cartucho de la DB de ventas). Se puede sobrescribir con --allowlist (archivo .json o lista 01,02,MA) o desactivar con --sin-allowlist.",
        ),
        (
            "Los dos estados",
            "estado_linea = estado de la LINEA de producto (NUEVO / IMPORTADO / "
            "TRADICIONAL / NACIONAL, guia ERP SKU_BX). estado_pedido = estado del "
            "PEDIDO (APROBADO / INGRESADO). No son lo mismo: INGRESADO en un "
            "pedido lo bloquea; INGRESADO en una planilla la deja pendiente de "
            "aprobar (COBRANZA).",
        ),
        (
            "Estados de linea",
            "Solo 4 valores: NUEVO, IMPORTADO, TRADICIONAL y NACIONAL (guia ERP SKU_BX). "
            "Si el maestro no define el estado, queda vacio: el GRUPO del producto "
            "(TAJADORES, RESALTADORES...) no es un estado. El valor original queda en "
            "estado_linea_raw y el PANEL informa de los que se limpiaron.",
        ),
        (
            "Precio unitario",
            "Sale del reporte de vigencias (definitivo): PRE_ARTICULO / VIGENCIA. "
            "El precio del catalogo (API) es referencial (precio de lista) y no se "
            "cruza con este dato. El PANEL controla que el importe cumpla "
            "importe = (PRE_ARTICULO/VIGENCIA) x CAN_PEDIDO.",
        ),
        (
            "Maestro de referencia",
            "Catalogo unico importado del cartucho (foto estatica de la DB): lineas, articulos, vendedores y clientes de los ultimos 5 anos. Se usa para resolver lineas por nombre o por codigo y para validar maestros. El stock y la descripcion los manda Render.",
        ),
        ("", ""),
        ("SIN MARCADO MANUAL", ""),
        (
            "Como se sigue",
            "Cada corrida guarda la foto del dia en .cache/snapshots y el siguiente reporte la compara. No hay que rellenar ni marcar columnas.",
        ),
        (
            "Prioridad y acciones",
            "prio_sugerida / accion_1 / accion_2 las calcula el sistema a partir del stock, la planilla y la vigencia.",
        ),
        ("", ""),
        ("COMO SE ORDENA LA PRIORIDAD", ""),
        (
            "Regla",
            "Solo entra lo cubierto por VES (stock real despachable) con saldo>0, linea autorizada por la allowlist, condicion de la familia y pedido APROBADO.",
        ),
        (
            "P1..P5",
            "P1 despacho completo | P2 parcial de alto impacto | P3 completar por traslado 121 | P4 liberar comercial (planilla/estado) | P5 programar o acumular.",
        ),
        (
            "despachable_hoy vs si_se_aprueba",
            "despachable_hoy = valor sin bloqueo de planilla (sale hoy). si_se_aprueba = valor condicionado a aprobar la planilla. Ojo: en PEDIDOS, despachable_hoy suma tambien los pedidos OBSERVACION (bajo umbral), que no van en DESPACHO_HOY porque no justifican camion.",
        ),
        (
            "Orden",
            "Monto entregable desc (caja primero). pct_cant = cercania real al 100% a pedido completo. Desempate: pedido mas antiguo primero.",
        ),
        (
            "Stock",
            "El stock es por SKU unico y se asigna por antiguedad (FIFO): el pedido mas antiguo consume primero. No sumar VES ni 121 por filas.",
        ),
    ]


def _write_leeme(wb, fam: str, umbral: float) -> None:
    """Portada: como leer el reporte y en que orden actuar."""
    ws = wb.active
    ws.title = "LEEME"
    for a, b in _leeme_rows(fam, umbral):
        ws.append([a, b])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 110
    ws.freeze_panes = "A2"


def _pedidos_unificados(an, fam: str, umbral: float) -> pd.DataFrame:
    """Una sola tabla de pedidos: los de la familia + los bloqueados.

    Reemplaza a las hojas POR_PEDIDO + BLOQUEADOS + OBSERVACION: todo se
    filtra desde aca con estado_accion / familia / accion_1.
    """
    from src.core.analytics import normalize_cond_familia

    cols = [
        "familia",
        "estado_accion",
        "prio_sugerida",
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "CONDICION_PAGO",
        "estado_pedido",
        "PEDIDO_FECHA",
        "dias",
        "filas",
        "pedido",
        "despacho",
        "saldo",
        "pct_cant",
        "pct_cubierto",
        "lineas",
        "lineas_nombre",
        "categorias",
        "estado_linea",
        "casi_cierra",
        "despachable_hoy",
        "si_se_aprueba",
        "val_atencion",
        "val_pendiente",
        "trasladable",
        "skus_faltantes",
        "unidades_faltantes",
        "detalle_faltantes",
        "kg_hoy",
        "kg_saldo",
        "kg_cobertura",
        "precio_unitario",
        "peso_estimada",
        "producto_descontinuado",
        "accion_1",
        "accion_2",
    ]
    frames = []
    try:
        acc = an.resumen_accion_pedido(fam, umbral)
    except Exception:
        acc = pd.DataFrame()
    if not acc.empty:
        a = acc.copy()
        a["familia"] = fam
        frames.append(a)
    try:
        bloq = an.get_pedidos_bloqueados()
    except Exception:
        bloq = pd.DataFrame()
    if not bloq.empty:
        b = bloq.copy()
        if "familia" not in b.columns:
            b["familia"] = (
                b["CONDICION_PAGO"].map(normalize_cond_familia)
                if "CONDICION_PAGO" in b.columns
                else "OTRO"
            )
        frames.append(b)
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    # Nombres canonicos (los del maestro y la API del stock):
    # estado_linea (estado de la linea de producto) y estado_pedido
    # (estado del pedido). El frame conserva PEDIDO_ESTADO / estados_linea
    # porque son los nombres crudos del ERP y de la columna en la DB.
    if "PEDIDO_ESTADO" in out.columns:
        out["estado_pedido"] = out["PEDIDO_ESTADO"]
    if "estados_linea" in out.columns:
        out["estado_linea"] = out["estados_linea"]
    for c in cols:
        if c not in out.columns:
            out[c] = 0 if c in ("dias", "filas") else ""
    out = out[cols]
    order = {
        "ENTREGA_TOTAL": 0,
        "PARCIAL": 1,
        "TRASLADO": 2,
        "OBSERVACION": 3,
        "SIN_COBERTURA": 4,
        "BLOQUEADO_ESTADO": 5,
    }
    out["_ord"] = out["estado_accion"].map(order).fillna(9)
    out = out.sort_values(
        ["NOM_VENDEDOR", "_ord", "despachable_hoy", "val_atencion"],
        ascending=[True, True, False, False],
    ).drop(columns=["_ord"])
    return out.reset_index(drop=True)


def _despacho_hoy(entrega: pd.DataFrame, resumen: pd.DataFrame, umbral: float) -> pd.DataFrame:
    """Solo las lineas realmente libres hoy (planilla no bloquea)."""
    if entrega is None or entrega.empty:
        return entrega if entrega is not None else pd.DataFrame()
    ok_peds = set()
    if not resumen.empty and "ID_PEDIDO" in resumen.columns and "val_atencion" in resumen.columns:
        ok_peds = set(
            resumen.loc[
                pd.to_numeric(resumen["val_atencion"], errors="coerce").fillna(0) >= umbral,
                "ID_PEDIDO",
            ].astype(str)
        )
    sub = entrega[entrega["ID_PEDIDO"].astype(str).isin(ok_peds)] if ok_peds else entrega.iloc[0:0]
    if "NOM_ESTADO_PLANILLA_ANTICIPO" in sub.columns:
        pl = sub["NOM_ESTADO_PLANILLA_ANTICIPO"].astype(str).str.strip().str.upper()
        sub = sub[pl.ne("INGRESADO")]
    return sub.reset_index(drop=True)


def _write_pedidos(wb, pedidos: pd.DataFrame) -> None:
    """Tabla unica de pedidos (accionables + bloqueados), orden por vendedor."""
    headers = [
        "estado_accion",
        "prio_sugerida",
        "familia",
        "NOM_VENDEDOR",
        "ID_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "CONDICION_PAGO",
        "estado_pedido",
        "PEDIDO_FECHA",
        "dias",
        "lineas",
        "lineas_nombre",
        "categorias",
        "estado_linea",
        "filas",
        "pct_cubierto",
        "casi_cierra",
        "skus_faltantes",
        "unidades_faltantes",
        "detalle_faltantes",
        "despachable_hoy",
        "si_se_aprueba",
        "kg_hoy",
        "kg_saldo",
        "kg_cobertura",
        "precio_unitario",
        "peso_estimada",
        "producto_descontinuado",
        "trasladable",
        "accion_1",
        "accion_2",
    ]
    ws = _abrir_hoja(
        wb,
        "PEDIDOS",
        "PEDIDOS  ·  tabla unica de accion",
        "Ordenado por vendedor y luego por accion y monto. Filtrar por estado_accion / "
        "lineas / categorias / estados_linea / casi_cierra. Llave: ID_PEDIDO.",
        headers,
    )

    def _num(v, default=0.0):
        try:
            f = float(v)
            return default if pd.isna(f) else f
        except (TypeError, ValueError):
            return default

    if not pedidos.empty:
        for _, r in pedidos.iterrows():
            ws.append(
                [
                    str(r.get("estado_accion", "")),
                    str(r.get("prio_sugerida", "")),
                    str(r.get("familia", "")),
                    str(r.get("NOM_VENDEDOR", "")),
                    str(r.get("ID_VENDEDOR", "")),
                    str(r.get("COD_CLIENTE", "")),
                    str(r.get("NOM_CLIENTE", "")),
                    str(r.get("ID_PEDIDO", "")),
                    str(r.get("NRO_DOCUMENTO", "")),
                    str(r.get("CONDICION_PAGO", "")),
                    str(r.get("estado_pedido", r.get("PEDIDO_ESTADO", ""))),
                    str(r.get("PEDIDO_FECHA", "")),
                    int(_num(r.get("dias", 0))),
                    str(r.get("lineas", "")),
                    str(r.get("lineas_nombre", "")),
                    str(r.get("categorias", "")),
                    str(r.get("estado_linea", r.get("estados_linea", ""))),
                    int(_num(r.get("filas", 0))),
                    _num(r.get("pct_cubierto", 0)),
                    "SI" if bool(r.get("casi_cierra", False)) else "NO",
                    int(_num(r.get("skus_faltantes", 0))),
                    _num(r.get("unidades_faltantes", 0)),
                    str(r.get("detalle_faltantes", "")),
                    _num(r.get("despachable_hoy", 0)),
                    _num(r.get("si_se_aprueba", 0)),
                    _num(r.get("kg_hoy", 0)),
                    _num(r.get("kg_saldo", 0)),
                    _num(r.get("kg_cobertura", 0)),
                    _num(r.get("precio_unitario", 0)),
                    "SI" if bool(r.get("peso_estimada", False)) else "NO",
                    "SI" if bool(r.get("producto_descontinuado", False)) else "NO",
                    _num(r.get("trasladable", 0)),
                    str(r.get("accion_1", "")),
                    str(r.get("accion_2", "")),
                ]
            )
    ws.freeze_panes = "A4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_drill_vendedor(wb, an, fam: str, umbral: float) -> None:
    """Drill vendedor -> cliente -> pedido con subtotales (prototipo VBA)."""
    headers = [
        "nivel",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "ID_PEDIDO",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "CONDICION_PAGO",
        "PEDIDO_ESTADO",
        "estado_accion",
        "prio_sugerida",
        "casi_cierra",
        "filas",
        "pct_cubierto",
        "monto_hoy",
        "monto_total",
        "kg_hoy",
        "accion_1",
    ]
    ws = _abrir_hoja(
        wb,
        "POR_VENDEDOR",
        f"POR VENDEDOR  ·  drill {fam}",
        "Vendedor -> cliente -> pedido con subtotales por vendedor (nivel=VENDEDOR). "
        "Ordena la salida de camiones por monto a despachar.",
        headers,
    )
    try:
        drill = an.get_por_vendedor(fam, umbral)
    except Exception:
        drill = pd.DataFrame()
    if not drill.empty:

        def _num(v, default=0.0):
            try:
                f = float(v)
                return default if pd.isna(f) else f
            except (TypeError, ValueError):
                return default

        for _, r in drill.iterrows():
            es_sub = str(r.get("nivel", "")) == "VENDEDOR"
            casi = r.get("casi_cierra", False)
            ws.append(
                [
                    "VENDEDOR" if es_sub else "PEDIDO",
                    str(r.get("ID_VENDEDOR", "")),
                    str(r.get("NOM_VENDEDOR", "")),
                    str(r.get("ID_PEDIDO", "")),
                    str(r.get("COD_CLIENTE", "")),
                    str(r.get("NOM_CLIENTE", "")),
                    str(r.get("CONDICION_PAGO", "")),
                    str(r.get("PEDIDO_ESTADO", "")),
                    str(r.get("estado_accion", "")),
                    str(r.get("prio_sugerida", "")),
                    str(casi) if es_sub else ("SI" if bool(casi) else ""),
                    int(_num(r.get("filas", 0))),
                    _num(r.get("pct_cubierto", 0)),
                    _num(r.get("monto_hoy", 0)),
                    _num(r.get("monto_total", 0)),
                    _num(r.get("kg_hoy", 0)),
                    str(r.get("accion_1", "")),
                ]
            )
            if es_sub:
                fila = ws.max_row
                for col in range(1, len(headers) + 1):
                    cell = ws.cell(row=fila, column=col)
                    cell.fill = _SUBTOTAL_FILL
                    cell.font = _SUBTOTAL_FONT
    ws.freeze_panes = "A4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _skus_colados(df: pd.DataFrame, rechazados=None) -> list[str]:
    """SKUs presentes TANTO en el embudo aceptado como en el rechazado.

    El filtro de allowlist debe ser una particion: un SKU no puede estar
    en los dos lados. Si aparece en ambos, el filtro no es consistente y
    hay que reportarlo (tipo=COLADO) en vez de dejarlo pasar en silencio.
    """
    if df is None or not len(df) or rechazados is None or not len(rechazados):
        return []
    sku_col = "SKU" if "SKU" in df.columns else "ID_ARTICULO"
    r_col = "SKU" if "SKU" in rechazados.columns else "ID_ARTICULO"
    if sku_col not in df.columns or r_col not in rechazados.columns:
        return []
    aceptados = set(df[sku_col].astype(str).str.strip())
    rechazados_set = set(rechazados[r_col].astype(str).str.strip())
    return sorted(aceptados & rechazados_set)


def _write_excepciones(wb, df: pd.DataFrame, rechazados=None, colados=None) -> None:
    """EXCEPCIONES: saldos que requieren revision humana (nada se pierde).

    Concentra en UNA hoja las tres excepciones que antes se dispersaban o
    no existian:

      REVISION_MANUAL    SKU con saldo pero SIN linea o SIN categoria: el
                         catalogo no lo reconoce. Se conserva el saldo
                         (la deuda es real) y se deriva a negociacion.
      FUERA_DE_ALLOWLIST SKU cuya linea no esta en la allowlist (24 lineas
                         core). Se reportan para auditar que ningun
                         producto se este colando en el embudo.
      COLADO             SKU que aparece TANTO en el embudo aceptado como
                         en el rechazado: el filtro no es consistente.
                         Es un fallo de integridad y se marca aparte.
    """
    headers = [
        "tipo",
        "motivo",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_PEDIDO",
        "SKU",
        "NOM_ARTICULO",
        "linea",
        "origen_linea",
        "categoria",
        "saldo",
        "valor",
        "pedidos",
    ]
    ws = _abrir_hoja(
        wb,
        "EXCEPCIONES",
        "EXCEPCIONES  ·  saldos que requieren revision humana",
        "tipo=REVISION_MANUAL: SKU con saldo pero sin linea o sin categoria (se "
        "conserva el saldo, no se descarta). tipo=FUERA_DE_ALLOWLIST: linea fuera "
        "de las 24 core (auditoria: ningun producto debe colarse). tipo=COLADO: "
        "SKU aceptado y rechazado a la vez (fallo de integridad del filtro).",
        headers,
    )
    if colados is not None and len(colados):
        for sku in sorted(set(colados)):
            ws.append(
                [
                    "COLADO",
                    "SKU presente en el embudo aceptado y en el rechazado: "
                    "el filtro de allowlist no es consistente",
                    "",
                    "",
                    "",
                    "",
                    "",
                    str(sku),
                    "",
                    "",
                    "",
                    "",
                    0.0,
                    0.0,
                    0,
                ]
            )
    if df is not None and len(df) and "saldo" in df.columns:
        off = df[pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0].copy()
        # REVISION_MANUAL: saldo real pero sin linea o sin categoria.
        # NO se filtra por `es_linea_valida`: un SKU sin linea tiene
        # es_linea_valida=False y se perderia de la revision manual.
        if not off.empty:
            _lin = off["linea"].astype(str).str.strip().str.upper()
            _cat = off["categoria"].astype(str).str.strip().str.upper()
            manual = off[
                _lin.isin(["", "NAN", "NONE"]) | _cat.isin(["", "NAN", "NONE"])
            ]
            if not manual.empty:
                sku_col = "SKU" if "SKU" in manual.columns else "ID_ARTICULO"
                for sku, grp in manual.groupby(sku_col, dropna=False):
                    first = grp.iloc[0]
                    _l = str(first.get("linea", "") or "").strip()
                    _c = str(first.get("categoria", "") or "").strip()
                    if _l.upper() in ("", "NAN", "NONE") and _c.upper() in ("", "NAN", "NONE"):
                        motivo = "Sin linea y sin categoria: completar maestro"
                    elif _l.upper() in ("", "NAN", "NONE"):
                        motivo = "Sin linea en el catalogo: completar maestro"
                    else:
                        motivo = f"Sin categoria (linea {_l}): completar maestro"
                    ws.append(
                        [
                            "REVISION_MANUAL",
                            motivo,
                            str(first.get("ID_VENDEDOR", "")),
                            str(first.get("NOM_VENDEDOR", "")),
                            str(first.get("COD_CLIENTE", "")),
                            str(first.get("NOM_CLIENTE", "")),
                            str(first.get("ID_PEDIDO", "")),
                            str(sku),
                            str(first.get("NOM_ARTICULO", first.get("nombre_catalogo", ""))),
                            _l if _l else "(SIN LINEA)",
                            str(first.get("origen_linea", "")),
                            _c if _c else "(SIN CATEGORIA)",
                            float(grp["saldo"].sum()),
                            float(
                                pd.to_numeric(
                                    grp.get("valor_saldo", 0), errors="coerce"
                                ).fillna(0).sum()
                            ),
                            int(grp["ID_PEDIDO"].nunique())
                            if "ID_PEDIDO" in grp.columns
                            else len(grp),
                        ]
                    )
    if rechazados is not None and len(rechazados):
        sku_col = "SKU" if "SKU" in rechazados.columns else "ID_ARTICULO"
        for sku, grp in rechazados.groupby(sku_col, dropna=False):
            first = grp.iloc[0]
            motivo = str(first.get("motivo_rechazo", "") or "FUERA_DE_ALLOWLIST")
            _lin = str(first.get("linea", "") or "")
            _sin_linea = _lin.strip().upper() in ("", "NAN", "NONE")
            if _sin_linea:
                _lin = "(SIN LINEA)"
            # Motivo LINEA_VACIA = el SKU no tiene linea: no es "fuera de la
            # allowlist" sino "sin clasificar" -> va a REVISION_MANUAL.
            _tipo = "REVISION_MANUAL" if _sin_linea else "FUERA_DE_ALLOWLIST"
            _motivo = (
                "SKU sin linea en el maestro: completar catalogo (deuda conservada)"
                if _sin_linea
                else motivo
            )
            ws.append(
                [
                    _tipo,
                    _motivo,
                    "",
                    "",
                    "",
                    "",
                    "",
                    str(sku),
                    str(first.get("NOM_ARTICULO", first.get("nombre_catalogo", ""))),
                    _lin,
                    str(first.get("origen_linea", "")),
                    str(first.get("categoria", "")),
                    float(pd.to_numeric(grp.get("saldo", 0), errors="coerce").fillna(0).sum()),
                    float(
                        pd.to_numeric(grp.get("valor_saldo", 0), errors="coerce").fillna(0).sum()
                    ),
                    int(grp["ID_PEDIDO"].nunique())
                    if "ID_PEDIDO" in grp.columns
                    else len(grp),
                ]
            )
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_saneamiento(wb, pendiente, df: pd.DataFrame, rechazados=None) -> None:
    """SANEAMIENTO: sin cobertura de stock + SKUs fuera del funnel (1 sola tabla).

    `rechazados` son las filas que el filtro estricto de allowlist dejo fuera
    del embudo: se reportan para que el descarte sea auditable.
    """
    headers = [
        "tipo",
        "motivo",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_PEDIDO",
        "SKU",
        "NOM_ARTICULO",
        "linea",
        "origen_linea",
        "categoria",
        "saldo",
        "valor",
        "pedidos",
    ]
    ws = _abrir_hoja(
        wb,
        "SANEAMIENTO",
        "SANEAMIENTO  ·  stock sin cobertura + SKUs fuera del funnel",
        "tipo=SIN_COBERTURA: a producir/comprar. tipo=FUERA_DE_FUNNEL: causa "
        "(alta en maestro Render / linea sin codigo / codigo fuera de la lista valida). "
        "tipo=FUERA_DE_ALLOWLIST: descartado por el filtro estricto de lineas.",
        headers,
    )
    if pendiente is not None and not pendiente.empty:
        sub = pendiente.copy()
        _ves = pd.to_numeric(
            sub.get("stock_real", sub.get("stock_api_ves", 0)), errors="coerce"
        ).fillna(0)
        _s121 = pd.to_numeric(sub.get("stock_api_121", 0), errors="coerce").fillna(0)
        sub = sub[(_ves <= 0).values & (_s121 <= 0).values]
        sku_col = "SKU" if "SKU" in sub.columns else "ID_ARTICULO"
        for _, row in sub.iterrows():
            ws.append(
                [
                    "SIN_COBERTURA",
                    "producir/comprar",
                    str(row.get("ID_VENDEDOR", "")),
                    str(row.get("NOM_VENDEDOR", "")),
                    str(row.get("COD_CLIENTE", "")),
                    str(row.get("NOM_CLIENTE", "")),
                    str(row.get("ID_PEDIDO", "")),
                    str(row.get(sku_col, "")),
                    str(row.get("NOM_ARTICULO", row.get("nombre_catalogo", ""))),
                    str(row.get("linea", "")),
                    str(row.get("origen_linea", "")),
                    str(row.get("categoria", "")),
                    float(row.get("saldo", 0) or 0),
                    float(row.get("val_pendiente", row.get("valor_saldo", 0)) or 0),
                    1,
                ]
            )
    if df is not None and len(df) and "saldo" in df.columns:
        off = df[pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0].copy()
        if "es_linea_valida" in off.columns:
            off = off[~off["es_linea_valida"].fillna(False).astype(bool)]
        if not off.empty:
            sku_col = "SKU" if "SKU" in off.columns else "ID_ARTICULO"
            for sku, grp in off.groupby(sku_col, dropna=False):
                first = grp.iloc[0]
                origen = str(first.get("origen_linea", "DESCONOCIDA") or "DESCONOCIDA")
                sin_api = (
                    bool(grp["sin_stock_api"].fillna(False).astype(bool).all())
                    if "sin_stock_api" in grp.columns
                    else False
                )
                if sin_api:
                    motivo = "Alta pendiente en maestro Render (SKU ausente)"
                elif origen == "DESCONOCIDA":
                    motivo = "Linea como nombre sin codigo/alias: definir alias"
                elif origen == "VACIA":
                    motivo = "SKU sin linea en catalogo: completar maestro"
                elif origen == "CODIGO":
                    motivo = "Codigo de linea fuera de la lista valida: decidir inclusion"
                else:
                    motivo = f"Origen {origen}: revisar"
                ws.append(
                    [
                        "FUERA_DE_FUNNEL",
                        motivo,
                        "",
                        "",
                        "",
                        "",
                        "",
                        str(sku),
                        str(first.get("NOM_ARTICULO", first.get("nombre_catalogo", ""))),
                        str(first.get("linea", "")),
                        origen,
                        str(first.get("categoria", "")),
                        float(grp["saldo"].sum()),
                        float(grp["valor_saldo"].sum()) if "valor_saldo" in grp else 0.0,
                        int(grp["ID_PEDIDO"].nunique()) if "ID_PEDIDO" in grp else len(grp),
                    ]
                )
    if rechazados is not None and len(rechazados):
        sku_col = "SKU" if "SKU" in rechazados.columns else "ID_ARTICULO"
        for sku, grp in rechazados.groupby(sku_col, dropna=False):
            first = grp.iloc[0]
            motivo = str(first.get("motivo_rechazo", "") or "FUERA_DE_ALLOWLIST")
            _lin = str(first.get("linea", "") or "")
            if _lin.strip().upper() in ("", "NAN", "NONE"):
                _lin = "(SIN LINEA)"
            ws.append(
                [
                    "FUERA_DE_ALLOWLIST",
                    motivo,
                    "",
                    "",
                    "",
                    "",
                    "",
                    str(sku),
                    str(first.get("NOM_ARTICULO", first.get("nombre_catalogo", ""))),
                    _lin,
                    str(first.get("origen_linea", "")),
                    str(first.get("categoria", "")),
                    float(pd.to_numeric(grp.get("saldo", 0), errors="coerce").fillna(0).sum()),
                    float(
                        pd.to_numeric(grp.get("valor_saldo", 0), errors="coerce").fillna(0).sum()
                    ),
                    int(grp["ID_PEDIDO"].nunique()) if "ID_PEDIDO" in grp.columns else len(grp),
                ]
            )
    if df is not None and len(df) and "producto_descontinuado" in df.columns:
        desc = df[df["producto_descontinuado"].fillna(False).astype(bool)].copy()
        if len(desc) and "saldo" in desc.columns:
            desc = desc[pd.to_numeric(desc["saldo"], errors="coerce").fillna(0) > 0]
        if len(desc):
            sku_col = "SKU" if "SKU" in desc.columns else "ID_ARTICULO"
            for sku, grp in desc.groupby(sku_col, dropna=False):
                first = grp.iloc[0]
                ws.append(
                    [
                        "DESCONTINUADO",
                        "renegociar o producir: el maestro ERP lo marca descontinuado",
                        "",
                        "",
                        "",
                        "",
                        "",
                        str(sku),
                        str(first.get("NOM_ARTICULO", first.get("nombre_catalogo", ""))),
                        str(first.get("linea", "")),
                        str(first.get("origen_linea", "")),
                        str(first.get("categoria", "")),
                        float(pd.to_numeric(grp["saldo"], errors="coerce").fillna(0).sum()),
                        float(
                            pd.to_numeric(grp.get("valor_saldo", 0), errors="coerce")
                            .fillna(0)
                            .sum()
                        ),
                        int(grp["ID_PEDIDO"].nunique()) if "ID_PEDIDO" in grp.columns else len(grp),
                    ]
                )
    ws.freeze_panes = "A4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_foto_dia(wb, foto: pd.DataFrame, resumen: dict) -> None:
    """Foto del dia: tabla primero (autofilter) y KPIs al final.

    Comparacion contra la foto anterior: el avance se mide solo, sin marcado
    manual. Si no hay foto previa, la hoja queda con el estado del dia.
    """
    ws = wb.create_sheet("FOTO_DIA")
    headers = [
        "cambio",
        "ID_PEDIDO",
        "NOM_VENDEDOR",
        "NOM_CLIENTE",
        "CONDICION_PAGO",
        "saldo_ayer",
        "saldo_hoy",
        "delta",
        "filas_hoy",
    ]
    ws.append(headers)
    _style_header(ws, len(headers))
    if not foto.empty:
        for _, row in foto.iterrows():
            ws.append(
                [
                    str(row.get("cambio", "")),
                    str(row.get("ID_PEDIDO", "")),
                    str(row.get("NOM_VENDEDOR", "")),
                    str(row.get("NOM_CLIENTE", "")),
                    str(row.get("CONDICION_PAGO", "")),
                    float(row.get("saldo_ayer", 0) or 0),
                    float(row.get("saldo_hoy", 0) or 0),
                    float(row.get("delta", 0) or 0),
                    int(row.get("filas_hoy", 0) or 0),
                ]
            )
    ws.freeze_panes = "A2"
    # KPIs a la derecha (K/L) para no romper la tabla ni su lectura por pandas
    kcol = 11
    ws.cell(
        row=1,
        column=kcol,
        value=f"FOTO DEL DIA vs {resumen['base']} ({resumen.get('dias')} dias)"
        if resumen.get("base")
        else "FOTO DEL DIA — sin foto previa (primera)",
    )
    ws.cell(row=2, column=kcol, value="KPI")
    ws.cell(row=2, column=kcol + 1, value="Valor")
    for cell in (ws.cell(row=2, column=kcol), ws.cell(row=2, column=kcol + 1)):
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
    r = 3
    kpis = [
        ("pedidos_hoy", "Pedidos hoy"),
        ("atendidos", "Pedidos ATENDIDOS (saldo 0)"),
        ("avance", "Pedidos con AVANCE"),
        ("nuevos", "Pedidos NUEVOS"),
        ("regresos", "Pedidos con REGRESO"),
        ("sin_cambio", "Sin cambio"),
        ("saldo_ayer", "Saldo pendiente ayer"),
        ("saldo_hoy", "Saldo pendiente hoy"),
        ("delta_total", "Delta (hoy - ayer)"),
        ("atendidos_valor", "Valor despachado (ATENDIDOS) S/"),
    ]
    for key, label in kpis:
        if resumen.get(key) is None:
            continue
        ws.cell(row=r, column=kcol, value=label)
        ws.cell(row=r, column=kcol + 1, value=resumen.get(key, 0))
        r += 1
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row)


def _write_cobranza(wb, an, umbral_dias) -> None:
    """Planillas ANTICIPO no aprobadas con dias (proxy PEDIDO_FECHA)."""
    headers = [
        "ID_PLANILLA",
        "ID_PEDIDO",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "PEDIDO_FECHA",
        "dias",
        "bucket",
        "filas",
        "saldo",
        "valor",
        "accion",
    ]
    ws = _abrir_hoja(
        wb,
        "COBRANZA",
        f"COBRANZA  ·  planillas no aprobadas (escalar >{umbral_dias} dias)",
        "Dias = proxy desde PEDIDO_FECHA (el ERP no trae fecha de planilla). "
        "accion: escalar a Creditos o seguimiento normal.",
        headers,
    )
    try:
        cob = an.resumen_cobranza(umbral_dias)
    except Exception:
        cob = pd.DataFrame()
    for _, r in cob.iterrows():
        ws.append(
            [
                str(r.get("ID_PLANILLA_ANTICIPO", "")),
                str(r.get("ID_PEDIDO", "")),
                str(r.get("ID_VENDEDOR", "")),
                str(r.get("NOM_VENDEDOR", "")),
                str(r.get("COD_CLIENTE", "")),
                str(r.get("NOM_CLIENTE", "")),
                str(r.get("PEDIDO_FECHA", "")),
                int(r.get("dias", 0) or 0),
                str(r.get("bucket", "")),
                int(r.get("filas", 0) or 0),
                float(r.get("saldo", 0) or 0),
                round(float(r.get("valor", 0) or 0), 2),
                str(r.get("accion", "")),
            ]
        )
    ws.freeze_panes = "A4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_panel(
    wb,
    fam,
    df,
    resumen,
    entrega,
    pendiente,
    umbral,
    an=None,
    umbral_planilla: int = 10,
    stock_age_hours: float | None = None,
    entrega_total=None,
    allowlist_resumen: dict | None = None,
    allowlist_rechazados=None,
) -> None:
    """PANEL: el cierre de hoy (KPIs + bullets + top 3) en una sola vista.

    `entrega` llega ya filtrada a lo despachable hoy (mismo criterio que la
    hoja DESPACHO_HOY) para que el panel y la lista no se contradigan.
    `entrega_total` es el conjunto cubierto por VES, usado solo para medir
    cuanto queda condicionado a la planilla.
    """
    ws = wb.create_sheet("PANEL")
    ws["A1"] = f"PANEL DEL DIA - {fam} (umbral S/ {umbral:,.0f})"
    # --- Cierre operativo (3 bullets automaticos) ---
    # Split planilla: libre hoy vs condicionado a aprobacion
    total = entrega_total if entrega_total is not None else entrega
    if "NOM_ESTADO_PLANILLA_ANTICIPO" in total.columns:
        _pl = total["NOM_ESTADO_PLANILLA_ANTICIPO"].astype(str).str.strip().str.upper()
        _blq = _pl.eq("INGRESADO")
    else:
        _blq = pd.Series(False, index=total.index)
    val_cond = float(total.loc[_blq, "val_atencion"].sum()) if "val_atencion" in total else 0.0
    n_cond = int(_blq.sum())
    # "Despacho inmediato" = lo que realmente sale hoy (libre de planilla)
    val_e = float(entrega["val_atencion"].sum()) if "val_atencion" in entrega else 0.0
    n_e = len(entrega)
    try:
        _s121 = pd.to_numeric(pendiente.get("stock_api_121", 0), errors="coerce").fillna(0)
        _ves = pd.to_numeric(
            pendiente.get("stock_real", pendiente.get("stock_api_ves", 0)),
            errors="coerce",
        ).fillna(0)
        _sal = pd.to_numeric(pendiente.get("saldo", 0), errors="coerce").fillna(0)
        _mask = _s121 > 0
        _trasladable = float(((_sal - _ves).clip(lower=0).where(_mask, 0)).sum())
        _n_tras = int(_mask.sum())
    except Exception:
        _trasladable, _n_tras = 0.0, 0
    try:
        _cob = an.resumen_cobranza(umbral_planilla) if an is not None else pd.DataFrame()
        _cob_n = len(_cob)
        _cob_v = round(float(_cob["valor"].sum()), 2) if not _cob.empty else 0.0
    except Exception:
        _cob_n, _cob_v = 0, 0.0
    ws["A2"] = "CIERRE OPERATIVO HOY"
    ws["B2"] = "Detalle"
    _style_header(ws, 2)
    # --- LAS TRES MEDIDAS DE LA DEUDA (no se confunden) ---
    # 1. Saldo PENDIENTE: lo que se debe segun la fuente de vigencias.
    # 2. Saldo FISICAMENTE CUBRIBLE: lo que podria cubrirse con stock
    #    utilizable (VES + 121), antes de mirar autorizaciones.
    # 3. Saldo LIBERADO: lo que además cumple condiciones administrativas.
    try:
        _pf = pendiente if pendiente is not None else df
        _und = _pf["saldo"].sum() if "saldo" in _pf.columns else 0.0
        _val = (
            _pf["valor_saldo"].sum() if "valor_saldo" in _pf.columns else 0.0
        )
        _ves_s = pd.to_numeric(
            _pf.get("stock_real", _pf.get("stock_api_ves", 0)), errors="coerce"
        ).fillna(0)
        _s121_s = pd.to_numeric(_pf.get("stock_api_121", 0), errors="coerce").fillna(0)
        _sal_s = pd.to_numeric(_pf.get("saldo", 0), errors="coerce").fillna(0)
        _cub_ves = _sal_s.clip(upper=_ves_s)
        _cub_121 = (_sal_s - _cub_ves).clip(lower=0).clip(upper=_s121_s)
        _und_cubrible = float(_cub_ves.sum() + _cub_121.sum())
        # Saldo LIBERADO: `val_atencion` ya exige cobertura en VES y planilla
        # aprobada (ver _recompute_relevance), asi que es el saldo despacho.
        _und_liberado = float(
            entrega["saldo"].sum() if "saldo" in entrega.columns else 0.0
        )
    except Exception:
        _und = _val = _und_cubrible = _und_liberado = 0.0
    cierre = [
        (
            f"Saldo pendiente: {_und:,.0f} und / S/ {_val:,.2f}",
            "total segun la fuente de vigencias (base conciliada)",
        ),
        (
            f"Saldo fisicamente cubrible: {_und_cubrible:,.0f} und",
            "VES + 121 con stock disponible (aun sin autorizacion)",
        ),
        (
            f"Saldo liberado para despacho: {_und_liberado:,.0f} und / S/ {val_e:,.2f}",
            "cumple cobertura VES y autorizacion (planilla+pedido aprobados)",
        ),
        (
            f"Despacho inmediato: S/ {val_e:,.2f} en {n_e} filas (ver DESPACHO_HOY)",
            f"{n_e} lineas libres con stock VES confirmado",
        ),
        (
            f"Condicionado a planilla: S/ {val_cond:,.2f} en {n_cond} filas (si_se_aprueba)",
            "liberar planillas en COBRANZA para despachar",
        ),
        (
            f"Liberar faltantes: {int(_trasladable):,} unds (solicitar guia 121→VES)",
            f"{_n_tras} filas con stock 121 (ver TRASLADO_121)",
        ),
        (
            f"Desbloqueo comercial: S/ {_cob_v:,.2f} en {_cob_n} planillas (ver COBRANZA)",
            f"aprobar/escalar >{umbral_planilla}d para liberar almacen",
        ),
    ]
    # Desglose del saldo pendiente por estado de linea (guia ERP):
    # Nuevo / Tradicional / Importado / Nacional + lo que no tiene estado
    # (SKU descontinuados o nuevos, que se reportan en EXCEPCIONES).
    try:
        _pf2 = pendiente if pendiente is not None else df
        if _pf2 is not None and len(_pf2) and "saldo" in _pf2.columns:
            _sal2 = pd.to_numeric(_pf2["saldo"], errors="coerce").fillna(0)
            _est2 = (
                _pf2["estado_linea"].astype(str).str.strip().str.upper()
                if "estado_linea" in _pf2.columns
                else pd.Series("", index=_pf2.index)
            )
            _pos2 = _sal2.clip(lower=0)
            for _e2 in ("NUEVO", "TRADICIONAL", "IMPORTADO", "NACIONAL"):
                _m2 = _est2.eq(_e2)
                _u2 = float(_pos2[_m2].sum())
                if _u2 <= 0:
                    continue
                _v2 = 0.0
                if "valor_saldo" in _pf2.columns:
                    _v2 = float(
                        pd.to_numeric(_pf2["valor_saldo"], errors="coerce")
                        .fillna(0)[_m2].sum()
                    )
                cierre.append(
                    (
                        f"Saldo {_e2.title()}: {_u2:,.0f} und / S/ {_v2:,.2f}",
                        "desglose por estado de linea (guia ERP SKU_BX)",
                    )
                )
            _sin2 = float(_pos2[_est2.isin(["", "NAN", "NONE"])].sum())
            if _sin2 > 0:
                cierre.append(
                    (
                        f"Saldo sin estado de linea: {_sin2:,.0f} und",
                        "SKUs descontinuados o nuevos: revisar en EXCEPCIONES",
                    )
                )
    except Exception:
        pass
    # --- CONCILIACION: ninguna cifra se pierde en silencio ---
    # Se compara el MISMO embudo en dos cortes:
    #   - el que ve el usuario (familia + linea valida + APROBADO)
    #   - la fuente completa (todo lo que trae el reporte de vigencias)
    # La diferencia es el saldo que queda FUERA del embudo: no es una
    # perdida silenciosa, es lo que se reporta en EXCEPCIONES.
    try:
        if df is not None and len(df) and "saldo" in df.columns:
            _sal_fuente = float(
                pd.to_numeric(df["saldo"], errors="coerce").fillna(0).clip(lower=0).sum()
            )
            _sal_embudo = 0.0
            if an is not None:
                try:
                    _emb = an.filtrar_familia(fam)
                    if "saldo" in _emb.columns:
                        _sal_embudo = float(
                            pd.to_numeric(_emb["saldo"], errors="coerce")
                            .fillna(0)
                            .clip(lower=0)
                            .sum()
                        )
                except Exception:
                    _sal_embudo = 0.0
            _fuera = max(_sal_fuente - _sal_embudo, 0.0)
            _n_fuera = 0
            if an is not None:
                try:
                    _emb2 = an.filtrar_familia(fam)
                    if "saldo" in _emb2.columns:
                        _n_fuera = int(
                            (
                                pd.to_numeric(_emb2["saldo"], errors="coerce")
                                .fillna(0)
                                .clip(lower=0)
                                .gt(0)
                            ).sum()
                        )
                except Exception:
                    _n_fuera = 0
            cierre.append(
                (
                    f"Conciliacion: S/ {_sal_fuente:,.2f} en la fuente / "
                    f"S/ {_sal_embudo:,.2f} en el embudo",
                    f"fuera del embudo: S/ {_fuera:,.2f} ({_n_fuera} lineas, ver EXCEPCIONES)",
                )
            )
    except Exception:
        pass
    # --- CONTROL ANTI-COLADO: el filtro de allowlist debe ser una particion ---
    # Un SKU no puede estar a la vez en el embudo aceptado y en el rechazado.
    try:
        _col = _skus_colados(df, allowlist_rechazados)
        if _col:
            cierre.append(
                (
                    f"ALERTA: {len(_col)} SKUs colados en el filtro de allowlist",
                    f"aceptados y rechazados a la vez: {', '.join(_col[:4])} (ver EXCEPCIONES)",
                )
            )
        else:
            cierre.append(
                (
                    "Control de allowlist OK: ningun SKU colado",
                    "aceptados y rechazados son conjuntos disjuntos",
                )
            )
    except Exception:
        pass
    # Estados de linea fuera de la guia ERP: el API los rellena con el grupo
    # del producto ("TAJADORES", "RESALTADORES"...) y no son estados.
    try:
        if df is not None and len(df) and "estado_linea_raw" in df.columns:
            _raw = df["estado_linea_raw"].astype(str).str.strip()
            _raw = _raw[_raw.ne("") & ~_raw.isin(["nan", "NAN"])]
            if len(_raw):
                cierre.append(
                    (
                        f"Estados de linea fuera de la guia: {len(_raw)} filas",
                        ", ".join(sorted(set(_raw))[:4]) + " (se limpiaron; ver estado_linea_raw)",
                    )
                )
    except Exception:
        pass
    # Control de coherencia del precio: el importe del ERP debe cumplir
    # PEDIDO_IMPORTE_ARITCULO = (PRE_ARTICULO / VIGENCIA) * CAN_PEDIDO.
    try:
        if df is not None and len(df) and "precio_verificable" in df.columns:
            _ver = df["precio_verificable"].fillna(False).astype(bool)
            _ok = df["precio_coherente"].fillna(True).astype(bool) & _ver
            _n = int(_ver.sum())
            if _n:
                cierre.append(
                    (
                        f"Coherencia de precios: {int(_ok.sum())}/{_n} lineas",
                        "importe = (PRE_ARTICULO/VIGENCIA) x CAN_PEDIDO",
                    )
                )
    except Exception:
        pass
    if stock_age_hours is not None:
        _stale = " (VIEJO: refrescar stock antes de emitir guias)" if stock_age_hours > 1 else ""
        cierre.append(
            (
                f"Stock snapshot: hace {stock_age_hours:.2f} h{_stale}",
                "cifras de VES/121 y guias de traslado",
            )
        )
    if allowlist_resumen:
        _rej = int(allowlist_resumen.get("filas_rechazadas", 0) or 0)
        _mot = allowlist_resumen.get("motivos") or {}
        _det = ", ".join(f"{k}: {v}" for k, v in sorted(_mot.items())) or "sin detalle"
        cierre.append(
            (
                f"Allowlist: {_rej} filas descartadas (ver SANEAMIENTO)",
                _det,
            )
        )
        _maestro = allowlist_resumen.get("maestro") or ""
        if _maestro:
            cierre.append(("Maestro de referencia", str(_maestro)))
    # Productos descontinuados con saldo: renegociar o producir, no despachar.
    try:
        if df is not None and len(df) and "producto_descontinuado" in df.columns:
            _desc = df[df["producto_descontinuado"].fillna(False).astype(bool)].copy()
            if len(_desc):
                _sal = pd.to_numeric(_desc.get("saldo", 0), errors="coerce").fillna(0)
                _desc = _desc[_sal > 0]
            if len(_desc):
                _vp = pd.to_numeric(_desc.get("valor_saldo", 0), errors="coerce").fillna(0).sum()
                _np = int(_desc["ID_PEDIDO"].nunique()) if "ID_PEDIDO" in _desc.columns else 0
                cierre.append(
                    (
                        f"Producto descontinuado: S/ {_vp:,.2f} en {_np} pedidos",
                        "no despachar sin renegocio (ver SANEAMIENTO / DESPACHO_HOY)",
                    )
                )
    except Exception:
        pass
    r = 3
    for a, b in cierre:
        ws.cell(row=r, column=1, value=a)
        ws.cell(row=r, column=2, value=b)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="KPI")
    ws.cell(row=r, column=2, value="Valor")
    _style_header(ws, 2)
    r += 1
    val_p = float(pendiente["val_pendiente"].sum()) if "val_pendiente" in pendiente else 0.0
    rows = [
        ("Familia", fam),
        (
            "Pedidos en el corte",
            int(resumen["ID_PEDIDO"].nunique())
            if not resumen.empty and "ID_PEDIDO" in resumen
            else 0,
        ),
        ("Despachable HOY S/", round(val_e, 2)),
        ("Condicionado a planilla S/", round(val_cond, 2)),
        ("Val Pendiente (sin VES) S/", round(val_p, 2)),
        (
            "Pedidos >= umbral",
            int((resumen["val_atencion"] >= umbral).sum())
            if not resumen.empty and "val_atencion" in resumen
            else 0,
        ),
        (
            "Pedidos < umbral (observacion)",
            int((resumen["val_atencion"] < umbral).sum())
            if not resumen.empty and "val_atencion" in resumen
            else 0,
        ),
    ]
    for label, value in rows:
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=value)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="ID_VENDEDOR")
    ws.cell(row=r, column=2, value="NOM_VENDEDOR")
    ws.cell(row=r, column=3, value="Val Atencion S/")
    ws.cell(row=r, column=4, value="Pedidos")
    _style_header(ws, 4)
    r += 1
    if not entrega.empty and "ID_VENDEDOR" in entrega.columns:
        rank = (
            entrega.groupby(["ID_VENDEDOR", "NOM_VENDEDOR"])["val_atencion"]
            .sum()
            .sort_values(ascending=False)
        )
        nped = entrega.groupby(["ID_VENDEDOR", "NOM_VENDEDOR"])["ID_PEDIDO"].nunique()
        for (vid, vn), v in list(rank.items())[:3]:
            ws.cell(row=r, column=1, value=str(vid))
            ws.cell(row=r, column=2, value=str(vn))
            ws.cell(row=r, column=3, value=round(float(v), 2))
            ws.cell(row=r, column=4, value=int(nped.get((vid, vn), 0)))
            r += 1
    r += 1
    ws.cell(row=r, column=1, value="QUICK WINS (pct alto + cubierto)")
    ws.cell(row=r, column=2, value="ID_PEDIDO")
    ws.cell(row=r, column=3, value="pct_cant")
    ws.cell(row=r, column=4, value="Val S/")
    _style_header(ws, 4)
    r += 1
    if not resumen.empty and "pct_cant" in resumen.columns:
        qw = resumen.sort_values("pct_cant", ascending=False).head(3)
        for _, row in qw.iterrows():
            if float(row.get("val_atencion", 0) or 0) <= 0:
                continue
            ws.cell(row=r, column=2, value=str(row.get("ID_PEDIDO", "")))
            ws.cell(row=r, column=3, value=float(row.get("pct_cant", 0) or 0))
            ws.cell(row=r, column=4, value=round(float(row.get("val_atencion", 0) or 0), 2))
            r += 1
    ws.freeze_panes = "A3"
    _auto_width(ws)


def _write_despacho_hoy(wb, fam, entrega, resumen, umbral) -> None:
    """Lista de trabajo del camion: solo lineas libres hoy (planilla ok)."""
    headers = [
        "rank_monto",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "PEDIDO_FECHA",
        "SKU",
        "NOM_ARTICULO",
        "linea",
        "estado_linea",
        "categoria",
        "saldo",
        "stock_VES",
        "cant_a_despachar",
        "cajas",
        "cajas_estimada",
        "peso_kg",
        "kg_a_despachar",
        "peso_estimada",
        "ean13",
        "descontinuado",
        "precio_unitario",
        "precio_coherente",
        "val_atencion",
        "despachable_hoy",
        "si_se_aprueba",
        "pct_cubierto_pedido",
        "pct_cant_pedido",
        "planilla_estado",
        "VIGENCIA",
        "POR_VIGENCIA",
        "medida_accion",
        "sustituto_sugerido",
        "nivel_confianza",
        "score_sustituto",
        "razon_sustituto",
        "sustituto_origen",
        "sustituto_stock",
    ]
    ws = _abrir_hoja(
        wb,
        "DESPACHO_HOY",
        f"DESPACHO HOY  ·  {fam}",
        "Lineas libres (stock VES confirmado y planilla no bloqueante), ordenadas por monto. "
        "Cada fila = un SKU a cargar: cant_a_despachar + peso_kg (capacidad) + ean13 (picking).",
        headers,
    )
    if entrega.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    # Mapa pedido -> (val_atencion, pct_cant) para rank y % por pedido
    vmap: dict[str, tuple[float, float]] = {}
    if not resumen.empty and "ID_PEDIDO" in resumen.columns:
        va = pd.to_numeric(resumen.get("val_atencion", 0), errors="coerce").fillna(0)
        pc = pd.to_numeric(resumen.get("pct_cant", 0), errors="coerce").fillna(0)
        for pid, v, p in zip(resumen["ID_PEDIDO"].astype(str), va, pc):
            vmap[pid] = (float(v), float(p))
    # % cubierto por pedido (lineas con VES >= saldo / total lineas)
    cub = {}
    if "ID_PEDIDO" in entrega.columns:
        _sal = pd.to_numeric(entrega.get("saldo", 0), errors="coerce").fillna(0)
        _ves = pd.to_numeric(
            entrega.get("stock_real", entrega.get("stock_api_ves", 0)), errors="coerce"
        ).fillna(0)
        _tmp = entrega.assign(_cub=(_ves >= _sal))
        for pid, grp in _tmp.groupby(entrega["ID_PEDIDO"].astype(str)):
            cub[pid] = round(float(grp["_cub"].mean() * 100), 1)
    # rank por pedido (monto desc), solo pedidos >= umbral
    order = sorted(vmap.items(), key=lambda kv: kv[1][0], reverse=True)
    rank = {pid: i + 1 for i, (pid, (v, _)) in enumerate(order)}
    ok_peds = {pid for pid, (v, _) in vmap.items() if v >= umbral}
    sub = entrega[entrega["ID_PEDIDO"].astype(str).isin(ok_peds)].copy()
    sub["_rv"] = sub["ID_PEDIDO"].astype(str).map(rank)
    sub = sub.sort_values(["_rv", "saldo"], ascending=[True, False])
    for _, row in sub.iterrows():
        pid = str(row.get("ID_PEDIDO", ""))
        ves = float(row.get("stock_real", row.get("stock_api_ves", 0)) or 0)
        saldo = float(row.get("saldo", 0) or 0)
        val_at = float(row.get("val_atencion", 0) or 0)
        planilla = str(row.get("NOM_ESTADO_PLANILLA_ANTICIPO", "") or "").strip().upper()
        bloqueado = planilla == "INGRESADO"
        ws.append(
            [
                rank.get(pid, ""),
                str(row.get("ID_VENDEDOR", "")),
                str(row.get("NOM_VENDEDOR", "")),
                str(row.get("COD_CLIENTE", "")),
                str(row.get("NOM_CLIENTE", "")),
                pid,
                str(row.get("NRO_DOCUMENTO", "")),
                str(row.get("PEDIDO_FECHA", "")),
                str(row.get("SKU", row.get("ID_ARTICULO", ""))),
                str(row.get("NOM_ARTICULO", row.get("nombre_catalogo", ""))),
                str(row.get("linea", "")),
                str(row.get("estado_linea", "")),
                str(row.get("categoria", "")),
                saldo,
                ves,
                round(min(max(saldo, 0), max(ves, 0)), 2),
                float(row.get("cajas", 0) or 0),
                "SI" if bool(row.get("cajas_estimada", False)) else "NO",
                float(row.get("peso_kg", 0) or 0),
                round(min(max(saldo, 0), max(ves, 0)) * float(row.get("peso_kg", 0) or 0), 2),
                "SI" if bool(row.get("peso_estimada", False)) else "NO",
                str(row.get("ean13", "")),
                "SI" if bool(row.get("producto_descontinuado", False)) else "NO",
                float(row.get("precio_unitario", 0) or 0),
                (
                    "-"
                    if not bool(row.get("precio_verificable", False))
                    else ("SI" if bool(row.get("precio_coherente", True)) else "NO")
                ),
                val_at,
                0.0 if bloqueado else val_at,
                val_at if bloqueado else 0.0,
                float(cub.get(pid, 0.0)),
                float(vmap.get(pid, (0, 0))[1]),
                str(row.get("NOM_ESTADO_PLANILLA_ANTICIPO", "")),
                float(row.get("VIGENCIA", 0) or 0),
                float(row.get("POR_VIGENCIA", 0) or 0),
                str(row.get("medida_accion", "")),
                str(row.get("sustituto_sugerido", "")),
                str(row.get("nivel_confianza", "")),
                float(row.get("score_sustituto", 0) or 0),
                str(row.get("razon_sustituto", "")),
                str(row.get("sustituto_origen", "")),
                float(row.get("sustituto_stock", 0) or 0),
            ]
        )
    ws.freeze_panes = "A4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_detalle_pedido(wb, df, familia: str | None = None) -> None:
    """DETALLE_PEDIDO: fila por SKU (destino del hipervinculo).

    Incluye la alerta de sustituto al final (sustituto_sugerido + nivel_confianza
    con color) para resolver "no tengo stock, que pongo en su lugar" sin salir
    de la hoja.
    """
    headers = [
        "pedido",
        "pedido_raiz",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "CONDICION_PAGO",
        "estado_pedido",
        "estado_linea",
        "SKU",
        "NOM_ARTICULO",
        "linea",
        "saldo",
        "stock_VES",
        "stock_121",
        "precio_unitario",
        "valor_saldo",
        "peso_kg",
        "ean13",
        "descontinuado",
        "sustituto_sugerido",
        "nivel_confianza",
        "score_sustituto",
        "razon_sustituto",
        "sustituto_origen",
        "sustituto_stock",
    ]
    ws = _abrir_hoja(
        wb,
        "DETALLE_PEDIDO",
        "DETALLE POR SKU  ·  destino del hipervinculo",
        "Una fila por SKU. La ultima columna (nivel_confianza) avisa el sustituto: "
        "VERDE = mismo EAN (certeza), AMARILLO = probable, ROJO = requiere tu criterio.",
        headers,
    )
    if df is None or df.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    d = df.copy()
    if familia:
        from src.core.analytics import normalize_cond_familia

        fam_serie = d.get("CONDICION_PAGO", pd.Series("", index=d.index)).map(
            normalize_cond_familia
        )
        d = d[fam_serie == str(familia).strip().upper()]
    if d.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    from src.core.prioridad import pedido_raiz as _raiz

    idc = "ID_PEDIDO" if "ID_PEDIDO" in d.columns else None
    if idc:
        d["_raiz"] = d[idc].map(_raiz)
        _orden = [c for c in ["NOM_CLIENTE", "_raiz", idc] if c in d.columns]
        if _orden:
            d = d.sort_values(_orden, na_position="last")
    for _, r in d.iterrows():
        ws.append(
            [
                str(r.get("ID_PEDIDO", "")),
                str(r.get("_raiz", "")),
                str(r.get("NOM_CLIENTE", "")),
                str(r.get("ID_VENDEDOR", "")),
                str(r.get("CONDICION_PAGO", "")),
                str(r.get("PEDIDO_ESTADO", "")),
                str(r.get("estado_linea", "")),
                str(r.get("SKU", r.get("ID_ARTICULO", ""))),
                str(r.get("NOM_ARTICULO", r.get("nombre_catalogo", ""))),
                str(r.get("linea", "")),
                float(pd.to_numeric(r.get("saldo", 0), errors="coerce") or 0),
                float(pd.to_numeric(r.get("stock_real", 0), errors="coerce") or 0),
                float(pd.to_numeric(r.get("stock_api_121", 0), errors="coerce") or 0),
                float(pd.to_numeric(r.get("precio_unitario", 0), errors="coerce") or 0),
                float(pd.to_numeric(r.get("valor_saldo", 0), errors="coerce") or 0),
                float(pd.to_numeric(r.get("peso_kg", 0), errors="coerce") or 0),
                str(r.get("ean13", "")),
                "SI" if bool(r.get("producto_descontinuado", False)) else "NO",
                str(r.get("sustituto_sugerido", "")),
                str(r.get("nivel_confianza", "")),
                float(pd.to_numeric(r.get("score_sustituto", 0), errors="coerce") or 0),
                str(r.get("razon_sustituto", "")),
                str(r.get("sustituto_origen", "")),
                float(pd.to_numeric(r.get("sustituto_stock", 0), errors="coerce") or 0),
            ]
        )
    ws.freeze_panes = "D4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_avance_pedido(wb, an, familia: str | None = None) -> None:
    """AVANCE_PEDIDO: una fila por PEDIDO x estado_linea (comparativa).

    Responde "de cuanto era el pedido, cuanto entregue y cuanto debo",
    desglosado por estado_linea. La columna `pedido` lleva HIPERVINCULO a la
    hoja DETALLE_PEDIDO para saltar al SKU que debo (un clic).
    """
    headers = [
        "pedido",
        "pedido_raiz",
        "es_complemento",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "CONDICION_PAGO",
        "prioridad_comercial_etq",
        "estado_pedido",
        "requiere",
        "tiene_oc",
        "estado_linea",
        "lineas",
        "pedido_und",
        "entregado_und",
        "saldo_und",
        "pct_avance",
        "valor_saldo",
        "VES_cubre",
        "dias",
    ]
    ws = _abrir_hoja(
        wb,
        "AVANCE_PEDIDO",
        "AVANCE POR PEDIDO  ·  que falta, por estado_linea",
        "Una fila por pedido y estado_linea. Clic en la columna pedido para saltar al "
        "SKU que se debe. Filtrar por pedido (bloques contiguos) o por pedido_raiz "
        "(agrupa C2185 y C2185A).",
        headers,
    )
    try:
        av = an.resumen_avance_pedido(familia)
    except Exception:
        av = pd.DataFrame()
    if av is not None and len(av):
        for _, r in av.iterrows():
            ws.append(
                [
                    str(r.get("pedido", "")),
                    str(r.get("pedido_raiz", "")),
                    str(r.get("es_complemento", "")),
                    str(r.get("cliente", "")),
                    str(r.get("id_vendedor", "")),
                    str(r.get("vendedor", "")),
                    str(r.get("condicion", "")),
                    str(r.get("prioridad_comercial_etq", "")),
                    str(r.get("estado_pedido", "")),
                    str(r.get("requiere", "")),
                    str(r.get("tiene_oc", "")),
                    str(r.get("estado_linea", "")),
                    int(r.get("lineas", 0) or 0),
                    float(r.get("pedido_und", 0) or 0),
                    float(r.get("entregado_und", 0) or 0),
                    float(r.get("saldo_und", 0) or 0),
                    float(r.get("pct_avance", 0) or 0),
                    float(r.get("valor_saldo", 0) or 0),
                    int(r.get("VES_cubre", 0) or 0),
                    int(r.get("dias", 0) or 0),
                ]
            )
    ws.freeze_panes = "C4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)
    # Hipervinculo de la columna pedido -> DETALLE_PEDIDO (si existe).
    _link_pedidos(ws, desde=4, col=1)


def _link_pedidos(ws, desde: int, col: int = 1, hoja: str = "DETALLE_PEDIDO") -> None:
    """Convierte la columna `col` en hipervinculo interno a la hoja de detalle."""
    for fila in range(desde, ws.max_row + 1):
        cel = ws.cell(row=fila, column=col)
        if cel.value in (None, ""):
            continue
        cel.hyperlink = f"#'{hoja}'!A1"
        cel.font = Font(color="0563C1", underline="single")


def _write_por_cliente(wb, an, familia: str | None = None) -> None:
    """POR_CLIENTE: vendedor x cliente con desglose por estado_linea."""
    headers = [
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "pedidos",
        "lineas",
        "pedido_und",
        "entregado_und",
        "saldo_und",
        "pct_avance",
        "valor_saldo",
        "NUEVO_sal",
        "IMPORTADO_sal",
        "TRADICIONAL_sal",
        "NACIONAL_sal",
        "NUEVO_ped",
        "IMPORTADO_ped",
        "TRADICIONAL_ped",
        "NACIONAL_ped",
    ]
    ws = _abrir_hoja(
        wb,
        "POR_CLIENTE",
        "VENDEDOR -> CLIENTE  ·  cuanto se debe por estado_linea",
        "Una fila por vendedor y cliente: pedido / entregado / saldo y el desglose "
        "NUEVO / IMPORTADO / TRADICIONAL / NACIONAL. Filtrar por ID_VENDEDOR (ej. 052).",
        headers,
    )
    try:
        pc = an.resumen_por_cliente(familia)
    except Exception:
        pc = pd.DataFrame()
    if pc is not None and len(pc):
        for _, r in pc.iterrows():
            ws.append(
                [
                    str(r.get("id_vendedor", "")),
                    str(r.get("vendedor", "")),
                    str(r.get("cod_cliente", "")),
                    str(r.get("cliente", "")),
                    int(r.get("pedidos", 0) or 0),
                    int(r.get("lineas", 0) or 0),
                    float(r.get("pedido_und", 0) or 0),
                    float(r.get("entregado_und", 0) or 0),
                    float(r.get("saldo_und", 0) or 0),
                    float(r.get("pct_avance", 0) or 0),
                    float(r.get("valor_saldo", 0) or 0),
                    float(r.get("NUEVO_sal", 0) or 0),
                    float(r.get("IMPORTADO_sal", 0) or 0),
                    float(r.get("TRADICIONAL_sal", 0) or 0),
                    float(r.get("NACIONAL_sal", 0) or 0),
                    float(r.get("NUEVO_ped", 0) or 0),
                    float(r.get("IMPORTADO_ped", 0) or 0),
                    float(r.get("TRADICIONAL_ped", 0) or 0),
                    float(r.get("NACIONAL_ped", 0) or 0),
                ]
            )
    ws.freeze_panes = "C4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_ya_entregado(wb, df, familia: str | None = None) -> None:
    """YA_ENTREGADO: pedidos con saldo 0 (silencio operativo, historico).

    No descarta nada: lo entregado sale del flujo accionable pero queda aqui
    para consulta (cuanto se entrego, cuando, a quien).
    """
    headers = [
        "pedido",
        "pedido_raiz",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "CONDICION_PAGO",
        "estado_pedido",
        "PEDIDO_FECHA",
        "lineas",
        "pedido_und",
        "entregado_und",
        "pct_avance",
        "valor_pedido",
    ]
    ws = _abrir_hoja(
        wb,
        "YA_ENTREGADO",
        "YA ENTREGADO  ·  pedidos cerrados (saldo 0)",
        "Pedidos ya despachados por completo. Quedan aqui para consulta: no son "
        "ruido en las hojas de accion pero tampoco se descartan.",
        headers,
    )
    if df is None or df.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    d = df.copy()
    if familia:
        from src.core.analytics import normalize_cond_familia

        fam_serie = d.get("CONDICION_PAGO", pd.Series("", index=d.index)).map(
            normalize_cond_familia
        )
        d = d[fam_serie == str(familia).strip().upper()]
    if d.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    idc = "ID_PEDIDO" if "ID_PEDIDO" in d.columns else None
    if idc is None:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return

    def _num(col):
        return pd.to_numeric(d.get(col, 0), errors="coerce").fillna(0)

    d["_ped"] = _num("CAN_PEDIDO")
    d["_des"] = _num("CAN_DESPACHO")
    d["_sal"] = _num("saldo")
    d["_vp"] = _num("valor_pedido")
    d["_vsal"] = _num("valor_saldo")
    g = d.groupby(idc, dropna=False)
    out = pd.DataFrame(
        {
            "lineas": g.size(),
            "pedido_und": g["_ped"].sum(),
            "entregado_und": g["_des"].sum(),
            "saldo_und": g["_sal"].sum(),
            "valor_pedido": g["_vp"].sum(),
        }
    )
    out = out[out["saldo_und"].round(2) <= 0]
    if out.empty:
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    out["pct_avance"] = (out["entregado_und"] / out["pedido_und"].replace(0, 1) * 100).round(1)
    for c, nombre in (
        ("NOM_CLIENTE", "cliente"),
        ("ID_VENDEDOR", "id_vendedor"),
        ("NOM_VENDEDOR", "vendedor"),
        ("CONDICION_PAGO", "condicion"),
        ("PEDIDO_ESTADO", "estado_pedido"),
        ("PEDIDO_FECHA", "fecha"),
    ):
        if c in d.columns:
            out[nombre] = g[c].first()
    from src.core.prioridad import pedido_raiz

    out = out.reset_index()
    out["raiz"] = out[idc].map(pedido_raiz)
    out = out.sort_values(["raiz", idc])
    for _, r in out.iterrows():
        ws.append(
            [
                str(r.get(idc, "")),
                str(r.get("raiz", "")),
                str(r.get("cliente", "")),
                str(r.get("id_vendedor", "")),
                str(r.get("vendedor", "")),
                str(r.get("condicion", "")),
                str(r.get("estado_pedido", "")),
                str(r.get("fecha", "")),
                int(r.get("lineas", 0) or 0),
                float(r.get("pedido_und", 0) or 0),
                float(r.get("entregado_und", 0) or 0),
                float(r.get("pct_avance", 0) or 0),
                float(r.get("valor_pedido", 0) or 0),
            ]
        )
    ws.freeze_panes = "C4"
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _write_traslado(wb, pendiente) -> None:
    """TRASLADO_121: solicitud contundente de traslado masivo 121 -> VES.

    Cabecera de solicitud (almacen origen/destino, totales, pedidos beneficiados)
    + una fila por SKU con impacto: valor trasladado, pedidos que desbloquea,
    cuantos cierran completos y que hacer si el stock 121 no alcanza.
    Ordenado por impacto (prioridad comercial + antiguedad + monto).
    """
    from src.config.settings import UMBRAL_CAJAS_121_OBSERVACION
    from src.core.prioridad import prioridad_comercial

    headers = [
        "rank",
        "SKU",
        "NOM_ARTICULO",
        "linea",
        "estado_linea",
        "saldo_total",
        "faltante_total",
        "stock_ves",
        "stock_121",
        "cajas_121",
        "alerta_121",
        "a_trasladar",
        "valor_traslado",
        "fuera_de_alcance_121",
        "SKUs_pedidos",
        "pedido_top",
        "pedidos_cerrar_100",
        "antiguedad_max_dias",
        "accion_si_no_alcanza",
        "detalle_fifo",
    ]
    ws = _abrir_hoja(
        wb,
        "TRASLADO_121",
        "SOLICITUD DE TRASLADO MASIVO  ·  121 -> VES",
        "Origen: almacen 121. Destino: VES. a_trasladar nunca supera el stock 121. "
        "Un solo tramite para todo el libro: los totales de la banda superior son la "
        "solicitud. detalle_fifo indica que pedido se lleva cada parte (mas antiguo primero).",
        headers,
    )
    _vaciar = pendiente is None or pendiente.empty
    sub = pendiente.copy() if not _vaciar else None
    if not _vaciar:
        _s121 = pd.to_numeric(sub.get("stock_api_121", 0), errors="coerce").fillna(0)
        sub = sub[(_s121 > 0).values].copy()
    if _vaciar or sub is None or sub.empty:
        # Sin datos: deja la banda de cabecera igual (solicitud en 0).
        ws.cell(row=3, column=1, value="TOTAL A TRASLADAR (unidades)")
        ws.cell(row=3, column=2, value=0)
        ws.freeze_panes = "A4"
        _finish_sheet(ws, ws.max_row, fila_enc=3)
        return
    _ves = pd.to_numeric(
        sub.get("stock_real", sub.get("stock_api_ves", 0)), errors="coerce"
    ).fillna(0)
    _sal = pd.to_numeric(sub.get("saldo", 0), errors="coerce").fillna(0)
    sub["__falt"] = (_sal - _ves).clip(lower=0)
    pu_col = "precio_unitario" if "precio_unitario" in sub.columns else None
    sub["__pu"] = pd.to_numeric(sub.get(pu_col, 0), errors="coerce").fillna(0) if pu_col else 0.0
    sku_col = "SKU" if "SKU" in sub.columns else "ID_ARTICULO"
    nom_col = "NOM_ARTICULO" if "NOM_ARTICULO" in sub.columns else "nombre_catalogo"
    fam_col = (
        sub["CONDICION_PAGO"].map(lambda v: prioridad_comercial(_familia_de(v)))
        if "CONDICION_PAGO" in sub.columns
        else pd.Series(5, index=sub.index)
    )
    sub["__prio_com"] = fam_col
    # Estado de descuento por pedido: cuantas lineas del pedido falta cubrir.
    _falt_por_ped = (
        sub.groupby("ID_PEDIDO", dropna=False)["__falt"].sum() if "ID_PEDIDO" in sub else None
    )
    rows = []
    for sku, grp in sub.groupby(sku_col, dropna=False):
        s121 = float(pd.to_numeric(grp["stock_api_121"], errors="coerce").fillna(0).max())
        falt_total = float(grp["__falt"].sum())
        a_tras = min(falt_total, s121)
        if "PEDIDO_FECHA" in grp.columns:
            ordered = grp.assign(
                _f=pd.to_datetime(grp["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
            ).sort_values(["_f"], na_position="last")
        else:
            ordered = grp
        restante, detalle, pedidos_tocados = a_tras, [], []
        for _, ln in ordered.iterrows():
            if restante <= 0:
                break
            want = float(ln["__falt"] or 0)
            if want <= 0:
                continue
            take = min(want, restante)
            detalle.append(f"{ln.get('ID_PEDIDO', '')}:{int(take)}")
            pedidos_tocados.append(str(ln.get("ID_PEDIDO", "")))
            restante -= take
        # Pedidos que CIERRAN al 100% con este traslado (su faltante == lo que se lleva)
        cierran = 0
        if _falt_por_ped is not None:
            llevado_por_ped: dict[str, float] = {}
            for d in detalle:
                pid_d, _, und = d.partition(":")
                llevado_por_ped[pid_d] = llevado_por_ped.get(pid_d, 0.0) + float(und or 0)
            for pid_d, llevado in llevado_por_ped.items():
                total_ped = float(
                    pd.to_numeric(
                        grp.loc[grp["ID_PEDIDO"].astype(str) == pid_d, "__falt"], errors="coerce"
                    )
                    .fillna(0)
                    .sum()
                )
                if total_ped > 0 and llevado >= total_ped - 1e-6:
                    cierran += 1
        _f = (
            pd.to_datetime(grp["PEDIDO_FECHA"], dayfirst=True, errors="coerce").max()
            if "PEDIDO_FECHA" in grp.columns
            else None
        )
        dias_max = 0
        if _f is not None and pd.notna(_f):
            dias_max = int((pd.Timestamp.now().normalize() - _f.normalize()).days)
        pu_pond = float((grp["__pu"] * grp["__falt"]).sum() / falt_total if falt_total > 0 else 0)
        prioridad = int(grp["__prio_com"].min()) if "__prio_com" in grp else 5
        # --- Reglas de observacion del almacen 121 ---
        # 121 (QC / produccion terminada) solo tiene `disponible`: NO hay
        # predespacho que descontar. El factor de empaque (un_bx) define
        # cuantas cajas hay:
        #   <= 1 caja                 -> TRASLADABLE
        #   >  1 caja                 -> TRASLADABLE + OBSERVACION (revisar)
        #   121 con stock sin faltante -> OBSERVACION (sobra stock en QC)
        s_ves_sku = float(
            pd.to_numeric(
                grp.get("stock_real", grp.get("stock_api_ves", 0)), errors="coerce"
            ).fillna(0).max()
        )
        _un_bx = 1.0
        if "un_bx" in grp.columns:
            _un_bx = float(
                pd.to_numeric(grp["un_bx"], errors="coerce").fillna(1).replace(0, 1).max()
            )
        cajas_121 = s121 / _un_bx if _un_bx else 0.0
        if falt_total <= 0:
            alerta_121 = "OBSERVACION"
        elif cajas_121 > UMBRAL_CAJAS_121_OBSERVACION:
            alerta_121 = "TRASLADABLE + OBSERVACION"
        else:
            alerta_121 = "TRASLADABLE"
        rows.append(
            {
                "sku": str(sku),
                "nombre": str(grp[nom_col].iloc[0]) if nom_col in grp.columns else "",
                "linea": str(grp["linea"].iloc[0]) if "linea" in grp.columns else "",
                "estado_linea": (
                    str(grp["estado_linea"].iloc[0]) if "estado_linea" in grp.columns else ""
                ),
                "saldo_total": float(
                    pd.to_numeric(grp.get("saldo", 0), errors="coerce").fillna(0).sum()
                ),
                "faltante_total": falt_total,
                "stock_ves": s_ves_sku,
                "stock_121": s121,
                "cajas_121": round(cajas_121, 2),
                "alerta_121": alerta_121,
                "a_trasladar": a_tras,
                "valor_traslado": a_tras * pu_pond,
                "fuera": max(falt_total - a_tras, 0.0),
                "pedidos": int(grp["ID_PEDIDO"].nunique()) if "ID_PEDIDO" in grp else len(grp),
                "pedido_top": pedidos_tocados[0] if pedidos_tocados else "",
                "cierran": cierran,
                "dias_max": dias_max,
                "accion": (
                    "TRASLADAR_COMPLETO"
                    if a_tras >= falt_total - 1e-6
                    else "TRASLADAR_PARCIAL_Y_REPONER"
                ),
                "fifo": "; ".join(detalle),
                "prioridad": prioridad,
            }
        )
    out = pd.DataFrame(rows)
    # Orden por impacto: prioridad comercial, luego valor trasladado.
    out = out.sort_values(["prioridad", "valor_traslado"], ascending=[True, False])
    # --- Banda de solicitud (fila 4): totales del tramite completo ---
    tot_tras = float(out["a_trasladar"].sum())
    tot_val = float(out["valor_traslado"].sum())
    tot_fuera = float(out["fuera"].sum())
    ped_benef = int(out["pedidos"].sum())
    ws.cell(row=4, column=1, value="TOTAL SOLICITUD")
    ws.cell(row=4, column=2, value=f"{tot_tras:,.0f} und")
    ws.cell(row=4, column=3, value=f"S/ {tot_val:,.2f}")
    ws.cell(row=4, column=4, value=f"{len(out)} SKUs")
    ws.cell(row=4, column=5, value=f"fuera de alcance: {tot_fuera:,.0f} und")
    for c in range(1, len(headers) + 1):
        ws.cell(row=4, column=c).fill = _SUBTOTAL_FILL
        ws.cell(row=4, column=c).font = _SUBTOTAL_FONT
    for i, (_, r) in enumerate(out.iterrows(), start=1):
        ws.append(
            [
                i,
                r["sku"],
                r["nombre"],
                r["linea"],
                r["estado_linea"],
                round(r["saldo_total"], 2),
                round(r["faltante_total"], 2),
                round(r["stock_ves"], 2),
                round(r["stock_121"], 2),
                round(r["cajas_121"], 2),
                r["alerta_121"],
                round(r["a_trasladar"], 2),
                round(r["valor_traslado"], 2),
                round(r["fuera"], 2),
                r["pedidos"],
                r["pedido_top"],
                r["cierran"],
                r["dias_max"],
                r["accion"],
                r["fifo"],
            ]
        )
    ws.freeze_panes = "A5"
    # Resaltado: las filas que necesitan conteo fisico en 121 (OBSERVACION)
    # se pintan para que el pedido de traslado no se firme a ciegas.
    _col_alerta = headers.index("alerta_121") + 1
    _letra_alerta = get_column_letter(_col_alerta)
    _fila_ini = 5
    if ws.max_row >= _fila_ini:
        ws.conditional_formatting.add(
            f"{_letra_alerta}{_fila_ini}:{_letra_alerta}{ws.max_row}",
            FormulaRule(
                formula=[f'ISNUMBER(SEARCH("OBSERVACION",{_letra_alerta}{_fila_ini}))'],
                fill=PatternFill(
                    start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"
                ),
            ),
        )
    _auto_width(ws)
    _finish_sheet(ws, ws.max_row, fila_enc=3)


def _familia_de(cond) -> str:
    """Familia de condicion de pago (import perezoso para evitar ciclos)."""
    from src.core.analytics import normalize_cond_familia

    return normalize_cond_familia(cond)


def export_cola_despacho(df: pd.DataFrame, output_path: str | Path | None = None) -> Path:
    """Genera XLSX con las lineas listas para despachar por ID_PEDIDO.

    Recibe el DataFrame producido por analytics.get_cola_despacho().
    """
    from datetime import datetime

    output_path = Path(
        output_path or f"cola_despacho_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "COLA_DESPACHO"
    cols = [
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "CONDICION_PAGO",
        "cond_familia",
        "SKU",
        "NOM_ARTICULO",
        "CAN_PEDIDO",
        "CAN_DESPACHO",
        "saldo",
        "stock_api_ves",
        "stock_api_121",
        "stock_api_otros",
        "un_bx",
        "cant_a_despachar",
        "cajas_a_despachar",
    ]
    headers = [c for c in cols if c in df.columns]
    ws.append(headers)
    _style_header(ws, len(headers))
    for _, row in df.iterrows():
        ws.append([row.get(h, "") for h in headers])
    ws.freeze_panes = "A2"
    _auto_width(ws)
    wb.save(output_path)
    return output_path


# ---------------------------------------------------------------
# Grupo de prioridad (multi-cliente/vendedor/pedido)
# ---------------------------------------------------------------
def export_grupo(df: pd.DataFrame, nombre: str, output_path: str | Path | None = None) -> Path:
    """Exporta las lineas de un grupo de prioridad a XLSX."""
    from datetime import datetime

    safe = (
        "".join(c if c.isalnum() or c in "_- " else "_" for c in nombre).strip().replace(" ", "_")
    )
    output_path = Path(
        output_path
        or f"grupo_{safe or 'sin_nombre'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "GRUPO"
    cols = [
        "ID_PEDIDO",
        "NRO_DOCUMENTO",
        "COD_CLIENTE",
        "NOM_CLIENTE",
        "ID_VENDEDOR",
        "NOM_VENDEDOR",
        "CONDICION_PAGO",
        "cond_familia",
        "SKU",
        "NOM_ARTICULO",
        "CAN_PEDIDO",
        "CAN_DESPACHO",
        "saldo",
        "cajas",
        "valor_saldo",
        "stock_api_ves",
        "stock_api_121",
        "stock_api_otros",
        "PEDIDO_ESTADO",
        "PEDIDO_FECHA",
    ]
    headers = [c for c in cols if c in df.columns]
    ws.append(headers)
    _style_header(ws, len(headers))
    for _, row in df.iterrows():
        ws.append([row.get(h, "") for h in headers])
    ws.freeze_panes = "A2"
    _auto_width(ws)
    wb.save(output_path)
    return output_path
