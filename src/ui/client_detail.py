"""
Vista de detalle de cliente (pagina propia del router).

Muestra KPIs del cliente, desglose por estado de linea y la tabla de
lineas de pedido (SKU, almacen, cantidades, saldo). Todas las columnas
son opcionales: la vista degrada segun los datos disponibles.
"""

from __future__ import annotations

import logging

import flet as ft
import pandas as pd

from src.core.analytics import PedidosAnalytics
from src.ui.components import build_tabular_report, kpi_card
from src.ui.config import (
    FONT_SIZE_2XL,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    PADDING_2XL,
    PADDING_LG,
    RADIUS_LG,
    SPACING_LG,
    SPACING_MD,
    SPACING_XL,
)

_log = logging.getLogger("g360.pedido_vigencias")


class ClientDetailView:
    """Pagina de detalle para un cliente especifico."""

    def __init__(self, df_cliente: pd.DataFrame, colors: dict, nombre: str = "") -> None:
        self._df = df_cliente
        self.c = colors
        self._nombre = nombre
        self._analytics = PedidosAnalytics(df_cliente) if not df_cliente.empty else None

    def build(self) -> ft.Container:
        _log.info("[ClientDetail] build: nombre=%s filas=%d", self._nombre, len(self._df) if self._df is not None else 0)
        if self._df is None or self._df.empty or self._analytics is None:
            return ft.Container(
                content=ft.Text("Sin datos para este cliente", size=FONT_SIZE_MEDIUM, color=self.c["text_muted"]),
                padding=PADDING_2XL,
            )

        kpis = self._analytics.get_kpis()
        _log.info("[ClientDetail] KPIs: %s", {k: v for k, v in kpis.items() if k in ['total_items', 'saldo_total', 'valor_total', 'cajas_total']})
        cli_col = self._analytics._cliente_col()
        nombre_cliente = ""
        if cli_col in self._df.columns and not self._df.empty:
            nombre_cliente = str(self._df[cli_col].iloc[0] or "")

        header = ft.Row([
            ft.Icon(ft.Icons.PERSON, size=FONT_SIZE_2XL, color=self.c["accent"]),
            ft.Column([
                ft.Text(nombre_cliente or self._nombre or "Detalle de cliente",
                        size=FONT_SIZE_2XL, weight=ft.FontWeight.W_700, color=self.c["text_primary"]),
                ft.Text(f"{len(self._df)} lineas de pedido", size=FONT_SIZE_SMALL, color=self.c["text_muted"]),
            ], spacing=2),
        ], spacing=SPACING_MD)

        cards = ft.Row([
            kpi_card(self.c, "Items", f"{kpis.get('total_items', 0):,}", "kpis", size="small"),
            kpi_card(self.c, "Saldo Units", self._fmt(kpis.get("saldo_total")), "saldo", size="small"),
            kpi_card(self.c, "Cajas", self._fmt(kpis.get("cajas_total")), "cajas", size="small"),
            kpi_card(self.c, "Valor S/", self._fmt(kpis.get("valor_total")), "valor", size="small"),
        ], spacing=SPACING_XL, wrap=True)

        children = [header, ft.Container(height=SPACING_LG), cards, ft.Container(height=SPACING_LG)]

        # Desglose por estado de linea si existe la columna
        est_col = self._analytics._estado_col()
        if est_col in self._df.columns:
            children.append(self._bloque_estado(est_col))

        children.append(ft.Text("Lineas de pedido", size=FONT_SIZE_MEDIUM,
                                weight=ft.FontWeight.W_700, color=self.c["text_secondary"]))
        children.append(self._tabla_lineas())

        return ft.Container(
            content=ft.Column(children, spacing=SPACING_LG, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=PADDING_2XL,
        )

    def _bloque_estado(self, est_col: str) -> ft.Control:
        g = (
            self._df.groupby(est_col, dropna=False)
            .agg(
                items=("CAN_PEDIDO", "size"),
                saldo=("saldo", "sum") if "saldo" in self._df else ("CAN_PEDIDO", "sum"),
            )
            .reset_index()
            .rename(columns={est_col: "estado"})
        )
        estado_rows = [
            ft.Row([
                ft.Text(str(r["estado"]) if str(r["estado"]) != "" else "(sin estado)",
                        size=FONT_SIZE_SMALL, color=self.c["text_primary"], expand=True),
                ft.Text(f"{float(r['items']):,.0f} items", size=FONT_SIZE_SMALL,
                        color=self.c["text_secondary"], width=110),
                ft.Text(f"{float(r['saldo']):,.0f} saldo", size=FONT_SIZE_SMALL,
                        color=self.c["kpis"].get("saldo", self.c["text_primary"]), width=110),
            ], spacing=SPACING_MD)
            for _, r in g.iterrows()
        ]
        return ft.Column([
            ft.Text("Desglose por estado de linea", size=FONT_SIZE_MEDIUM,
                    weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            ft.Container(
                content=ft.Column(estado_rows, spacing=SPACING_MD),
                padding=PADDING_LG,
                bgcolor=self.c["surface_sunken"],
                border_radius=RADIUS_LG,
            ),
        ], spacing=SPACING_LG)

    def _tabla_lineas(self) -> ft.Control:
        df = self._df
        sku_col = self._analytics._sku_col()
        nom_col = self._analytics._nombre_col()
        cols: list[tuple[str, str, str | None]] = [(sku_col, "SKU", None)]
        if nom_col in df.columns:
            cols.append((nom_col, "Producto", None))
        if "NOM_ALMACEN" in df.columns:
            cols.append(("NOM_ALMACEN", "Almacen", None))
        cols.extend([
            ("CAN_PEDIDO", "Pedido", "num"),
            ("CAN_DESPACHO", "Desp.", "num"),
        ])
        if "saldo" in df.columns:
            cols.append(("saldo", "Saldo", "num"))
        if "cajas" in df.columns:
            cols.append(("cajas", "Cajas", "num"))
        if "valor_saldo" in df.columns:
            cols.append(("valor_saldo", "Valor S/", "num"))

        return build_tabular_report(self.c, df, cols, page_limit=200)

    @staticmethod
    def _fmt(value) -> str:
        if value is None or (isinstance(value, float) and value != value):
            return "—"
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)