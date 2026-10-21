"""
Dashboard por Vendedor con respuestas ejecutivas.

Responde:
- Que SKU debo, cuanto debo (unidades y soles)
- Cuanto tengo para despachar (stock VES)
- Si hay stock para traslado
- Cajas enteras
- Estado del pedido, planilla anticipo, condicion de pago
- Comparar pedido completo vs vigencias
- Estado de linea (Tradicional/Nuevo)
- Snapshot: comparar hoy vs mañana (seguimiento)
"""

from __future__ import annotations

import logging
from datetime import datetime

import flet as ft
import pandas as pd

from src.core.analytics import PedidosAnalytics
from src.core.snapshot import SnapshotManager, StateLineFilter
from src.config.settings import DATA_DIR
from src.ui.components import build_tabular_report, kpi_card
from src.ui.config import (
    DIALOG_HEIGHT,
    DIALOG_WIDTH,
    DROPDOWN_WIDTH,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_XL,
    MAX_VENDOR_NAME_LENGTH,
    PADDING_2XL,
    PADDING_XS,
    SPACING_2XL,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
    TOP_PAYMENT_CONDITIONS,
    TOP_SKUS_LIMIT,
)

_log = logging.getLogger("g360.pedido_vigencias")


class VendorDashboard:
    """Dashboard de vendedor con respuestas ejecutivas."""

    def __init__(self, page: ft.Page, colors: dict) -> None:
        self.page = page
        self.c = colors
        self._df = None
        self._analytics = None
        self._api_state = "offline"
        self._snapshot_mgr = SnapshotManager(DATA_DIR)
        self._compare_df = None  # DataFrame para comparacion

        # Controles
        self._vendor_dropdown = None
        self._status_text = ft.Text("", size=FONT_SIZE_NORMAL, color=colors["text_muted"])
        self._content_area = ft.Container(expand=True)
        self._snapshot_info = ft.Text("", size=FONT_SIZE_SMALL, color=colors["text_muted"])

        # Badges de estado de línea
        self._state_badges = None
        self._selected_state = "todos"

    def build(self) -> ft.Container:
        """Construye el dashboard de vendedor."""
        self._vendor_dropdown = ft.Dropdown(
            label="Seleccionar Vendedor",
            width=DROPDOWN_WIDTH,
            text_size=FONT_SIZE_MEDIUM,
            options=[],
            on_change=self._on_vendor_change,
        )

        # Badges de estado de línea
        self._state_badges = ft.Row([
            ft.Chip(
                ft.Text(label, size=FONT_SIZE_SMALL),
                on_click=lambda _, key=key: self._on_state_click(key),
                bgcolor=self.c.get(color, self.c["accent"]) if key == "todos" else None,
                selected=(key == "todos"),
                padding=PADDING_XS,
            )
            for key, label, icon, color in [
                ("todos", "Todos", ft.Icons.SELECT_ALL, "accent"),
                ("nuevo", "NUEVO", ft.Icons.NEW_RELEASES, "success"),
                ("tradicional", "TRAD", ft.Icons.HISTORY, "info"),
                ("importado", "IMP", ft.Icons.IMPORT_EXPORT, "warning"),
                ("sin_estado", "—", ft.Icons.HELP_OUTLINE, "text_muted"),
            ]
        ], spacing=SPACING_SM, wrap=True)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    self._vendor_dropdown,
                    ft.Container(expand=True),
                    ft.ElevatedButton(
                        "Snapshot",
                        icon=ft.Icons.CAMERA_ALT,
                        on_click=self._save_snapshot,
                        tooltip="Guardar estado actual para comparar",
                    ),
                    ft.ElevatedButton(
                        "Comparar",
                        icon=ft.Icons.COMPARE_ARROWS,
                        on_click=self._compare_snapshot,
                        tooltip="Comparar con snapshot anterior",
                    ),
                ], spacing=SPACING_LG),
                self._snapshot_info,
                ft.Text("Estado de Línea:", size=FONT_SIZE_NORMAL, color=self.c["text_muted"]),
                self._state_badges,
                ft.Divider(height=1, color=self.c["border"]),
                self._content_area,
            ], spacing=SPACING_LG, expand=True),
            padding=PADDING_2XL,
        )

    def _save_snapshot(self, e):
        """Guarda snapshot del estado actual."""
        if self._df is not None:
            path = self._snapshot_mgr.save_snapshot(self._df, f"snapshot_{datetime.now().strftime('%H%M%S')}")
            self._snapshot_info.value = f"✓ Snapshot guardado: {path.name}"
            self._snapshot_info.update()

    def _compare_snapshot(self, e):
        """Compara snapshots."""
        snapshots = self._snapshot_mgr.list_snapshots()
        if len(snapshots) < 2:
            self._snapshot_info.value = "⚠ Necesitas al menos 2 snapshots"
            self._snapshot_info.update()
            return

        base = snapshots[1]["label"]
        new = snapshots[0]["label"]
        diff = self._snapshot_mgr.compare_snapshots(base, new)
        if not diff.empty:
            self._show_comparison(diff, base, new)

    def _show_comparison(self, diff, base_label, new_label):
        """Muestra comparacion de snapshots."""
        cambios = diff["cambio"].value_counts()
        df_cmp = pd.DataFrame({
            "Cambio": cambios.index.tolist(),
            "Cantidad": cambios.values.tolist(),
        })

        dlg = ft.AlertDialog(
            title=ft.Text(f"Comparación: {base_label} vs {new_label}"),
            content=ft.Container(
                content=build_tabular_report(
                    self.c, df_cmp,
                    [("Cambio", "Cambio", None), ("Cantidad", "Cantidad", "num")],
                    page_limit=20, show_totals=True,
                ),
                width=DIALOG_WIDTH,
                height=DIALOG_HEIGHT,
            ),
        )
        self.page.open(dlg)

    def _on_state_click(self, state: str):
        """Click en badge de estado de línea."""
        self._selected_state = state
        for chip in self._state_badges.controls:
            chip_text = chip.content.value if hasattr(chip.content, "value") else ""
            is_selected = any(
                key == state and chip_text == label
                for key, label, _, _ in [
                    ("todos", "Todos"),
                    ("nuevo", "NUEVO"),
                    ("tradicional", "TRAD"),
                    ("importado", "IMP"),
                    ("sin_estado", "—"),
                ]
            )
            chip.bgcolor = self.c["accent"] if is_selected else None
            chip.selected = is_selected
        self._state_badges.update()
        # Refrescar dashboard con filtro
        if self._vendor_dropdown.value:
            self._show_vendor_dashboard(self._vendor_dropdown.value)

    def update_data(self, df, api_state="offline"):
        """Actualiza datos y lista vendedores."""
        _log.info("[VendorDashboard] update_data: filas=%d, api_state=%s", len(df) if df is not None else 0, api_state)
        self._df = df
        self._analytics = PedidosAnalytics(df) if df is not None and not df.empty else None
        self._api_state = api_state

        # Llenar dropdown de vendedores
        if df is not None and "ID_VENDEDOR" in df.columns:
            vendors = df.groupby("ID_VENDEDOR").agg(
                nombre=("NOM_VENDEDOR", "first"),
                filas=("ID_PEDIDO", "count"),
            ).reset_index().sort_values("filas", ascending=False)
            _log.info("[VendorDashboard] update_data: %d vendedores encontrados", len(vendors))

            self._vendor_dropdown.options = [
                ft.dropdown.Option(
                    row["ID_VENDEDOR"],
                    f"{row['ID_VENDEDOR']} - {row['nombre'][:MAX_VENDOR_NAME_LENGTH]} ({row['filas']})"
                )
                for _, row in vendors.iterrows()
            ]
            # Solo actualizar si el control ya esta montado en la pagina
            if self._vendor_dropdown.page is not None:
                self._vendor_dropdown.update()
                _log.info("[VendorDashboard] Dropdown actualizado")
        else:
            _log.warning("[VendorDashboard] update_data: df sin ID_VENDEDOR")

    def _on_vendor_change(self, e):
        """Cuando se selecciona un vendedor."""
        vendor_id = e.control.value
        _log.info("[VendorDashboard] Cambio vendedor seleccionado: %s", vendor_id)
        if vendor_id and self._analytics:
            self._show_vendor_dashboard(vendor_id)

    def _show_vendor_dashboard(self, vendor_id: str):
        """Muestra el dashboard completo del vendedor."""
        _log.info("[VendorDashboard] Mostrando dashboard vendedor: %s", vendor_id)
        df = self._df[self._df["ID_VENDEDOR"] == vendor_id].copy()
        if df.empty:
            _log.warning("[VendorDashboard] Vendedor %s sin filas", vendor_id)
            return

        # Aplicar filtro de estado de línea
        mask = StateLineFilter.get_filter_mask(df, self._selected_state)
        df = df[mask]

        nombre = df["NOM_VENDEDOR"].iloc[0]
        df["saldo"] = df["CAN_PEDIDO"] - df["CAN_DESPACHO"]

        # === KPI PRINCIPALES ===
        con_saldo = df[df["saldo"] > 0]
        total_pedido = df["CAN_PEDIDO"].sum()
        total_despachado = df["CAN_DESPACHO"].sum()
        total_saldo = df["saldo"].sum()
        valor_total = df["PEDIDO_IMPORTE_ARITCULO"].sum()
        valor_saldo = con_saldo["PEDIDO_IMPORTE_ARITCULO"].sum()

        kpis = ft.Row([
            kpi_card(self.c, "Pedidos", f"{df['ID_PEDIDO'].nunique()}", "kpis"),
            kpi_card(self.c, "Saldo Units", f"{total_saldo:,.0f}", "saldo"),
            kpi_card(self.c, "Valor S/", f"{valor_saldo:,.0f}", "valor"),
            kpi_card(self.c, "% Atendido", f"{total_despachado/max(total_pedido,1)*100:.1f}%", "porcentaje"),
        ], spacing=SPACING_2XL, wrap=True)

        # === ESTADO PEDIDOS ===
        aprobados = (df["PEDIDO_ESTADO"] == "APROBADO").sum()
        ingresados = (df["PEDIDO_ESTADO"] == "INGRESADO").sum()

        estado_row = ft.Row([
            kpi_card(self.c, "Aprobados", f"{aprobados}", "success"),
            kpi_card(self.c, "Ingresados", f"{ingresados}", "warning"),
        ], spacing=SPACING_2XL, wrap=True)

        # === TOP SKUs CON SALDO ===
        top_skus = con_saldo.groupby(["ID_ARTICULO", "NOM_ARTICULO"]).agg(
            saldo=("saldo", "sum"),
            valor=("PEDIDO_IMPORTE_ARITCULO", "sum"),
            aprobados=("PEDIDO_ESTADO", lambda x: (x == "APROBADO").sum()),
            pendientes=("PEDIDO_ESTADO", lambda x: (x == "INGRESADO").sum()),
        ).sort_values("saldo", ascending=False).head(TOP_SKUS_LIMIT)

        sku_table = self._build_sku_table(top_skus)

        # === ALMACENES (TRASLADOS) ===
        almacenes = df.groupby("NOM_ALMACEN").agg(
            saldo=("saldo", "sum"),
            stock=("STK_DISPONIBLE", "sum"),
        ).reset_index()

        alma_table = self._build_almacen_table(almacenes)

        # === CONDICIONES DE PAGO ===
        cond_pago = df.groupby("CONDICION_PAGO").agg(
            filas=("ID_PEDIDO", "count"),
            valor=("PEDIDO_IMPORTE_ARITCULO", "sum"),
        ).sort_values("valor", ascending=False).head(TOP_PAYMENT_CONDITIONS)

        pago_table = self._build_pago_table(cond_pago)

        # === PLANILLAS DE ANTICIPO ===
        planillas = df[df["ID_PLANILLA_ANTICIPO"].notna()]
        planilla_text = f"Planillas: {planillas['ID_PLANILLA_ANTICIPO'].nunique()}" if len(planillas) > 0 else "Sin planillas"

        # === ARMAR DASHBOARD ===
        self._content_area.content = ft.Column([
            ft.Text(f"Vendedor: {vendor_id} - {nombre}", size=FONT_SIZE_XL, weight=ft.FontWeight.W_700, color=self.c["text_primary"]),
            ft.Container(height=SPACING_LG),
            ft.Text("Resumen Ejecutivo", size=FONT_SIZE_MEDIUM, weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            kpis,
            estado_row,
            ft.Container(height=SPACING_2XL),
            ft.Text(f"Top SKUs con Saldo Pendiente | {planilla_text}", size=FONT_SIZE_MEDIUM, weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            sku_table,
            ft.Container(height=SPACING_2XL),
            ft.Text("Distribucion por Almacen (Traslados)", size=FONT_SIZE_MEDIUM, weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            alma_table,
            ft.Container(height=SPACING_2XL),
            ft.Text("Condiciones de Pago", size=FONT_SIZE_MEDIUM, weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            pago_table,
        ], spacing=SPACING_LG, scroll=ft.ScrollMode.AUTO, expand=True)

        self._content_area.update()
        _log.info("[VendorDashboard] Dashboard vendedor %s mostrado OK", vendor_id)

    def _build_sku_table(self, df) -> ft.Container:
        """Tabla de SKUs con saldo."""
        d = df.reset_index()
        cols = [
            ("ID_ARTICULO", "SKU", None),
            ("NOM_ARTICULO", "Nombre", None),
            ("saldo", "Saldo", "num"),
            ("valor", "Valor S/", "num"),
            ("aprobados", "Aprob", "num"),
            ("pendientes", "Pend", "num"),
        ]
        return build_tabular_report(
            self.c, d, cols, page_limit=len(d),
            color_overrides={"saldo": "error", "aprobados": "success", "pendientes": "warning"},
        )

    def _build_almacen_table(self, df) -> ft.Container:
        """Tabla de almacenes."""
        cols = [("NOM_ALMACEN", "Almacen", None), ("saldo", "Saldo", "num"), ("stock", "Stock", "num")]
        return build_tabular_report(self.c, df, cols)

    def _build_pago_table(self, df) -> ft.Container:
        """Tabla de condiciones de pago."""
        d = df.reset_index()
        cols = [("CONDICION_PAGO", "Condicion", None), ("filas", "Filas", "num"), ("valor", "Valor S/", "num")]
        return build_tabular_report(self.c, d, cols)

    def update_theme(self, colors: dict):
        self.c = colors
