"""
Vistas del monitor operativo de pedidos (apoyo al ERP, despacho manual).

Contiene las vistas base del monitor. Las vistas Resumen/Alertas/Configuracion
viven en monitor_extra.py.
Cada vista independiente reutiliza los colores/componentes del dashboard:
- StatsView   (Estadisticas): rankings (clientes deudores, pedidos casi 100%,
               vendedores pendientes, SKUs mas necesitados por condicion).
- HistoryView (Historico): snapshots automaticos + comparador por ID_PEDIDO+SKU.
- SearchView  (Buscar): busqueda por ID_PEDIDO / OC / vendedor / cliente con chips.
- GroupsView  (Grupos): crear/guardar grupos multi-cliente/vendedor/pedido (JSON).
- ColaView    (Cola Despacho): lineas listas para cargar en el ERP manualmente.

Cada vista implementa: set_data(df, api_state), set_colors(colors) y build().
"""

from __future__ import annotations

import logging

import flet as ft
import pandas as pd

from src.config.settings import DATA_DIR
from src.core.analytics import COND_FAMILIA_ORDER, PedidosAnalytics, summarize_df
from src.core.exporters import export_cola_despacho, export_grupo
from src.core.snapshot import SnapshotManager
from src.ui.components import build_master_table, build_sortable_table, empty_state, kpi_card
from src.ui.config import (
    FONT_SIZE_LARGE,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    PADDING_LG,
    PADDING_MD,
    PADDING_SM,
    RADIUS_MD,
    RADIUS_SM,
    SPACING_2XL,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
    SPACING_XS,
)

_log = logging.getLogger("g360.pedido_vigencias")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _chip(label: str, on_click, selected: bool, colors: dict, key: str = "accent") -> ft.Chip:
    return ft.Chip(
        label=ft.Text(label, size=FONT_SIZE_SMALL),
        on_click=on_click,
        selected=selected,
        bgcolor=colors["surface_variant"] if selected else None,
        check_color=colors[key],
        data=label,
    )


def _dropdown(options: list, value=None, label: str = "", width: int = 220) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        value=value,
        options=options,
        width=width,
        text_size=FONT_SIZE_SMALL,
    )


def _section_header(colors: dict, title: str, icon, subtitle: str = "") -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(icon, size=16, color=colors["accent"]),
                ft.Text(
                    title,
                    size=FONT_SIZE_LARGE,
                    weight=ft.FontWeight.W_700,
                    color=colors["text_primary"],
                ),
                ft.Container(expand=True),
                ft.Text(subtitle, size=FONT_SIZE_TINY, color=colors["text_muted"]),
            ],
            spacing=SPACING_MD,
        ),
        padding=ft.Padding(4, 2, 4, 2),
    )


def _card(colors: dict, header: ft.Control, body: ft.Control, padding: int = 10) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [header, ft.Container(height=SPACING_SM), body], spacing=SPACING_SM, expand=True
        ),
        padding=ft.Padding(padding, padding, padding, padding),
        bgcolor=colors["surface"],
        border_radius=RADIUS_MD,
        border=ft.BorderSide(1, colors["border"]),
        expand=True,
    )


def _kpi_row(colors: dict, kpis: list[tuple[str, str, str]]) -> ft.Row:
    return ft.Row(
        [kpi_card(colors, label, value, color_key) for label, value, color_key in kpis],
        spacing=SPACING_2XL,
        wrap=True,
    )


