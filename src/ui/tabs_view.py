"""
Vista principal del dashboard: drill-down de 3 niveles sobre el dataset.

Estructura (navegacion por click en filas, sin dropdowns):
- KPI cards (resumen del nivel actual)
- Breadcrumb clickeable (Dashboard > Vendedor > Cliente > Linea)
- Selector de dimension raiz (segmentado, oculto en niveles hijos)
- Tabla maestra con filtros por columna y headers clickeables para sort

Drill-down: el click en una fila de un nivel agrupado (Vendedor/Cliente/Producto)
agrega un nivel al stack y refiltra el DataFrame. KPIs se recalculan en cada nivel.
"""

from __future__ import annotations

import logging
from typing import Callable

import flet as ft

from src.core.analytics import PedidosAnalytics
from src.ui.components import build_master_table, empty_state, kpi_card
from src.ui.config import (
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    PADDING_SM,
    RADIUS_SM,
    SPACING_2XL,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    TABLE_PAGE_SIZE,
)

_log = logging.getLogger("g360.pedido_vigencias")

# Dimension raiz: lista simple de vendedores (drill: vendedor → cliente → pedido → sku)
DIMENSIONS: list[tuple[str, str, str, str]] = [
    (
        "vendedor",
        "Vendedores",
        "Vigencia por vendedor — click en nombre para ver clientes",
        ft.Icons.PERSON,
    ),
]

