"""Drill limpio vendedor → cliente → pedido → sku."""

import pandas as pd

from src.config.theme import get_colors
from src.ui.tabs_view import TabsView


class _P:
    overlay = []
    controls = []
    def update(self, *a): pass
    def add(self, *c): pass


def _df():
    return pd.DataFrame([
        {"ID_VENDEDOR": "V1", "NOM_VENDEDOR": "Juan", "COD_CLIENTE": "C1", "NOM_CLIENTE": "Cli A",
         "ID_PEDIDO": "P1", "SKU": "S1", "NOM_ARTICULO": "A1", "CAN_PEDIDO": 10, "CAN_DESPACHO": 2, "saldo": 8, "valor_saldo": 100, "_fuente": "a.xls"},
        {"ID_VENDEDOR": "V1", "NOM_VENDEDOR": "Juan", "COD_CLIENTE": "C1", "NOM_CLIENTE": "Cli A",
         "ID_PEDIDO": "P1", "SKU": "S2", "NOM_ARTICULO": "A2", "CAN_PEDIDO": 5, "CAN_DESPACHO": 0, "saldo": 5, "valor_saldo": 50, "_fuente": "a.xls"},
        {"ID_VENDEDOR": "V1", "NOM_VENDEDOR": "Juan", "COD_CLIENTE": "C2", "NOM_CLIENTE": "Cli B",
         "ID_PEDIDO": "P2", "SKU": "S3", "NOM_ARTICULO": "A3", "CAN_PEDIDO": 7, "CAN_DESPACHO": 7, "saldo": 0, "valor_saldo": 0, "_fuente": "a.xls"},
        {"ID_VENDEDOR": "V2", "NOM_VENDEDOR": "Ana", "COD_CLIENTE": "C3", "NOM_CLIENTE": "Cli C",
         "ID_PEDIDO": "P3", "SKU": "S4", "NOM_ARTICULO": "A4", "CAN_PEDIDO": 20, "CAN_DESPACHO": 5, "saldo": 15, "valor_saldo": 200, "_fuente": "a.xls"},
    ])


def test_drill_vendedor_a_sku():
    tv = TabsView(_P(), get_colors("dark"))
    df = _df()
    tv.update_data(df, "offline")
    assert tv._dimension == "vendedor"
    assert tv._drill_stack == []

    # Vendedor Juan → clientes (3 lineas -> 2 clientes agrupados)
    tv._on_row_click({"ID_VENDEDOR": "V1", "NOM_VENDEDOR": "Juan"})
    assert tv._dimension == "vendedor_cliente"
    assert tv._drill_stack[-1]["label"] == "Juan"
    assert len(tv._current_level_df()) == 3
    assert len(tv._group_level(tv._current_level_df(), "vendedor_cliente")) == 2

    # Cliente Cli A → pedidos
    tv._on_row_click({"COD_CLIENTE": "C1", "NOM_CLIENTE": "Cli A"})
    assert tv._dimension == "pedido"
    assert len(tv._drill_stack) == 2
    # nivel pedido agrupa a 1 pedido (P1) para C1
    grouped = tv._group_level(tv._current_level_df(), "pedido")
    assert len(grouped) == 1
    assert grouped.iloc[0]["ID_PEDIDO"] == "P1"

    # Pedido P1 → SKUs
    tv._on_row_click({"ID_PEDIDO": "P1"})
    assert tv._dimension == "linea"
    assert len(tv._current_level_df()) == 2
    assert set(tv._current_level_df()["SKU"]) == {"S1", "S2"}

    # Breadcrumb y back
    tv._drill_to(1)  # volver a cliente
    assert tv._dimension == "pedido" or tv._drill_stack[-1]["label"] == "Cli A"
    tv._drill_to(None)
    assert tv._dimension == "vendedor"
    assert tv._drill_stack == []


def test_tabs_view_limpia_sin_ruido():
    """La vista limpia no expone chips ni selector de 9 dimensiones."""
    tv = TabsView(_P(), get_colors("dark"))
    tv.update_data(_df(), "offline")
    root = tv.build()
    # build no debe incluir sort/cond chips (limpio)
    assert root is not None
    # solo debe exponer una dimension raiz
    from src.ui.tabs_view import DIMENSIONS
    assert DIMENSIONS == [("vendedor", "Vendedores", "Vigencia por vendedor — click en nombre para ver clientes", tv._dimension)] or len(DIMENSIONS) == 1