# ---------------------------------------------------------------------------
# StatsView (Estadisticas)
# ---------------------------------------------------------------------------
class StatsView:
    _COLS_CLIENTES = [
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("items", "Items", "num"),
        ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"),
        ("cajas", "Cajas", "num"),
    ]
    _COLS_PEDIDOS = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("pedido", "Pedido", "num"),
        ("despacho", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("por_atendido", "% Aten.", "pct"),
        ("cajas", "Cajas", "num"),
        ("valor", "Valor S/", "num"),
    ]
    _COLS_VENDEDORES = [
        ("ID_VENDEDOR", "ID", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("items", "Items", "num"),
        ("pedido", "Pedido", "num"),
        ("saldo", "Vig. Total", "num"),
        ("valor", "Valor S/", "num"),
        ("stock_VES", "Stock VES", "num"),
        ("disp_cub_VES", "Disp. Cubierto", "num"),
    ]
    _COLS_SKUS = [
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("categoria", "Categoria", None),
        ("items", "Lineas", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor", "Valor S/", "num"),
        ("stock_VES", "Stock VES", "num"),
        ("stock_121", "Stock 121", "num"),
        ("disp_cub_VES", "Disp. Cubierto", "num"),
    ]

    def __init__(self, colors: dict) -> None:
        self.c = colors
        self._df: pd.DataFrame | None = None
        self._cond = "TODAS"
        self._vend = None
        self._clie = None
        self._sku = None
        self._linea = None
        self._categoria = None
        self._sort_states: dict[str, tuple] = {}
        self._host: ft.Container | None = None
        self._cond_row = ft.Row(spacing=SPACING_SM, wrap=True)
        self._vend_dd = _dropdown([], label="Vendedor")
        self._clie_dd = _dropdown([], label="Cliente")
        self._sku_tf = ft.TextField(
            label="SKU",
            hint_text="Buscar SKU",
            text_size=FONT_SIZE_SMALL,
            width=180,
            on_submit=lambda _: self._on_filter_change(),
        )
        self._linea_dd = _dropdown([], label="Linea")
        self._categoria_dd = _dropdown([], label="Categoria")

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        if self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def _refresh_options(self) -> None:
        df = self._df
        self._vend_dd.options = [ft.dropdown.Option(None, "Vendedor: Todos")]
        self._clie_dd.options = [ft.dropdown.Option(None, "Cliente: Todos")]
        self._linea_dd.options = [ft.dropdown.Option(None, "Linea: Todas")]
        self._categoria_dd.options = [ft.dropdown.Option(None, "Categoria: Todas")]
        if df is None or len(df) == 0:
            return
        if "ID_VENDEDOR" in df.columns:
            vends = df.drop_duplicates("ID_VENDEDOR")[["ID_VENDEDOR", "NOM_VENDEDOR"]]
            for _, r in vends.iterrows():
                self._vend_dd.options.append(
                    ft.dropdown.Option(
                        str(r["ID_VENDEDOR"]), f"{r['ID_VENDEDOR']} - {str(r['NOM_VENDEDOR'])[:24]}"
                    )
                )
        if "COD_CLIENTE" in df.columns:
            clies = df.drop_duplicates("COD_CLIENTE")[["COD_CLIENTE", "NOM_CLIENTE"]]
            for _, r in clies.iterrows():
                self._clie_dd.options.append(
                    ft.dropdown.Option(
                        str(r["COD_CLIENTE"]), f"{r['COD_CLIENTE']} - {str(r['NOM_CLIENTE'])[:24]}"
                    )
                )
        if "linea" in df.columns:
            # La linea es siempre el codigo canonico; se muestra el nombre
            # para que sea legible, pero el VALOR sigue siendo el codigo
            # (el filtro compara exacto).
            _nombres: dict[str, str] = {}
            if "linea_nombre" in df.columns:
                for cod, nom in zip(df["linea"].astype(str), df["linea_nombre"].astype(str)):
                    cod = cod.strip()
                    nom = nom.strip()
                    if cod and nom and cod not in _nombres:
                        _nombres[cod] = nom
            for v in sorted(df["linea"].dropna().astype(str).unique()):
                if not v:
                    continue
                etiqueta = f"{v} - {_nombres[v]}" if v in _nombres else v
                self._linea_dd.options.append(ft.dropdown.Option(v, etiqueta))
        if "categoria" in df.columns:
            for v in sorted(x for x in df["categoria"].dropna().astype(str).unique() if x):
                self._categoria_dd.options.append(ft.dropdown.Option(v, v))

    def _cond_options(self) -> list[str]:
        if self._df is None or "cond_familia" not in self._df.columns:
            return []
        present = set(self._df["cond_familia"].dropna().astype(str).unique())
        return [c for c in COND_FAMILIA_ORDER if c in present]

    def _filtered(self) -> pd.DataFrame | None:
        df = self._df
        if df is None or len(df) == 0:
            return df
        mask = pd.Series(True, index=df.index)
        if self._cond != "TODAS" and "cond_familia" in df.columns:
            mask &= df["cond_familia"] == self._cond
        if self._vend and "ID_VENDEDOR" in df.columns:
            mask &= df["ID_VENDEDOR"].astype(str) == str(self._vend)
        if self._clie and "COD_CLIENTE" in df.columns:
            mask &= df["COD_CLIENTE"].astype(str) == str(self._clie)
        if self._sku and self._analytics_sku_col() in df.columns:
            mask &= (
                df[self._analytics_sku_col()]
                .astype(str)
                .str.contains(str(self._sku), case=False, na=False, regex=False)
            )
        if self._linea or self._categoria:
            conds = []
            if self._linea and "linea" in df.columns:
                conds.append(df["linea"].astype(str) == str(self._linea))
            if self._categoria and "categoria" in df.columns:
                conds.append(df["categoria"].astype(str) == str(self._categoria))
            if conds:
                mask &= conds[0] if len(conds) == 1 else (conds[0] | conds[1])
        return df[mask].reset_index(drop=True)

    def _analytics_sku_col(self) -> str:
        if self._df is not None and "SKU" in self._df.columns:
            return "SKU"
        return "ID_ARTICULO"

    def _on_cond(self, label: str, e=None) -> None:
        self._cond = label
        self._render_into()

    def _on_filter_change(self, e=None) -> None:
        v = self._vend_dd.value
        self._vend = v if v and v != "None" else None
        c = self._clie_dd.value
        self._clie = c if c and c != "None" else None
        self._sku = (self._sku_tf.value or "").strip() or None
        l = self._linea_dd.value
        self._linea = l if l and l != "None" else None
        ca = self._categoria_dd.value
        self._categoria = ca if ca and ca != "None" else None
        self._render_into()

    def _on_toggle_sort(self, key: str, col: str) -> None:
        cur = self._sort_states.get(key, (None, False))
        if cur[0] == col:
            self._sort_states[key] = (col, not cur[1])
        else:
            self._sort_states[key] = (col, False)
        self._render_into()

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._refresh_options()
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._refresh_options()
        self._host.content = self._build_content()
        self._host.update()

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para ver estadisticas")
        df = self._filtered()
        if df is None or len(df) == 0:
            return empty_state(self.c, "Sin resultados con los filtros seleccionados")

        an = PedidosAnalytics(df)
        cond_chips = [
            _chip("Todas", lambda e, lbl="TODAS": self._on_cond(lbl), self._cond == "TODAS", self.c)
        ]
        for fam in self._cond_options():
            cond_chips.append(
                _chip(
                    fam,
                    lambda e, lbl=fam: self._on_cond(lbl),
                    self._cond == fam,
                    self.c,
                    key="warning" if fam == "CANJE" else "accent",
                )
            )
        self._cond_row.controls = cond_chips

        filtros = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Condicion de pago (chips)", size=FONT_SIZE_TINY, color=self.c["text_muted"]
                    ),
                    self._cond_row,
                    ft.Container(height=SPACING_SM),
                    ft.Row(
                        [
                            self._vend_dd,
                            self._clie_dd,
                            self._sku_tf,
                            self._linea_dd,
                            self._categoria_dd,
                        ],
                        spacing=SPACING_MD,
                        wrap=True,
                    ),
                ],
                spacing=SPACING_SM,
            ),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        clientes = an.get_top_clientes_deudores(top=10, by="valor")
        pedidos = an.get_pedidos_casi_100(min_pct=80.0, top=12)
        vendedores = an.get_vendedores_pendientes(top=10)
        skus = an.get_skus_mas_necesitados(
            familia=None if self._cond == "TODAS" else self._cond, top=15
        )

        def build_t(card_key: str, title: str, icon, df_table, columns):
            return _card(
                self.c,
                _section_header(self.c, title, icon, f"{len(df_table)} registros"),
                build_sortable_table(
                    self.c,
                    df_table,
                    columns,
                    card_key,
                    self._sort_states,
                    self._on_toggle_sort,
                    page_limit=15,
                )
                if df_table is not None and len(df_table)
                else empty_state(self.c, "Sin datos"),
            )

        row1 = ft.Row(
            [
                build_t(
                    "stats_clientes",
                    "Clientes que mas debemos",
                    ft.Icons.PEOPLE,
                    clientes,
                    self._COLS_CLIENTES,
                ),
                build_t(
                    "stats_pedidos",
                    "Pedidos casi 100% atencion",
                    ft.Icons.FACT_CHECK,
                    pedidos,
                    self._COLS_PEDIDOS,
                ),
            ],
            spacing=SPACING_2XL,
            vertical_alignment=ft.CrossAxisAlignment.START,
            wrap=True,
        )
        row2 = ft.Row(
            [
                build_t(
                    "stats_vendedores",
                    "Vendedores con mas pendientes",
                    ft.Icons.PERSON,
                    vendedores,
                    self._COLS_VENDEDORES,
                ),
                build_t(
                    "stats_skus",
                    "SKUs mas necesitados",
                    ft.Icons.INVENTORY_2,
                    skus,
                    self._COLS_SKUS,
                ),
            ],
            spacing=SPACING_2XL,
            vertical_alignment=ft.CrossAxisAlignment.START,
            wrap=True,
        )

        return ft.Column(
            [
                filtros,
                ft.Container(height=SPACING_SM),
                row1,
                ft.Container(height=SPACING_2XL),
                row2,
            ],
            spacing=SPACING_LG,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )


