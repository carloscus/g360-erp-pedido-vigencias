"""Pruebas de generacion XLSX: hojas, formulas y formato."""

from __future__ import annotations

import pandas as pd
from openpyxl import load_workbook

from src.core.exporters import export_to_xlsx


def _build_df() -> pd.DataFrame:
    return pd.DataFrame({
        "NRO_DOCUMENTO": ["20481150125", "20481150126"],
        "COD_CLIENTE": ["10214", "10214"],
        "NOM_CLIENTE": ["CLIENTE A", "CLIENTE A"],
        "ID_VENDEDOR": ["177", "177"],
        "NOM_VENDEDOR": ["VENDEDOR 1", "VENDEDOR 1"],
        "ID_ARTICULO": ["02187", "01240"],
        "NOM_ARTICULO": ["FORRO N VINIFORRITO CRISTAL 20-25", "N SEMIDEPORTIVA FUTBOL CRACKCITO"],
        "categoria": ["VINIFAN", "VINIBALL"],
        "estado_linea": ["TRADICIONAL", "NACIONAL"],
        "NOM_ALMACEN": ["CENTRO LOGISTICO VES", "VES"],
        "CONDICION_PAGO": ["CONTADO", "CONTADO"],
        "un_bx": [100, 60],
        "PRE_ARTICULO": [178, 9.16],
        "CAN_PEDIDO": [100, 384],
        "CAN_DESPACHO": [0, 0],
        "saldo": [100, 384],
        "por_atendido": [0, 0],
        "cajas": [1, 6.4],
        "valor_saldo": [178, 9.16],
    })


def test_export_hojas_base_y_por_vendedor(tmp_path):
    """El XLSX contiene las 7 hojas base + una hoja por vendedor."""
    out = tmp_path / "out.xlsx"
    export_to_xlsx(_build_df(), out)
    wb = load_workbook(out)
    esperadas = [
        "RESUMEN", "POR_CLIENTE", "POR_VENDEDOR", "POR_PRODUCTO",
        "STOCK_DESPACHO", "DETALLE", "ALERTAS_QC",
    ]
    for hoja in esperadas:
        assert hoja in wb.sheetnames, f"Falta hoja {hoja}: {wb.sheetnames}"
    # Hoja individual por vendedor (ID 177, VENDEDOR 1)
    assert "177_VENDEDOR 1" in wb.sheetnames


def test_export_nombre_con_timestamp():
    """El nombre default sigue el patron pedidos_vigencias_YYYYMMDD_HHMMSS."""
    import re

    from src.core.exporters import _default_filename
    assert re.match(r"pedidos_vigencias_\d{8}_\d{6}\.xlsx", _default_filename())


def test_detalle_con_formulas(tmp_path):
    """La hoja DETALLE tiene formulas Excel en las columnas calculadas."""
    out = tmp_path / "out.xlsx"
    export_to_xlsx(_build_df(), out)
    wb = load_workbook(out)
    ws = wb["DETALLE"]
    headers = [c.value for c in ws[1]]
    # La fila 2 debe tener formulas en las columnas calculadas
    f_row = {h: i + 1 for i, h in enumerate(headers)}
    saldo_cell = ws.cell(row=2, column=f_row["saldo"])
    por_cell = ws.cell(row=2, column=f_row["por_atendido"])
    cajas_cell = ws.cell(row=2, column=f_row["cajas"])
    saldo_formula = str(saldo_cell.value)
    assert saldo_formula.startswith("=")
    # La formula debe restar dos celdas (CAN_PEDIDO - CAN_DESPACHO)
    assert "-" in saldo_formula
    assert str(por_cell.value).startswith("=IF(")
    assert str(cajas_cell.value).startswith("=IF(")


def test_resumen_kpis(tmp_path):
    """La hoja RESUMEN incluye KPIs globales y tabla por categoria."""
    out = tmp_path / "out.xlsx"
    export_to_xlsx(_build_df(), out)
    wb = load_workbook(out)
    ws = wb["RESUMEN"]
    valores = [ws.cell(row=r, column=2).value for r in range(2, 11)]
    assert 2 in valores  # total items
    assert 484 in valores  # saldo total
    assert "VINIFAN" in [ws.cell(row=r, column=1).value for r in range(12, 15)]
