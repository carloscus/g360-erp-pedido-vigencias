"""
Panel de vistas del sidebar.

Cada botón aplica un pre-filtro al dataset y navega a la vista correspondiente.
Los botones están agrupados por criterio de presentación:
  - Pedidos:   Por Pedido (con indicador de traslado), Por Línea
  - Análisis:  Por Vendedor, Por Cliente, Por Producto, Por Almacén,
               Por Categoría, Por Estado de Línea
  - Resumen:   Dashboard, Stock QC
  - Monitor:   Resumen, Alertas, Estadísticas, Histórico, Buscar,
               Grupos, Cola Despacho, Configuración

La tabla principal tiene filtros por columna (texto libre) independientes
de este panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import flet as ft

from src.ui.config import (
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    PADDING_LG,
    PADDING_SM,
    RADIUS_SM,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)

_log = logging.getLogger("g360.pedido_vigencias")


@dataclass(frozen=True)
class ViewDef:
    """Definicion declarativa de un tipo de vista."""

    nav_id: str
    label: str
    icon: str
    tooltip: str = ""


@dataclass(frozen=True)
class ViewGroup:
    """Grupo de vistas con un criterio comun (Resumen, Pedidos, Analisis)."""

    title: str
    icon: str
    views: tuple[ViewDef, ...]


# Grupos de vistas por criterio de presentacion.
# Data principal: XLSX cargado manualmente (lineas de pedido).
# Data complementaria (APIs): stock por almacen, maestros de cliente/vendedor/catalogo.
VIEW_GROUPS: list[ViewGroup] = [
    ViewGroup(
        title="Pedidos",
        icon=ft.Icons.ASSIGNMENT,
        views=(
            ViewDef("pedido", "Por Pedido", ft.Icons.RECEIPT_LONG,
                    "Detalle por pedido con indicador de traslado (stock por almacen)"),
            ViewDef("detalle", "Por Linea", ft.Icons.LIST_ALT,
                    "Cada linea del XLSX con su stock por almacen"),
        ),
    ),
    ViewGroup(
        title="Analisis",
        icon=ft.Icons.ANALYTICS,
        views=(
            ViewDef("vendedor", "Por Vendedor", ft.Icons.PERSON, "Agrupado por vendedor"),
            ViewDef("cliente", "Por Cliente", ft.Icons.PEOPLE, "Agrupado por cliente"),
            ViewDef("producto", "Por Producto", ft.Icons.INVENTORY_2, "Agrupado por producto/SKU"),
            ViewDef("almacen", "Por Almacen", ft.Icons.WAREHOUSE,
                    "Stock por almacen (VES/121/otros) vs pendiente"),
            ViewDef("categoria", "Por Categoria", ft.Icons.PIE_CHART, "Agrupado por categoria"),
            ViewDef("estado_linea", "Por Estado de Linea", ft.Icons.RULE, "Agrupado por estado de linea"),
        ),
    ),
    ViewGroup(
        title="Resumen",
        icon=ft.Icons.SUMMARIZE,
        views=(
            ViewDef("dashboard", "Dashboard", ft.Icons.DASHBOARD, "Vista general con KPIs"),
            ViewDef("alerts", "Stock QC", ft.Icons.WARNING_AMBER,
                    "SKUs con saldo > 5000 en VES (espera liberacion)"),
        ),
    ),
    ViewGroup(
        title="Monitor",
        icon=ft.Icons.MONITOR_HEART,
        views=(
            ViewDef("resumen", "Resumen", ft.Icons.QUERY_STATS,
                    "KPIs globales/segmentados con estado de stock (API)"),
            ViewDef("alertas", "Alertas", ft.Icons.NOTIFICATIONS,
                    "Vencidos, por vencer, 100% atendible, sin stock, sin catalogo"),
            ViewDef("estadisticas", "Estadisticas", ft.Icons.BAR_CHART,
                    "A quien le debemos, pedidos cerca del 100% y SKUs mas necesitados"),
            ViewDef("historico", "Historico", ft.Icons.HISTORY,
                    "Evolucion de entregas entre snapshots por pedido"),
            ViewDef("buscar", "Buscar", ft.Icons.SEARCH,
                    "Busqueda por pedido, OC, vendedor o cliente"),
            ViewDef("grupos", "Grupos", ft.Icons.GROUPS,
                    "Grupos de prioridad de clientes o vendedores"),
            ViewDef("cola", "Cola Despacho", ft.Icons.LOCAL_SHIPPING,
                    "Pedidos listos para despacho manual (ID_PEDIDO)"),
            ViewDef("config", "Configuracion", ft.Icons.SETTINGS,
                    "Umbrales de alerta, snapshots y credenciales del API"),
        ),
    ),
    ViewGroup(
        title="Seguimiento",
        icon=ft.Icons.FLAG_CIRCLE,
        views=(
            ViewDef("prioridades", "Prioridades", ft.Icons.PRIORITY_HIGH,
                    "Prioridad, anclas y observaciones persistentes por pedido o cliente"),
        ),
    ),
]


# Lista plana de todas las vistas (compatibilidad con codigo existente).
VIEWS: list[ViewDef] = [v for g in VIEW_GROUPS for v in g.views]


class FiltersPanel:
    """Panel de vistas agrupadas por criterio de presentacion."""

    def __init__(self, colors: dict, on_view_change: callable):
        self.c = colors
        self._on_view_change = on_view_change
        self._view_buttons: dict[str, ft.Container] = {}
        self._active_view: str | None = None
        self.state: dict = {"view": None}

    def build(self) -> ft.Container:
        """Construye el panel de vistas agrupadas."""
        group_controls: list[ft.Control] = []
        for idx, group in enumerate(VIEW_GROUPS):
            if idx > 0:
                group_controls.append(
                    ft.Container(height=SPACING_MD)
                )
            group_controls.append(self._group_header(group))
            for view in group.views:
                group_controls.append(self._view_button(view))

        return ft.Container(
            content=ft.Column(group_controls, spacing=SPACING_SM, tight=True),
            padding=PADDING_LG,
        )

    def _group_header(self, group: ViewGroup) -> ft.Control:
        """Encabezado de grupo con icono y titulo."""
        return ft.Row([
            ft.Icon(group.icon, size=FONT_SIZE_TINY + 1, color=self.c["accent"], opacity=0.8),
            ft.Text(
                group.title.upper(),
                size=FONT_SIZE_TINY,
                weight=ft.FontWeight.W_700,
                color=self.c["text_muted"],
            ),
        ], spacing=SPACING_SM, tight=True)

    def _view_button(self, v: ViewDef) -> ft.Container:
        is_active = self._active_view == v.nav_id
        ctrl = ft.Container(
            content=ft.Row([
                ft.Icon(v.icon, size=FONT_SIZE_NORMAL,
                        color=self.c["accent"] if is_active else self.c["text_muted"]),
                ft.Text(v.label, size=FONT_SIZE_SMALL,
                        color=self.c["text_primary"] if is_active else self.c["text_muted"],
                        weight=ft.FontWeight.W_700 if is_active else ft.FontWeight.W_500),
            ], spacing=SPACING_SM, tight=True),
            padding=PADDING_SM,
            border_radius=RADIUS_SM,
            bgcolor=self.c["surface_variant"] if is_active else None,
            tooltip=v.tooltip,
            on_click=lambda _, vid=v.nav_id: self._on_click(vid),
            ink=True,
        )
        self._view_buttons[v.nav_id] = ctrl
        return ctrl

    def _on_click(self, nav_id: str) -> None:
        _log.info("[Filters] view click: %s", nav_id)
        self.set_active(nav_id)
        if self._on_view_change:
            self._on_view_change(nav_id)

    def set_active(self, nav_id: str | None) -> None:
        """Resalta el boton de vista activo."""
        self._active_view = nav_id
        self.state["view"] = nav_id
        for vid, ctrl in self._view_buttons.items():
            active = vid == nav_id
            ctrl.bgcolor = self.c["surface_variant"] if active else None
            ctrl.content.controls[0].color = self.c["accent"] if active else self.c["text_muted"]
            ctrl.content.controls[1].color = self.c["text_primary"] if active else self.c["text_muted"]
            ctrl.content.controls[1].weight = ft.FontWeight.W_700 if active else ft.FontWeight.W_500
            if getattr(ctrl, "page", None) is not None:
                try:
                    ctrl.update()
                except Exception:
                    pass

    def set_options(self, **_kwargs) -> None:
        """No-op: las vistas no tienen opciones dinamicas."""
        pass

    def reset(self) -> None:
        """No-op de compatibilidad."""
        pass

    def _safe_update(self, control: ft.Control) -> None:
        """Actualiza un control solo si esta adjunto a la pagina."""
        if control is not None and getattr(control, "page", None) is not None:
            try:
                control.update()
            except Exception as ex:
                _log.warning("[Filters] _safe_update fallo: %s", ex)