# ---------------------------------------------------------------------------
# HistoryView (Historico)
# ---------------------------------------------------------------------------
class HistoryView:
    _COLS_COMPARACION = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("ID_ARTICULO", "SKU", None),
        ("CAN_DESPACHO_antes", "Desp. antes", "num"),
        ("CAN_DESPACHO_ahora", "Desp. ahora", "num"),
        ("cambio", "Cambio", None),
    ]

    def __init__(
        self, colors: dict, snapshot: SnapshotManager | None = None, on_snack=None
    ) -> None:
        self.c = colors
        self._snapshot = snapshot or SnapshotManager(DATA_DIR)
        self._on_snack = on_snack
        self._df: pd.DataFrame | None = None
        self._sort_states: dict[str, tuple] = {}
        self._base_dd = _dropdown([], label="Snapshot base", width=280)
        self._host: ft.Container | None = None
        self._compare_df: pd.DataFrame | None = None
        self._summary: dict = {}

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        if self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def _snap_options(self) -> list:
        opts = [ft.dropdown.Option(None, "(sin snapshot)")]
        for s in self._snapshot.list_snapshots()[:30]:
            opts.append(
                ft.dropdown.Option(s["label"], f"{s['label']} · {s['total_saldo']:,.0f} unds")
            )
        return opts

    def _do_compare(self, e=None) -> None:
        base = self._base_dd.value
        if not base:
            return
        merged, summary = self._snapshot.compare_current(base, self._df)
        self._compare_df = merged
        self._summary = summary
        if self._on_snack and summary:
            self._on_snack(
                f"Base {base}: {summary['atendidos']} atendidos, {summary['nuevos']} nuevos, {summary['sin_cambio']} sin cambio",
                "#3B82F6",
            )
        self._render_into()

    def _on_toggle_sort(self, key: str, col: str) -> None:
        cur = self._sort_states.get(key, (None, False))
        self._sort_states[key] = (col, not cur[1]) if cur[0] == col else (col, False)
        self._render_into()

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._host.content = self._build_content()
        self._host.update()

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para ver el historico")
        self._base_dd.options = self._snap_options()
        snapshots = self._snapshot.list_snapshots()[:30]

        info = ft.Row(
            [
                ft.Icon(ft.Icons.HISTORY, size=16, color=self.c["accent"]),
                ft.Text(
                    "Se guarda un snapshot automatico en cada carga del XLS.",
                    size=FONT_SIZE_SMALL,
                    color=self.c["text_secondary"],
                ),
            ],
            spacing=SPACING_MD,
        )

        actions = ft.Container(
            content=ft.Row(
                [
                    self._base_dd,
                    ft.ElevatedButton(
                        "Comparar con esta carga",
                        icon=ft.Icons.COMPARE_ARROWS,
                        on_click=self._do_compare,
                    ),
                ],
                spacing=SPACING_MD,
                wrap=True,
            ),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        lista = ft.Container(
            content=ft.Column(
                [
                    _section_header(self.c, "Snapshots guardados", ft.Icons.INVENTORY),
                    *[
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.SAVE, size=12, color=self.c["text_muted"]),
                                    ft.Text(
                                        s.get("label", ""),
                                        size=FONT_SIZE_SMALL,
                                        color=self.c["text_primary"],
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Container(expand=True),
                                    ft.Text(
                                        f"{s.get('total_items', 0):,} items · {s.get('total_saldo', 0):,.0f} unds",
                                        size=FONT_SIZE_TINY,
                                        color=self.c["text_muted"],
                                    ),
                                ],
                                spacing=SPACING_SM,
                            ),
                            padding=PADDING_SM,
                            bgcolor=self.c["surface_sunken"],
                            border_radius=RADIUS_SM,
                        )
                        for s in snapshots[:12]
                    ],
                ],
                spacing=SPACING_SM,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=PADDING_LG,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
            height=320,
        )

        cols = [info, actions]
        if self._summary:
            kpis = _kpi_row(
                self.c,
                [
                    ("Atendidos", f"{self._summary.get('atendidos', 0):,}", "saldo"),
                    ("Nuevos", f"{self._summary.get('nuevos', 0):,}", "items"),
                    ("Sin cambio", f"{self._summary.get('sin_cambio', 0):,}", "valor"),
                    ("Eliminados", f"{self._summary.get('eliminados', 0):,}", "porcentaje"),
                ],
            )
            cols.append(kpis)
            tabla = build_sortable_table(
                self.c,
                self._compare_df if self._compare_df is not None else pd.DataFrame(),
                self._COLS_COMPARACION,
                "hist_comp",
                self._sort_states,
                self._on_toggle_sort,
                page_limit=50,
            )
            cols.append(tabla)
        cols.append(lista)
        return ft.Column(cols, spacing=SPACING_LG, expand=True, scroll=ft.ScrollMode.AUTO)