# Columnas por dimension — limpias para el drill vendedor→cliente→pedido→sku
COLUMNS_BY_DIM: dict[str, list[tuple[str, str, str | None]]] = {
    "detalle": [
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("valor_saldo", "Valor S/", "num"),
        ("stock_api_ves", "Stock VES", "num"),
    ],
    "pedido_sku": [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("ID_VENDEDOR", "ID Vend.", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("CONDICION_PAGO", "Condicion", None),
        ("pedido", "Pedido", "num"),
        ("despacho", "Despachado", "num"),
        ("saldo", "Pendiente", "num"),
        ("cajas", "Cajas", "num"),
        ("por_atendido", "% Atend.", "num"),
        ("estado", "Estado", None),
        ("stock_VES", "Stock VES", "num"),
        ("stock_121", "Stock 121", "num"),
        ("disp_cub_VES", "Disp. Cubierto", "num"),
        ("valor", "Valor S/", "num"),
    ],
    "vendedor": [
        ("ID_VENDEDOR", "Cod.", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("items", "Lineas", "num"),
        ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"),
    ],
    "vendedor_cliente": [
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("items", "Lineas", "num"),
        ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"),
    ],
    "cliente": [
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("items", "Lineas", "num"),
        ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"),
    ],
    "producto": [
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("categoria", "Categoria", None),
        ("items", "Lineas", "num"),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Vig. Total", "num"),
        ("cajas", "Cajas", "num"),
        ("valor_saldo", "Valor S/", "num"),
        ("stock_VES", "Stock VES", "num"),
        ("stock_121", "Stock 121", "num"),
        ("disp_cub_VES", "Disp. Cubierto", "num"),
    ],
    "pedido": [
        ("ID_PEDIDO", "Pedido", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("items", "Lineas", "num"),
        ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"),
        ("estado", "Estado", None),
    ],
    "almacen": [
        ("NOM_ALMACEN", "Almacen", None),
        ("items", "Items", "num"),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor_saldo", "Valor S/", "num"),
    ],
    "categoria": [
        ("categoria", "Categoria", None),
        ("items", "Items", "num"),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor_saldo", "Valor S/", "num"),
    ],
    "estado_linea": [
        ("estado_linea", "Estado Linea", None),
        ("items", "Lineas", "num"),
        ("pedido", "Pedido", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor", "Valor S/", "num"),
    ],
}

# Configuracion del drill-down por nivel.
# Cada nivel sabe que columna se usa como drill key y a que nivel se llega.
# driller es la key de dimension a la que se navega al hacer click en una fila.
DRILL_CONFIG: dict[str, dict] = {
    "pedido_sku": {
        "next": "linea",
        "key_col": "ID_PEDIDO",
        "label_col": "ID_PEDIDO",
        "filter_method": "get_lineas_filtradas_id_pedido",
    },
    "vendedor": {
        "next": "vendedor_cliente",
        "key_col": "ID_VENDEDOR",
        "label_col": "NOM_VENDEDOR",
        "filter_method": "get_clientes_by_vendedor",
    },
    "vendedor_cliente": {
        "next": "pedido",
        "key_col": "COD_CLIENTE",
        "label_col": "NOM_CLIENTE",
        "filter_method": "get_lineas_filtradas_vendedor_cliente",
    },
    "cliente": {
        "next": "pedido",
        "key_col": "COD_CLIENTE",
        "label_col": "NOM_CLIENTE",
        "filter_method": "get_lineas_filtradas_cliente",
    },
    "pedido": {
        "next": "linea",
        "key_col": "ID_PEDIDO",
        "label_col": "ID_PEDIDO",
        "filter_method": "get_lineas_filtradas_id_pedido",
    },
    "producto": {
        "next": "linea",
        "key_col": "SKU",
        "label_col": "NOM_ARTICULO",
        "filter_method": "get_lineas_filtradas_sku",
    },
    "almacen": {
        "next": "linea",
        "key_col": "NOM_ALMACEN",
        "label_col": "NOM_ALMACEN",
        "filter_method": "get_lineas_filtradas_almacen",
    },
    "categoria": {
        "next": "linea",
        "key_col": "categoria",
        "label_col": "categoria",
        "filter_method": "get_lineas_filtradas_categoria",
    },
    "estado_linea": {
        "next": "linea",
        "key_col": "estado_linea",
        "label_col": "estado_linea",
        "filter_method": "get_lineas_filtradas_estado",
    },
    "linea": {
        "next": None,
        "key_col": None,
        "label_col": None,
        "filter_method": None,
    },
}


class TabsView:
    """Vista principal con drill-down de 3 niveles y tabla maestra."""

    def __init__(
        self,
        page: ft.Page,
        colors: dict,
        on_open_detail: Callable | None = None,
    ) -> None:
        self.page = page
        self.c = colors
        self._on_open_detail = on_open_detail

        self._df = None
        self._analytics: PedidosAnalytics | None = None
        self._api_state = "offline"

        self._dimension: str = "vendedor"
        self._filter_values: dict[str, str] = {}
        self._sort_col: str | None = None
        self._sort_desc: bool = False
        self._pre_filter: str | None = None
        self._sort_chip_active: bool = False
        self._cond_familia: str | None = None  # chip de condicion de pago (familia)

        # Stack de drill-down: lista de niveles navegados.
        # Nivel 0 = raiz (dimension agrupada). Cada nivel hijo guarda su df filtrado.
        # Cada item: {"dim": str, "key": any, "label": str, "parent_key": any, "df": DataFrame}
        self._drill_stack: list[dict] = []
        # Columnas marcadas como drillable (clickeables) por nivel
        self._drill_cols: set[str] = set()

        self._dimension_segment: ft.Control | None = None
        self._kpis_row: ft.Control | None = None
        self._breadcrumb_row: ft.Control | None = None
        self._sort_chip_row: ft.Control | None = None
        self._cond_chip_row: ft.Control | None = None
        self._table_container: ft.Container = ft.Container(expand=True)
        self._root: ft.Container = ft.Container(expand=True)

    # ---------------------------------------------------------------
    # Build
    # ---------------------------------------------------------------
    def build(self) -> ft.Container:
        """Construye el contenedor raiz — limpio: breadcrumb + KPIs + tabla."""
        self._kpis_row = self._build_kpis_row()
        self._breadcrumb_row = self._build_breadcrumb()
        self._table_container.content = self._build_table()

        self._root = ft.Container(
            content=ft.Column(
                [
                    self._kpis_row,
                    self._breadcrumb_row,
                    self._table_container,
                ],
                spacing=SPACING_MD,
                expand=True,
            ),
            expand=True,
        )
        return self._root

    def _build_dimension_segment(self) -> ft.Control:
        """Selector de dimension con iconos (segmented control). Solo visible en raiz."""

        def make_btn(dim_id: str, label: str, tooltip: str, icon) -> ft.Container:
            is_active = self._dimension == dim_id
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            icon,
                            size=12,
                            color=self.c["accent"] if is_active else self.c["text_muted"],
                        ),
                        ft.Text(
                            label,
                            size=FONT_SIZE_SMALL,
                            weight=ft.FontWeight.W_700 if is_active else ft.FontWeight.W_500,
                            color=self.c["text_primary"] if is_active else self.c["text_muted"],
                        ),
                    ],
                    spacing=5,
                    tight=True,
                ),
                padding=ft.Padding(10, 6, 10, 6),
                border_radius=6,
                bgcolor=self.c["surface_variant"] if is_active else None,
                tooltip=tooltip,
                on_click=lambda _, d=dim_id: self._set_dimension(d),
                ink=True,
            )

        visible = self._drill_stack == []
        return ft.Row(
            controls=[make_btn(d, l, t, ic) for d, l, t, ic in DIMENSIONS],
            spacing=SPACING_MD,
            wrap=True,
            visible=visible,
        )

    def _build_breadcrumb(self) -> ft.Control:
        """Breadcrumb clickeable: Dashboard > Vendedor > Cliente > Linea."""
        if self._drill_stack == []:
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HOME, size=12, color=self.c["text_muted"]),
                        ft.Text("Vista general", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )

        crumbs: list[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HOME, size=11, color=self.c["text_muted"]),
                        ft.Text("Vista general", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                    ],
                    spacing=4,
                    tight=True,
                ),
                on_click=lambda _: self._drill_to(None),
                ink=True,
                padding=ft.Padding(4, 2, 4, 2),
            )
        ]
        for i, level in enumerate(self._drill_stack):
            crumbs.append(ft.Text(">", size=FONT_SIZE_TINY, color=self.c["text_muted"]))
            label = str(level.get("label", ""))
            # Truncar label largo
            short = label if len(label) <= 28 else label[:25] + "..."
            crumbs.append(
                ft.Container(
                    content=ft.Text(
                        short,
                        size=FONT_SIZE_TINY,
                        weight=ft.FontWeight.W_700,
                        color=self.c["accent"]
                        if i == len(self._drill_stack) - 1
                        else self.c["text_secondary"],
                    ),
                    on_click=lambda _, idx=i: self._drill_to(idx),
                    ink=True,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        return ft.Container(
            content=ft.Row(crumbs, spacing=4, tight=True, wrap=True),
            padding=ft.Padding(0, 0, 0, 0),
        )

    def _build_sort_chip(self) -> ft.Control:
        """Chip de ordenamiento rapido por disponible cubierto."""
        is_active = self._sort_chip_active
        icon_color = self.c["success"] if is_active else self.c["text_muted"]
        chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SORT, size=12, color=icon_color),
                    ft.Text(
                        "Disp. Cubierto" if is_active else "Sin ordenar",
                        size=FONT_SIZE_TINY,
                        weight=ft.FontWeight.W_700 if is_active else ft.FontWeight.W_500,
                        color=icon_color,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.Padding(10, 5, 10, 5),
            border_radius=RADIUS_SM,
            bgcolor=self.c["surface_variant"] if is_active else None,
            border=ft.BorderSide(1, self.c["success"] if is_active else self.c["border"]),
            tooltip="Ordenar por Disponible Cubierto (desc)",
            ink=True,
            on_click=lambda _: self._toggle_sort_chip(),
        )
        return chip

    def _toggle_sort_chip(self) -> None:
        self._sort_chip_active = not self._sort_chip_active
        if self._sort_chip_active:
            self._sort_col = "disp_cub_VES"
            self._sort_desc = True
        else:
            self._sort_col = None
            self._sort_desc = False
        self._soft_refresh()

    def _build_cond_chips(self) -> ft.Control:
        """Chips de condicion de pago (familia normalizada) para filtrar."""
        if self._df is None or "cond_familia" not in self._df.columns:
            return ft.Container()

        from src.core.analytics import COND_FAMILIA_ORDER

        presentes = [
            c
            for c in COND_FAMILIA_ORDER
            if c in set(self._df["cond_familia"].dropna().astype(str).unique())
        ]

        def make_chip(label: str, key: str | None, color_key: str = "accent") -> ft.Container:
            is_active = self._cond_familia == key
            border_color = self.c[color_key] if is_active else self.c["border"]
            txt_color = (
                self.c.get(color_key, self.c["accent"]) if is_active else self.c["text_muted"]
            )
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.CHECK if is_active else ft.Icons.FILTER_ALT,
                            size=10,
                            color=txt_color,
                        ),
                        ft.Text(
                            label,
                            size=FONT_SIZE_TINY,
                            weight=ft.FontWeight.W_700 if is_active else ft.FontWeight.W_500,
                            color=txt_color,
                        ),
                    ],
                    spacing=3,
                    tight=True,
                ),
                padding=ft.Padding(8, 3, 8, 3),
                border_radius=RADIUS_SM,
                bgcolor=self.c["surface_variant"] if is_active else None,
                border=ft.BorderSide(1, border_color),
                tooltip=f"Filtrar por {label}",
                ink=True,
                on_click=lambda _, k=key: self._set_cond(k),
            )

        chips = [make_chip("Cond: TODAS", None)]
        for fam in presentes:
            color_key = "warning" if fam == "CANJE" else "accent"
            chips.append(make_chip(fam, fam, color_key))
        return ft.Container(
            content=ft.Row(chips, spacing=SPACING_SM, wrap=True),
            visible=bool(presentes),
        )

    def _set_cond(self, familia: str | None) -> None:
        self._cond_familia = familia
        self._filter_values = {}
        self._refresh()

    def _build_kpis_row(self) -> ft.Control:
        """Fila de KPI cards (resumen del nivel actual del drill-down)."""
        level_df = self._current_level_df()
        if level_df is None or level_df.empty:
            return ft.Container()
        try:
            analytics = PedidosAnalytics(level_df)
            kpis = analytics.get_kpis()
        except Exception as ex:
            _log.warning("[TabsView] _build_kpis_row fallo: %s", ex)
            return ft.Container()
        return ft.Row(
            [
                kpi_card(self.c, "Items", f"{(kpis.get('total_items') or 0):,}", "items"),
                kpi_card(self.c, "Saldo", f"{(kpis.get('saldo_total') or 0):,.0f}", "saldo"),
                kpi_card(self.c, "Valor S/", f"{(kpis.get('valor_total') or 0):,.0f}", "valor"),
                kpi_card(self.c, "Cajas", f"{(kpis.get('cajas_total') or 0):,.0f}", "cajas"),
                kpi_card(
                    self.c,
                    "Despacho",
                    f"{((kpis.get('total_despachado') or 0) / max((kpis.get('total_pedido') or 1), 1) * 100):.1f}%",
                    "porcentaje",
                ),
            ],
            spacing=SPACING_2XL,
            wrap=True,
        )

    def _current_level_df(self):
        """Devuelve el DataFrame del nivel actual del drill-down."""
        if self._df is None:
            return None
        if self._drill_stack:
            df = self._drill_stack[-1].get("df", self._df)
        else:
            df = self._apply_pre_filter(self._df)
        if df is not None and self._cond_familia and "cond_familia" in df.columns:
            df = df[df["cond_familia"] == self._cond_familia].reset_index(drop=True)
        return df

    def _build_table(self) -> ft.Control:
        """Construye la tabla maestra del nivel actual — vendedor usa tree."""
        if self._analytics is None or self._df is None:
            return empty_state(self.c)

        # Tree limpio para la raiz vendedor -> cliente
        if self._dimension == "vendedor" and not self._drill_stack:
            tree = self._build_vendor_tree()
            if tree is not None:
                return tree

        columns = COLUMNS_BY_DIM.get(self._dimension, COLUMNS_BY_DIM["detalle"])
        level_df = self._current_level_df()
        grouped_df = self._group_level(level_df, self._dimension)

        drillable = set()
        cfg = DRILL_CONFIG.get(self._dimension, {})
        if cfg.get("next") and cfg.get("key_col"):
            drillable.add(cfg["key_col"])
        self._drill_cols = drillable

        return build_master_table(
            self.c,
            grouped_df,
            columns=columns,
            filter_values=self._filter_values,
            sort_col=self._sort_col,
            sort_desc=self._sort_desc,
            on_filter_change=self._on_filter_change,
            on_sort_change=self._on_sort_change,
            on_clear_filters=self._on_clear_filters,
            on_row_click=self._on_row_click,
            drillable_cols=self._drill_cols,
            page_limit=TABLE_PAGE_SIZE,
        )

    def _build_vendor_tree(self) -> ft.Control | None:
        """Arbol vendedor → cliente (2 niveles visibles, fuente 13-14)."""
        level_df = self._current_level_df()
        if level_df is None or level_df.empty:
            return None
        try:
            vendors = self._group_level(level_df, "vendedor")
        except Exception:
            return None
        if vendors is None or vendors.empty:
            return None

        v_col = self._analytics._vendedor_col() if self._analytics else "ID_VENDEDOR"
        c_col = self._analytics._cliente_col() if self._analytics else "COD_CLIENTE"

        tiles: list[ft.Control] = []
        for _, v in vendors.iterrows():
            vid = str(v.get("ID_VENDEDOR", v.get(v_col, "")))
            vname = str(v.get("NOM_VENDEDOR", vid))
            items = int(v.get("items", 0) or 0)
            saldo = float(v.get("saldo", 0) or 0)
            valor = float(v.get("valor", 0) or 0)

            # Clientes de este vendedor
            try:
                sub = (
                    level_df[level_df[v_col].astype(str) == vid]
                    if v_col in level_df.columns
                    else level_df
                )
                cli_df = PedidosAnalytics(sub).get_by_cliente() if not sub.empty else sub
            except Exception:
                cli_df = None

            client_controls: list[ft.Control] = []
            if cli_df is not None and not cli_df.empty:
                for _, cl in cli_df.iterrows():
                    cid = str(cl.get("COD_CLIENTE", cl.get(c_col, "")))
                    cname = str(cl.get("NOM_CLIENTE", cid))
                    c_items = int(cl.get("items", 0) or 0)
                    c_saldo = float(cl.get("saldo", 0) or 0)
                    # Fila cliente clickeable → pedidos
                    client_controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.PEOPLE, size=14, color=self.c["text_muted"]),
                                    ft.Text(
                                        cname,
                                        size=13,
                                        weight=ft.FontWeight.W_600,
                                        color=self.c["text_primary"],
                                        expand=True,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(cid, size=11, color=self.c["text_muted"]),
                                    ft.Text(f"{c_items} lin", size=11, color=self.c["text_muted"]),
                                    ft.Text(
                                        f"{c_saldo:,.0f} saldo",
                                        size=11,
                                        color=self.c["accent"],
                                        weight=ft.FontWeight.W_700,
                                    ),
                                    ft.Icon(
                                        ft.Icons.CHEVRON_RIGHT, size=14, color=self.c["text_muted"]
                                    ),
                                ],
                                spacing=8,
                                tight=True,
                            ),
                            padding=ft.Padding(12, 8, 12, 8),
                            bgcolor=self.c["surface"],
                            border_radius=RADIUS_SM,
                            border=ft.BorderSide(1, self.c["border"]),
                            ink=True,
                            on_click=lambda _, _vid=vid, _cid=cid, _cn=cname: (
                                self._on_tree_client_click(_vid, _cid, _cn)
                            ),
                        )
                    )
            if not client_controls:
                client_controls = [ft.Text("Sin clientes", size=12, color=self.c["text_muted"])]

            tiles.append(
                ft.ExpansionTile(
                    title=ft.Row(
                        [
                            ft.Icon(ft.Icons.PERSON, size=16, color=self.c["accent"]),
                            ft.Text(
                                vname,
                                size=14,
                                weight=ft.FontWeight.W_700,
                                color=self.c["text_primary"],
                                expand=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    f"{items} lin · {saldo:,.0f} · S/ {valor:,.0f}",
                                    size=11,
                                    color=self.c["text_muted"],
                                ),
                                padding=ft.Padding(6, 2, 6, 2),
                                bgcolor=self.c["surface_variant"],
                                border_radius=RADIUS_SM,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    subtitle=ft.Text(
                        f"Cod {vid} · click para expandir clientes",
                        size=11,
                        color=self.c["text_muted"],
                    ),
                    controls=client_controls,
                    collapsed_text_color=self.c["text_muted"],
                    text_color=self.c["text_primary"],
                    bgcolor=self.c["surface"],
                    collapsed_bgcolor=self.c["surface"],
                    icon_color=self.c["accent"],
                )
            )

        return ft.Container(
            content=ft.Column(tiles, spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True,
        )

    def _on_tree_client_click(self, vendor_id: str, client_id: str, client_name: str) -> None:
        """Click en cliente del tree → drill directo a pedidos de ese cliente."""
        level_df = self._current_level_df()
        if level_df is None or self._analytics is None:
            return
        v_col = self._analytics._vendedor_col()
        c_col = self._analytics._cliente_col()
        sub = level_df
        if v_col in sub.columns:
            sub = sub[sub[v_col].astype(str) == str(vendor_id)]
        if c_col in sub.columns:
            sub = sub[sub[c_col].astype(str) == str(client_id)]
        sub = sub.reset_index(drop=True)
        if sub.empty:
            return
        # Push vendedor_cliente level si no estamos ya, luego pedido
        # Simplificado: ir directo a pedido con las lineas filtradas
        level = {
            "dim": "pedido",
            "key": str(client_id),
            "label": client_name,
            "key_col": c_col,
            "df": sub,
        }
        self._dimension = "pedido"
        # Simular stack vendedor → cliente para breadcrumb
        if not self._drill_stack:
            # crear nivel vendedor padre para breadcrumb correcto
            v_row = self._group_level(level_df, "vendedor")
            v_label = vendor_id
            try:
                v_match = v_row[v_row["ID_VENDEDOR"].astype(str) == str(vendor_id)]
                if not v_match.empty:
                    v_label = str(v_match.iloc[0].get("NOM_VENDEDOR", vendor_id))
            except Exception:
                pass
            self._drill_stack.append(
                {
                    "dim": "vendedor_cliente",
                    "key": str(vendor_id),
                    "label": v_label,
                    "df": level_df[level_df[v_col].astype(str) == str(vendor_id)].reset_index(
                        drop=True
                    )
                    if v_col in level_df.columns
                    else level_df,
                }
            )
        self._drill_down(level)

    # ---------------------------------------------------------------
    # Dimension grouping
    # ---------------------------------------------------------------
    def _group_level(self, df, dim: str):
        """Agrupa el DataFrame del nivel actual segun la dimension."""
        if df is None or df.empty:
            return df
        if dim == "detalle" or dim == "linea":
            return df

        temp_analytics = PedidosAnalytics(df)
        # Parent info from drill stack (the level ABOVE current)
        parent = self._drill_stack[-2] if len(self._drill_stack) >= 2 else None

        if dim == "vendedor":
            return temp_analytics.get_by_vendedor()
        if dim == "pedido_sku":
            return temp_analytics.get_lineas_por_pedido()
        if dim == "vendedor_cliente":
            if parent and parent.get("key"):
                return temp_analytics.get_clientes_by_vendedor(parent["key"])
            return temp_analytics.get_by_cliente()
        if dim == "cliente":
            if parent and parent.get("key"):
                return temp_analytics.get_clientes_by_vendedor(parent["key"])
            return temp_analytics.get_by_cliente()
        if dim == "pedido":
            # En drill vendedor→cliente, df ya está filtrado al cliente; agrupar directo
            try:
                return temp_analytics.get_resumen_pedidos()
            except Exception:
                return (
                    temp_analytics.get_pedidos_by_cliente(parent["key"])
                    if parent and parent.get("key")
                    else temp_analytics.get_resumen_pedidos()
                )
        if dim == "categoria":
            return temp_analytics.get_by_category()
        if dim == "estado_linea":
            return temp_analytics.get_by_estado_linea()
        if dim == "almacen":
            return temp_analytics.get_by_almacen()
        if dim == "producto":
            sku_col = temp_analytics._sku_col()
            nom_col = temp_analytics._nombre_col()
            group_cols = [sku_col]
            if nom_col in df.columns:
                group_cols.append(nom_col)
            agg = {"items": ("CAN_PEDIDO", "size")}
            if "CAN_PEDIDO" in df.columns:
                agg["CAN_PEDIDO"] = ("CAN_PEDIDO", "sum")
            if "CAN_DESPACHO" in df.columns:
                agg["CAN_DESPACHO"] = ("CAN_DESPACHO", "sum")
            if "saldo" in df.columns:
                agg["saldo"] = ("saldo", "sum")
            if "cajas" in df.columns:
                agg["cajas"] = ("cajas", "sum")
            if "valor_saldo" in df.columns:
                agg["valor_saldo"] = ("valor_saldo", "sum")
            if "categoria" in df.columns:
                agg["categoria"] = ("categoria", "first")
            prods = df.groupby(group_cols, dropna=False).agg(**agg).reset_index()
            # Disponible cubierto por SKU — solo VES cuenta como cobertura real
            if "stock_api_ves" in df.columns and sku_col in df.columns:
                ves = df.groupby(sku_col)["stock_api_ves"].first()
                prods["stock_VES"] = (
                    prods[sku_col]
                    .astype(str)
                    .map({str(k): float(v) for k, v in ves.items()})
                    .fillna(0)
                )
            else:
                prods["stock_VES"] = 0
            if "stock_api_121" in df.columns and sku_col in df.columns:
                s121 = df.groupby(sku_col)["stock_api_121"].first()
                prods["stock_121"] = (
                    prods[sku_col]
                    .astype(str)
                    .map({str(k): float(v) for k, v in s121.items()})
                    .fillna(0)
                )
            else:
                prods["stock_121"] = 0
            prods["disp_cub_VES"] = prods.apply(
                lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
            )
            if "saldo" in prods.columns:
                prods = prods.sort_values("saldo", ascending=False).reset_index(drop=True)
            return prods

        return df

    def _build_pedido_view(self, df):
        """Construye la vista Por Pedido con indicador de traslado.

        Para cada linea de pedido muestra:
        - Vendedor, Cliente, Pedido (OC), SKU
        - Pedido, Despacho, Pendiente
        - Stock por almacen: VES (venta), 121 (QC), Otros
        - Indicador Traslado?: SI / NO / PARCIAL
        - Faltante: unidades que no se pueden cubrir ni con traslado

        Logica de traslado:
        - stock_ves >= saldo         -> NO   (cubierto en VES)
        - stock_ves < saldo y total  -> SI   (trasladar de 121/otros a VES)
        - total < saldo              -> FALTA (producir o comprar)
        """
        if df is None or df.empty:
            return df

        pedido = df.copy()

        # Asegurar columnas de stock presentes
        for col in ("stock_api_ves", "stock_api_121", "stock_api_otros"):
            if col not in pedido.columns:
                pedido[col] = 0

        # Calcular stock total y faltante
        pedido["stock_total"] = (
            pedido["stock_api_ves"].fillna(0)
            + pedido["stock_api_121"].fillna(0)
            + pedido["stock_api_otros"].fillna(0)
        )

        # Indicador de traslado
        def _calc_traslado(row):
            saldo = max(float(row.get("saldo", 0) or 0), 0)
            ves = float(row.get("stock_api_ves", 0) or 0)
            total = float(row.get("stock_total", 0) or 0)
            if saldo <= 0:
                return ""
            if ves >= saldo:
                return "NO"
            if total >= saldo:
                return "SI"
            return "FALTA"

        pedido["necesita_traslado"] = pedido.apply(_calc_traslado, axis=1)

        # Faltante = unidades que no se pueden cubrir ni con todo el stock
        def _calc_faltante(row):
            saldo = max(float(row.get("saldo", 0) or 0), 0)
            total = float(row.get("stock_total", 0) or 0)
            return max(saldo - total, 0)

        pedido["faltante_traslado"] = pedido.apply(_calc_faltante, axis=1)

        # Ordenar por OC + SKU
        sort_cols = []
        if "NRO_DOCUMENTO" in pedido.columns:
            sort_cols.append("NRO_DOCUMENTO")
        if "SKU" in pedido.columns:
            sort_cols.append("SKU")
        if sort_cols:
            pedido = pedido.sort_values(sort_cols).reset_index(drop=True)

        return pedido

    # ---------------------------------------------------------------
    # Data updates
    # ---------------------------------------------------------------
    def update_data(self, df, api_state: str = "offline") -> None:
        """Actualiza datos y reconstruye la vista. Resetea el drill."""
        _log.info(
            "[TabsView] update_data: filas=%d, api_state=%s",
            len(df) if df is not None else 0,
            api_state,
        )
        self._df = df
        self._analytics = PedidosAnalytics(df) if df is not None and not df.empty else None
        self._api_state = api_state
        self._filter_values = {}
        self._sort_col = None
        self._sort_desc = False
        self._sort_chip_active = False
        self._cond_familia = None
        self._drill_stack = []
        self._refresh()

    def update_view(self, view: str | None) -> None:
        """Aplica un pre-filtro segun el tipo de vista del sidebar. Resetea drill."""
        _log.info("[TabsView] update_view: %s", view)
        self._pre_filter = view
        if view == "vendedor":
            self._dimension = "vendedor"
        elif view == "cliente":
            self._dimension = "cliente"
        elif view == "producto":
            self._dimension = "producto"
        elif view == "almacen":
            self._dimension = "almacen"
        elif view == "categoria":
            self._dimension = "categoria"
        elif view == "estado_linea":
            self._dimension = "estado_linea"
        elif view == "pedido":
            self._dimension = "pedido"
        elif view == "pedido_sku":
            self._dimension = "pedido_sku"
        else:
            self._dimension = "vendedor"
        self._filter_values = {}
        self._sort_col = None
        self._sort_desc = False
        self._sort_chip_active = False
        self._drill_stack = []
        self._refresh()

    def _apply_pre_filter(self, df):
        """Aplica el pre-filtro del tipo de vista al DataFrame."""
        if self._pre_filter is None or df is None or df.empty:
            return df
        if self._pre_filter == "alerts":
            if self._analytics is not None:
                alerts = self._analytics.get_qc_alerts()
                if alerts is not None and not alerts.empty:
                    sku_col = self._analytics._sku_col()
                    if sku_col and sku_col in df.columns:
                        skus = alerts[sku_col].unique().tolist()
                        return df[df[sku_col].isin(skus)].reset_index(drop=True)
        elif self._pre_filter == "sin_catalogo":
            if "categoria" in df.columns:
                # OJO: la categoria faltante viene como NaN (no ""), asi que
                # comparar solo con "" dejaba el filtro siempre vacio.
                _cat = df["categoria"]
                _vacio = _cat.isna() | _cat.astype(str).str.strip().isin(["", "nan"])
                return df[_vacio].reset_index(drop=True)
        return df

    def _refresh(self) -> None:
        """Reconstruye KPIs, breadcrumb y tabla."""
        if self._root is None or getattr(self._root, "page", None) is None:
            return
        try:
            if self._kpis_row is not None:
                new_kpis = self._build_kpis_row()
                self._kpis_row.controls = new_kpis.controls
            if self._breadcrumb_row is not None:
                new_crumb = self._build_breadcrumb()
                self._breadcrumb_row.content = new_crumb.content
            self._table_container.content = self._build_table()
            self._root.update()
        except Exception as ex:
            _log.warning("[TabsView] _refresh fallo: %s", ex)

    def _soft_refresh(self) -> None:
        """Reconstruye solo la tabla y los KPIs (sin redibujar el selector)."""
        try:
            if self._kpis_row is not None:
                new_kpis = self._build_kpis_row()
                self._kpis_row.controls = new_kpis.controls
            self._table_container.content = self._build_table()
            if getattr(self._table_container, "page", None) is not None:
                self._table_container.update()
        except Exception as ex:
            _log.warning("[TabsView] _soft_refresh fallo: %s", ex)

    # ---------------------------------------------------------------
    # Interaction handlers
    # ---------------------------------------------------------------
    def _set_dimension(self, dim: str) -> None:
        _log.info("[TabsView] set_dimension: %s", dim)
        if self._dimension == dim:
            return
        self._dimension = dim
        self._filter_values = {}
        self._sort_col = None
        self._sort_desc = False
        self._sort_chip_active = False
        self._cond_familia = None
        self._drill_stack = []
        if self._dimension_segment is not None:
            new_seg = self._build_dimension_segment()
            self._dimension_segment.controls = new_seg.controls
            self._dimension_segment.update()
        if self._breadcrumb_row is not None:
            new_crumb = self._build_breadcrumb()
            self._breadcrumb_row.content = new_crumb.content
            self._breadcrumb_row.update()
        self._table_container.content = self._build_table()
        if getattr(self._table_container, "page", None) is not None:
            self._table_container.update()

    def _drill_to(self, index_or_none) -> None:
        """Navega a un nivel del drill stack. None = volver a la raiz."""
        if index_or_none is None:
            self._drill_stack = []
            self._dimension = "vendedor"
        else:
            idx = int(index_or_none)
            self._drill_stack = self._drill_stack[: idx + 1]
            self._dimension = self._drill_stack[idx].get("dim", "vendedor")
        self._filter_values = {}
        self._sort_col = None
        self._sort_desc = False
        self._sort_chip_active = False
        self._cond_familia = None
        self._refresh()

    def _drill_down(self, level: dict) -> None:
        """Empuja un nivel nuevo al stack y refresca."""
        self._drill_stack.append(level)
        self._filter_values = {}
        self._sort_col = None
        self._sort_desc = False
        self._sort_chip_active = False
        self._cond_familia = None
        self._refresh()

    def _on_filter_change(self, col_key: str, text: str) -> None:
        if text:
            self._filter_values[col_key] = text
        else:
            self._filter_values.pop(col_key, None)
        self._soft_refresh()

    def _on_clear_filters(self) -> None:
        _log.info("[TabsView] _on_clear_filters: limpiando %d filtros", len(self._filter_values))
        self._filter_values = {}
        self._soft_refresh()

    def _on_sort_change(self, col_key: str) -> None:
        if self._sort_col == col_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col_key
            self._sort_desc = False
        self._soft_refresh()

    def _on_row_click(self, row: dict) -> None:
        """Click en una fila: drill-down segun el nivel actual, o detalle de cliente."""
        _log.info("[TabsView] row click: dim=%s row=%s", self._dimension, list(row.keys())[:4])
        cfg = DRILL_CONFIG.get(self._dimension, {})
        next_dim = cfg.get("next")
        key_col = cfg.get("key_col")
        label_col = cfg.get("label_col")
        filter_method = cfg.get("filter_method")

        if next_dim and key_col and filter_method:
            key_val = row.get(key_col, "")
            label_val = row.get(label_col, "") if label_col else key_val
            self._do_drill_down(next_dim, key_col, key_val, label_val, filter_method)
            return

        # Fallback: si la fila tiene COD_CLIENTE, abre el detalle del cliente
        if self._on_open_detail is not None:
            cod = str(row.get("COD_CLIENTE", "") or "")
            nombre = str(row.get("NOM_CLIENTE", "") or "")
            if cod:
                self._on_open_detail(cod, nombre)

    def _do_drill_down(
        self,
        next_dim: str,
        key_col: str,
        key_val,
        label_val,
        filter_method: str,
    ) -> None:
        """Filtra el df del nivel actual y empuja un nivel nuevo al stack."""
        level_df = self._current_level_df()
        if level_df is None or self._analytics is None:
            return

        try:
            sub_df = self._apply_filter_method(filter_method, key_col, key_val, level_df)
        except Exception as ex:
            _log.warning("[TabsView] drill down fallo: %s", ex)
            return
        if sub_df is None or sub_df.empty:
            _log.info("[TabsView] drill down sin resultados: %s=%s", key_col, key_val)
            return

        level = {
            "dim": next_dim,
            "key_col": key_col,
            "key": str(key_val),
            "label": str(label_val) if label_val else str(key_val),
            "df": sub_df,
        }
        # Cambiar dimension ANTES de refrescar para que la nueva tabla use las columnas correctas
        self._dimension = next_dim
        self._drill_down(level)

    def _apply_filter_method(self, method: str, key_col: str, key_val, df):
        """Aplica un filtro de drill segun el metodo declarado."""
        if self._analytics is None:
            return None
        if method == "get_clientes_by_vendedor":
            vid = self._analytics._vendedor_col()
            if vid not in df.columns:
                return None
            return df[df[vid].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_vendedor_cliente":
            # Filtrar por vendedor del nivel padre + cliente de esta fila
            parent = self._drill_stack[-2] if len(self._drill_stack) >= 2 else None
            vid = self._analytics._vendedor_col()
            cid = self._analytics._cliente_col()
            sub = df
            if parent and vid in sub.columns and parent.get("key"):
                sub = sub[sub[vid].astype(str) == str(parent["key"])]
            if cid in sub.columns:
                sub = sub[sub[cid].astype(str) == str(key_val)]
            return sub.reset_index(drop=True)
        if method == "get_lineas_filtradas_cliente":
            cid = self._analytics._cliente_col()
            if cid in df.columns:
                return df[df[cid].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_sku":
            sku_col = self._analytics._sku_col()
            if sku_col in df.columns:
                return df[df[sku_col].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_almacen":
            if "NOM_ALMACEN" in df.columns:
                return df[df["NOM_ALMACEN"].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_categoria":
            if "categoria" in df.columns:
                return df[df["categoria"].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_estado":
            col = "estado_linea" if "estado_linea" in df.columns else "estado"
            if col in df.columns:
                return df[df[col].astype(str) == str(key_val)].reset_index(drop=True)
        if method == "get_lineas_filtradas_id_pedido":
            if self._analytics:
                return self._analytics.get_lineas_by_id_pedido(key_val)
        if method == "get_lineas_filtradas_oc":
            if "NRO_DOCUMENTO" in df.columns:
                return df[df["NRO_DOCUMENTO"].astype(str) == str(key_val)].reset_index(drop=True)
        return None

    # ---------------------------------------------------------------
    # Theme
    # ---------------------------------------------------------------
    def update_theme(self, colors: dict) -> None:
        self.c = colors
        self._refresh()