# ---------------------------------------------------------------------------
# SearchView (Buscar)
# ---------------------------------------------------------------------------
class SearchView:
    _COLS_RESULT = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("CONDICION_PAGO", "Condicion", None),
        ("cond_familia", "Familia", None),
        ("PEDIDO_ESTADO", "Estado", None),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor_saldo", "Valor S/", "num"),
        ("stock_api_ves", "Stock VES", "num"),
        ("ATENDIBLE_100", "Atend. 100%", None),
    ]

    def __init__(self, colors: dict) -> None:
        self.c = colors
        self._df: pd.DataFrame | None = None
        self._query = ""
        self._cond = "TODAS"
        self._estado = "TODOS"
        self._vend = None
        self._clie = None
        self._result_df: pd.DataFrame | None = None
        self._explanation = ""
        self._summary: dict = {}
        self._sort_states: dict[str, tuple] = {}
        self._host: ft.Container | None = None
        self._text = ft.TextField(
            hint_text="Buscar: ID_PEDIDO (FC00861), OC, cliente, vendedor, SKU, condicion...",
            prefix_icon=ft.Icons.SEARCH,
            text_size=FONT_SIZE_SMALL,
            expand=True,
            on_submit=lambda e: self._on_search(),
            autofocus=True,
        )
        self._cond_row = ft.Row(spacing=SPACING_SM, wrap=True)
        self._estado_row = ft.Row(spacing=SPACING_SM, wrap=True)
        self._vend_dd = _dropdown([], label="Vendedor")
        self._clie_dd = _dropdown([], label="Cliente")

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        if self._result_df is not None and self._query:
            self._on_search(re_apply=True)
        elif self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def _cond_options(self) -> list[str]:
        if self._df is None or "cond_familia" not in self._df.columns:
            return []
        present = set(self._df["cond_familia"].dropna().astype(str).unique())
        return [c for c in COND_FAMILIA_ORDER if c in present]

    def _on_cond(self, label: str) -> None:
        self._cond = label
        self._on_search(re_apply=True)

    def _on_estado(self, label: str) -> None:
        self._estado = "TODOS" if label == "TODOS" else label
        self._on_search(re_apply=True)

    def _on_vend_clie(self, e=None) -> None:
        v = self._vend_dd.value
        self._vend = v if v and v != "None" else None
        c = self._clie_dd.value
        self._clie = c if c and c != "None" else None
        self._on_search(re_apply=True)

    def _on_search(self, re_apply: bool = False) -> None:
        self._query = (self._text.value or "").strip()
        if self._df is None or len(self._df) == 0:
            return
        an = PedidosAnalytics(self._df)
        if self._query:
            result, expl = an.query_natural(self._query)
            self._explanation = expl if not result.empty else "Sin resultados"
        else:
            result, self._explanation = self._df, "Vista completa"
        if result is not None and len(result):
            r = result.copy()
            if self._cond != "TODAS" and "cond_familia" in r.columns:
                r = r[r["cond_familia"] == self._cond]
            if self._estado != "TODOS" and "PEDIDO_ESTADO" in r.columns:
                r = r[r["PEDIDO_ESTADO"].astype(str).str.upper() == self._estado]
            if self._vend and "ID_VENDEDOR" in r.columns:
                r = r[r["ID_VENDEDOR"].astype(str) == str(self._vend)]
            if self._clie and "COD_CLIENTE" in r.columns:
                r = r[r["COD_CLIENTE"].astype(str) == str(self._clie)]
            self._result_df = r.reset_index(drop=True)
        else:
            self._result_df = pd.DataFrame()
        self._add_atendible_flag()
        self._summary = summarize_df(self._result_df)
        self._render_into()

    def _add_atendible_flag(self) -> None:
        """Columna 'Atendible 100%' = stock API VES alcanza todo el saldo."""
        r = self._result_df
        if r is None or len(r) == 0 or "saldo" not in r.columns:
            return
        saldo = pd.to_numeric(r["saldo"], errors="coerce").fillna(0)
        atendido = saldo <= 0
        flag = pd.Series("Sin stock", index=r.index, dtype=object)
        flag[atendido] = "Atendido"
        if "stock_api_ves" in r.columns:
            stk = pd.to_numeric(r["stock_api_ves"], errors="coerce")
            con_stock = ~stk.isna()
            flag[(~atendido) & con_stock & (stk >= saldo)] = "SI"
            flag[(~atendido) & con_stock & (stk < saldo)] = "NO"
        r["ATENDIBLE_100"] = flag

    def _on_toggle_sort(self, key: str, col: str) -> None:
        cur = self._sort_states.get(key, (None, False))
        self._sort_states[key] = (col, not cur[1]) if cur[0] == col else (col, False)
        self._render_into()

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._host.content = self._build_content()
        self._host.update()

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para poder buscar")
        self._vend_dd.options = [ft.dropdown.Option(None, "Vendedor: Todos")]
        self._clie_dd.options = [ft.dropdown.Option(None, "Cliente: Todos")]
        if "ID_VENDEDOR" in self._df.columns:
            for _, r in self._df.drop_duplicates("ID_VENDEDOR")[
                ["ID_VENDEDOR", "NOM_VENDEDOR"]
            ].iterrows():
                self._vend_dd.options.append(
                    ft.dropdown.Option(
                        str(r["ID_VENDEDOR"]), f"{r['ID_VENDEDOR']} - {str(r['NOM_VENDEDOR'])[:24]}"
                    )
                )
        if "COD_CLIENTE" in self._df.columns:
            for _, r in self._df.drop_duplicates("COD_CLIENTE")[
                ["COD_CLIENTE", "NOM_CLIENTE"]
            ].iterrows():
                self._clie_dd.options.append(
                    ft.dropdown.Option(
                        str(r["COD_CLIENTE"]), f"{r['COD_CLIENTE']} - {str(r['NOM_CLIENTE'])[:24]}"
                    )
                )

        cond_chips = [
            _chip("Todas", lambda e, lbl="TODAS": self._on_cond(lbl), self._cond == "TODAS", self.c)
        ]
        for fam in self._cond_options():
            cond_chips.append(
                _chip(
                    fam,
                    lambda e, lbl=fam: self._on_cond(lbl),
                    self._cond == fam,
                    self.c,
                    key="warning" if fam == "CANJE" else "accent",
                )
            )
        self._cond_row.controls = cond_chips
        estados = ["TODOS", "APROBADO", "INGRESADO"]
        est_chips = [
            _chip(
                st,
                lambda e, lbl=st: self._on_estado(lbl),
                self._estado == st,
                self.c,
                key="success" if st == "APROBADO" else "warning",
            )
            for st in estados
        ]
        self._estado_row.controls = est_chips

        bar = ft.Container(
            content=ft.Column(
                [
                    self._text,
                    ft.Row([self._vend_dd, self._clie_dd], spacing=SPACING_MD, wrap=True),
                    ft.Row(
                        [
                            ft.Text("Condicion:", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                            self._cond_row,
                        ],
                        spacing=SPACING_MD,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.Text("Estado:", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                            self._estado_row,
                        ],
                        spacing=SPACING_MD,
                        wrap=True,
                    ),
                ],
                spacing=SPACING_SM,
            ),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        result_df = self._result_df if self._result_df is not None else pd.DataFrame()
        n = len(result_df)
        res_info = ft.Text(
            f"{n:,} resultado(s) · {self._explanation}"
            if n
            else "Sin resultados. Ajusta la busqueda.",
            size=FONT_SIZE_SMALL,
            color=self.c["text_secondary"] if n else self.c["warning"],
            weight=ft.FontWeight.W_600 if n else ft.FontWeight.W_500,
        )
        tabla = (
            build_master_table(
                self.c,
                result_df,
                self._COLS_RESULT,
                {},
                None,
                False,
                lambda c, t: None,
                lambda c: None,
                lambda: None,
                on_row_click=None,
                drillable_cols=set(),
                page_limit=100,
            )
            if n
            else empty_state(self.c, "Sin resultados de busqueda")
        )

        summary_panel = self._build_summary() if n else ft.Container()

        return ft.Column(
            [bar, ft.Container(height=SPACING_SM), res_info, summary_panel, tabla],
            spacing=SPACING_LG,
            expand=True,
        )

    def _build_summary(self) -> ft.Control:
        """KPIs agregados del resultado filtrado (pendientes y cobertura 100%)."""
        s = self._summary
        if not s or not s.get("lineas_total"):
            return ft.Container()

        def card(label: str, value: str, key: str = "items") -> ft.Control:
            return kpi_card(self.c, label, value, key, size="small")

        atend_val = (
            f"{s['atendibles']} ({s['atendibles_pct']:.0f}%)"
            if s.get("usar_stock")
            else f"{s['atendibles']} (s/d stock)"
        )
        cards = ft.Row(
            [
                card("Lineas", f"{s['lineas_total']:,}"),
                card("Pendientes", f"{s['pendientes']:,}", "porcentaje"),
                card("Unidades", f"{s['unidades']:,.0f}", "saldo"),
                card("Valor S/", f"{s['valor']:,.0f}", "valor"),
                card("Pedidos", f"{s['pedidos']:,}", "items"),
                card("Clientes", f"{s['clientes']:,}", "porcentaje"),
                card("Atend. 100%", atend_val, "saldo"),
                card("Unid. atend.", f"{s['unidades_atendibles']:,.0f}", "saldo"),
            ],
            spacing=SPACING_MD,
            wrap=True,
        )

        caption = ft.Text(
            "Atendible 100% = linea con saldo > 0 cuyo stock API VES ≥ saldo."
            if s.get("usar_stock")
            else "Sin dato de stock API (VES): la cobertura no se puede calcular.",
            size=FONT_SIZE_TINY,
            color=self.c["text_muted"],
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Resumen de pendientes",
                        size=FONT_SIZE_TINY,
                        color=self.c["text_muted"],
                        weight=ft.FontWeight.W_700,
                    ),
                    cards,
                    caption,
                ],
                spacing=SPACING_SM,
            ),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )


# ---------------------------------------------------------------------------
# GroupsView (Grupos)
# ---------------------------------------------------------------------------
class GroupsView:
    _COLS_LINEAS = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("COD_CLIENTE", "Cod.", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("cond_familia", "Familia", None),
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("cajas", "Cajas", "num"),
        ("valor_saldo", "Valor S/", "num"),
        ("stock_api_ves", "Stock VES", "num"),
        ("stock_api_121", "Stock 121", "num"),
    ]

    def __init__(self, colors: dict, store=None, on_snack=None) -> None:
        from src.ui.groups_store import GroupsStore

        self.c = colors
        self._store = store or GroupsStore()
        self._on_snack = on_snack
        self._df: pd.DataFrame | None = None
        self._selected: dict | None = None
        self._clientes_check: dict[str, ft.Checkbox] = {}
        self._vendedores_check: dict[str, ft.Checkbox] = {}
        self._name = ft.TextField(
            label="Nombre del grupo",
            hint_text="Ej: Anticipos Lima Norte",
            text_size=FONT_SIZE_SMALL,
            expand=True,
        )
        self._groups_dd = _dropdown([], label="Grupo guardado", width=360)
        self._host: ft.Container | None = None

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        self._clientes_check = {}
        self._vendedores_check = {}
        if self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def _save(self, e=None) -> None:
        clientes = [k for k, chk in self._clientes_check.items() if chk.value]
        vendedores = [k for k, chk in self._vendedores_check.items() if chk.value]
        if not (clientes or vendedores):
            if self._on_snack:
                self._on_snack("Marca al menos un cliente o vendedor", "#F59E0B")
            return
        g = self._store.add((self._name.value or ""), clientes=clientes, vendedores=vendedores)
        self._name.value = ""
        if self._on_snack:
            self._on_snack(f"Grupo '{g['nombre']}' guardado", "#10B981")
        self._groups_dd.options = self._group_options()
        self._groups_dd.value = g["id"]
        self._selected = g
        self._render_into()

    def _on_select_group(self, e=None) -> None:
        gid = self._groups_dd.value
        self._selected = self._store.get(gid) if gid and gid != "None" else None
        self._render_into()

    def _delete(self, e=None) -> None:
        if self._selected:
            self._store.delete(self._selected.get("id", ""))
            self._selected = None
            self._groups_dd.value = None
            if self._on_snack:
                self._on_snack("Grupo eliminado", "#EF4444")
            self._render_into()

    def _export(self, e=None) -> None:
        if self._selected and self._df is not None:
            lines = self._store.filter_df(self._df, self._selected)
            if lines is None or len(lines) == 0:
                if self._on_snack:
                    self._on_snack("El grupo no tiene lineas para exportar", "#F59E0B")
                return
            try:
                out = export_grupo(lines, self._selected.get("nombre", "grupo"))
                if self._on_snack:
                    self._on_snack(f"Grupo exportado: {out.name}", "#10B981")
            except Exception as ex:
                if self._on_snack:
                    self._on_snack(f"Error exportando: {ex}", "#EF4444")

    def _group_options(self) -> list:
        opts = [ft.dropdown.Option(None, "(seleccionar grupo)")]
        for g in self._store.load():
            n = g.get("nombre", "sin nombre")
            opts.append(
                ft.dropdown.Option(
                    g.get("id", ""),
                    f"{n}  ({len(g.get('clientes', []))} cli / {len(g.get('vendedores', []))} ven)",
                )
            )
        return opts

    def _checkbox(self, key: str, label: str, pool: dict) -> ft.Checkbox:
        chk = pool.get(key)
        if chk is None:
            chk = ft.Checkbox(
                label=label, value=False, label_style=ft.TextStyle(size=FONT_SIZE_SMALL)
            )
            pool[key] = chk
        return chk

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._host.content = self._build_content()
        self._host.update()

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para crear grupos")

        self._groups_dd.options = self._group_options()

        # Seleccion de clientes/vendedores (checkbox) para crear grupo nuevo
        cli_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Clientes (marcar)",
                        size=FONT_SIZE_TINY,
                        color=self.c["text_muted"],
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [self._checkbox(cod, f"{cod} - {nom}", self._clientes_check)],
                                    spacing=SPACING_SM,
                                )
                                for cod, nom in self._top_clientes()
                            ],
                            spacing=SPACING_XS,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=170,
                        padding=PADDING_SM,
                        bgcolor=self.c["surface_sunken"],
                        border_radius=RADIUS_SM,
                    ),
                ],
                spacing=SPACING_SM,
            ),
            expand=True,
        )
        ven_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Vendedores (marcar)",
                        size=FONT_SIZE_TINY,
                        color=self.c["text_muted"],
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [self._checkbox(vid, f"{vid} - {nom}", self._vendedores_check)],
                                    spacing=SPACING_SM,
                                )
                                for vid, nom in self._top_vendedores()
                            ],
                            spacing=SPACING_XS,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=170,
                        padding=PADDING_SM,
                        bgcolor=self.c["surface_sunken"],
                        border_radius=RADIUS_SM,
                    ),
                ],
                spacing=SPACING_SM,
            ),
            expand=True,
        )

        crear = ft.Container(
            content=ft.Column(
                [
                    _section_header(self.c, "Crear grupo de prioridad", ft.Icons.PLAYLIST_ADD),
                    ft.Row(
                        [
                            self._name,
                            ft.ElevatedButton(
                                "Guardar grupo", icon=ft.Icons.SAVE, on_click=self._save
                            ),
                        ],
                        spacing=SPACING_MD,
                    ),
                    ft.Container(height=SPACING_SM),
                    ft.Row([cli_section, ven_section], spacing=SPACING_2XL, expand=True),
                ],
                spacing=SPACING_SM,
            ),
            padding=PADDING_LG,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        accion = ft.Container(
            content=ft.Row(
                [
                    self._groups_dd,
                    ft.ElevatedButton(
                        "Exportar grupo", icon=ft.Icons.DOWNLOAD, on_click=self._export
                    ),
                    ft.OutlinedButton("Eliminar", icon=ft.Icons.DELETE, on_click=self._delete),
                ],
                spacing=SPACING_MD,
                wrap=True,
            ),
            padding=PADDING_LG,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        cols: list[ft.Control] = [crear, accion]
        if self._selected is not None:
            lines = self._store.filter_df(self._df, self._selected)
            nom = self._selected.get("nombre", "")
            if lines is not None and len(lines):
                an = PedidosAnalytics(lines)
                k = an.get_kpis()
                cols.append(
                    _kpi_row(
                        self.c,
                        [
                            ("Items", f"{k.get('total_items', 0):,}", "items"),
                            ("Saldo", f"{k.get('saldo_total', 0):,.0f}", "saldo"),
                            ("Valor S/", f"{k.get('valor_total', 0):,.0f}", "valor"),
                            ("Clientes", f"{k.get('n_clientes', 0):,}", "porcentaje"),
                        ],
                    )
                )
                cols.append(
                    build_master_table(
                        self.c,
                        lines,
                        self._COLS_LINEAS,
                        {},
                        None,
                        False,
                        lambda c, t: None,
                        lambda c: None,
                        lambda: None,
                        on_row_click=None,
                        drillable_cols=set(),
                        page_limit=100,
                    )
                )
            else:
                cols.append(
                    ft.Text(
                        f"Grupo '{nom}' no tiene lineas coincidentes",
                        size=FONT_SIZE_SMALL,
                        color=self.c["warning"],
                    )
                )
        return ft.Column(cols, spacing=SPACING_LG, expand=True, scroll=ft.ScrollMode.AUTO)

    def _top_clientes(self) -> list[tuple[str, str]]:
        df = self._df
        if df is None or "COD_CLIENTE" not in df.columns:
            return []
        g = (
            df.groupby("COD_CLIENTE", dropna=False)
            .agg(nom=("NOM_CLIENTE", "first"), saldo=("saldo", "sum"))
            .reset_index()
        )
        g = g.sort_values("saldo", ascending=False).head(40)
        return [(str(r["COD_CLIENTE"]), str(r["nom"])[:22]) for _, r in g.iterrows()]

    def _top_vendedores(self) -> list[tuple[str, str]]:
        df = self._df
        if df is None or "ID_VENDEDOR" not in df.columns:
            return []
        g = (
            df.groupby("ID_VENDEDOR", dropna=False)
            .agg(nom=("NOM_VENDEDOR", "first"), saldo=("saldo", "sum"))
            .reset_index()
        )
        g = g.sort_values("saldo", ascending=False)
        return [(str(r["ID_VENDEDOR"]), str(r["nom"])[:22]) for _, r in g.iterrows()]


# ---------------------------------------------------------------------------
# ColaView (Cola Despacho)
# ---------------------------------------------------------------------------
class ColaView:
    _COLS_COLA = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("NOM_CLIENTE", "Cliente", None),
        ("NOM_VENDEDOR", "Vendedor", None),
        ("cond_familia", "Familia", None),
        ("SKU", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("CAN_PEDIDO", "Pedido", "num"),
        ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Saldo", "num"),
        ("stock_api_ves", "Stock VES", "num"),
        ("stock_api_121", "Stock 121", "num"),
        ("cant_a_despachar", "A despachar", "num"),
        ("cajas_a_despachar", "Cajas", "num"),
    ]

    def __init__(self, colors: dict, on_snack=None) -> None:
        self.c = colors
        self._on_snack = on_snack
        self._df: pd.DataFrame | None = None
        self._sort_states: dict[str, tuple] = {}
        self._host: ft.Container | None = None

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        if self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def _on_toggle_sort(self, key: str, col: str) -> None:
        cur = self._sort_states.get(key, (None, False))
        self._sort_states[key] = (col, not cur[1]) if cur[0] == col else (col, False)
        self._render_into()

    def _export(self, e=None) -> None:
        if self._df is None or len(self._df) == 0:
            return
        cola = PedidosAnalytics(self._df).get_cola_despacho()
        if len(cola) == 0:
            if self._on_snack:
                self._on_snack("No hay lineas listas para despachar", "#F59E0B")
            return
        try:
            out = export_cola_despacho(cola)
            if self._on_snack:
                self._on_snack(f"Cola despacho exportada: {out.name}", "#10B981")
        except Exception as ex:
            if self._on_snack:
                self._on_snack(f"Error exportando: {ex}", "#EF4444")

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._host.content = self._build_content()
        self._host.update()

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para ver la cola de despacho")
        cola = PedidosAnalytics(self._df).get_cola_despacho()
        if len(cola) == 0:
            return empty_state(self.c, "Sin stock VES disponible: no hay despacho inmediato")

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LOCAL_SHIPPING, size=18, color=self.c["accent"]),
                    ft.Text(
                        "Cola de despacho manual (cargar en el ERP por ID_PEDIDO)",
                        size=FONT_SIZE_MEDIUM,
                        weight=ft.FontWeight.W_700,
                        color=self.c["text_primary"],
                    ),
                    ft.Container(expand=True),
                    ft.ElevatedButton(
                        "Exportar cola", icon=ft.Icons.DOWNLOAD, on_click=self._export
                    ),
                ],
                spacing=SPACING_MD,
            ),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )

        kpis = _kpi_row(
            self.c,
            [
                ("Lineas a despachar", f"{len(cola):,}", "items"),
                ("Unidades", f"{cola['cant_a_despachar'].sum():,.0f}", "saldo"),
                ("Cajas", f"{cola['cajas_a_despachar'].sum():,.0f}", "cajas"),
                ("Pedidos", f"{cola['ID_PEDIDO'].nunique():,}", "porcentaje"),
            ],
        )
        info = ft.Text(
            "cant_a_despachar = min(saldo, stock VES). El stock 121 (QC) / otros almacenes se muestra solo como informacion.",
            size=FONT_SIZE_TINY,
            color=self.c["text_muted"],
        )
        tabla = build_sortable_table(
            self.c,
            cola,
            self._COLS_COLA,
            "cola",
            self._sort_states,
            self._on_toggle_sort,
            page_limit=100,
        )
        return ft.Column([header, kpis, info, tabla], spacing=SPACING_LG, expand=True)
