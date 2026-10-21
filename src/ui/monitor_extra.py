"""
Vistas extra del monitor: Resumen, Alertas y Configuracion.

- ResumenView  (Resumen): KPIs globales/segmentados + banner de estado de stock
                + rankings de vendedores y clientes (top 5).
- AlertsView   (Alertas): reglas operativas (vencidos, por vencer, 100% atendible,
                sin stock, sin catalogo, API offline) con severidad y detalle clickeable.
- ConfigView   (Configuracion): umbrales, toggles de alertas, snapshots y credenciales
                del API persistidos en .cache/config.json (UserConfig).

Misma convencion que monitor_views: set_colors(colors), set_data(df, api_state), build().
"""

from __future__ import annotations

import logging

import flet as ft
import pandas as pd

from src.config.settings import S1_API_KEY, S1_API_URL, UserConfig
from src.core.alerts import ALERTS, compute_alerts
from src.core.analytics import COND_FAMILIA_ORDER, PedidosAnalytics, summarize_df
from src.ui.components import build_sortable_table, empty_state, kpi_card
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
    SPACING_XS,
)
from src.ui.monitor_views import _card, _chip, _dropdown, _kpi_row, _section_header

_log = logging.getLogger("g360.pedido_vigencias")


def _severity_color(colors: dict, severity: str) -> str:
    return colors.get(
        severity,  # error / warning / success / info son claves del tema
        colors.get("accent", "#10B981"),
    )


def _present(df: pd.DataFrame, columns: list[tuple[str, str, str | None]]) -> list:
    """Solo columnas existentes en el DataFrame."""
    return [c for c in columns if c[0] in df.columns]


def _severity_card(colors: dict, label: str, value: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Column([
            ft.Text(value, size=FONT_SIZE_LARGE, weight=ft.FontWeight.W_700,
                    color=color, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(label.upper(), size=FONT_SIZE_TINY, color=colors["text_muted"]),
        ], spacing=SPACING_XS),
        padding=PADDING_SM,
        bgcolor=colors["surface"],
        border_radius=RADIUS_SM,
        border=ft.BorderSide(1, colors["border"]),
        expand=True,
    )


# ---------------------------------------------------------------------------
# Base comun de las vistas del monitor
# ---------------------------------------------------------------------------
class _MonitorBase:
    def __init__(self, colors: dict) -> None:
        self.c = colors
        self._df: pd.DataFrame | None = None
        self._api_state = "offline"
        self._cond = "TODAS"
        self._host: ft.Container | None = None
        self._cond_row = ft.Row(spacing=SPACING_SM, wrap=True)
        self._sort_states: dict[str, tuple] = {}

    def set_colors(self, colors: dict) -> None:
        self.c = colors

    def set_data(self, df, api_state: str = "offline") -> None:
        self._df = df
        self._api_state = api_state or "offline"
        if self._host is not None and getattr(self._host, "page", None) is not None:
            self._render_into()

    def build(self) -> ft.Container:
        self._host = ft.Container(expand=True)
        self._host.content = self._build_content()
        return self._host

    def _render_into(self) -> None:
        if self._host is None or getattr(self._host, "page", None) is None:
            return
        self._host.content = self._build_content()
        try:
            self._host.update()
        except Exception as ex:
            _log.warning("[MonitorExtra] _render_into fallo: %s", ex)

    def _cond_options(self) -> list[str]:
        if self._df is None or "cond_familia" not in self._df.columns:
            return []
        present = set(self._df["cond_familia"].dropna().astype(str).unique())
        return [c for c in COND_FAMILIA_ORDER if c in present]

    def _filtered(self) -> pd.DataFrame | None:
        df = self._df
        if df is None or len(df) == 0:
            return df
        if self._cond != "TODAS" and "cond_familia" in df.columns:
            df = df[df["cond_familia"] == self._cond].reset_index(drop=True)
        return df

    def _on_cond(self, label: str, e=None) -> None:
        self._cond = label
        self._render_into()

    def _on_toggle_sort(self, key: str, col: str) -> None:
        cur = self._sort_states.get(key, (None, False))
        if cur[0] == col:
            self._sort_states[key] = (col, not cur[1])
        else:
            self._sort_states[key] = (col, False)
        self._render_into()

    def _cond_chips(self) -> list[ft.Chip]:
        chips = [_chip("Todas", lambda e, lbl="TODAS": self._on_cond(lbl),
                       self._cond == "TODAS", self.c)]
        for fam in self._cond_options():
            chips.append(_chip(
                fam,
                lambda e, lbl=fam: self._on_cond(lbl),
                self._cond == fam,
                self.c,
                key="warning" if fam == "CANJE" else "accent",
            ))
        return chips

    def _cond_box(self, label: str = "Condicion de pago (chips)") -> ft.Container:
        self._cond_row.controls = self._cond_chips()
        return ft.Container(
            content=ft.Column([
                ft.Text(label, size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                self._cond_row,
            ], spacing=SPACING_SM),
            padding=PADDING_MD,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, self.c["border"]),
        )


# ---------------------------------------------------------------------------
# ResumenView (Resumen / KPIs)
# ---------------------------------------------------------------------------
class ResumenView(_MonitorBase):
    _COLS_VENDEDORES = [
        ("ID_VENDEDOR", "ID", None), ("NOM_VENDEDOR", "Vendedor", None),
        ("items", "Items", "num"), ("saldo", "Vig. Total", "num"),
        ("valor", "Valor S/", "num"), ("stock_VES", "Stock VES", "num"),
        ("disp_cub_VES", "Disp. Cub.", "num"),
    ]
    _COLS_CLIENTES = [
        ("COD_CLIENTE", "Cod.", None), ("NOM_CLIENTE", "Cliente", None),
        ("items", "Items", "num"), ("saldo", "Saldo", "num"),
        ("valor", "Valor S/", "num"), ("cajas", "Cajas", "num"),
    ]
    _COLS_CLIENTES_DRILL = [
        ("COD_CLIENTE", "Cod.", None), ("NOM_CLIENTE", "Cliente", None),
        ("items", "Items", "num"), ("pedido", "Pedido", "num"),
        ("despacho", "Desp.", "num"), ("saldo", "Vig.", "num"),
        ("cajas", "Cajas", "num"), ("valor", "Valor S/", "num"),
        ("stock_VES", "Stock VES", "num"), ("disp_cub_VES", "Disp. Cub.", "num"),
    ]
    _COLS_PEDIDOS_DRILL = [
        ("ID_PEDIDO", "ID Pedido", None), ("NRO_DOCUMENTO", "OC", None),
        ("items", "Items", "num"), ("pedido", "Pedido", "num"),
        ("despacho", "Desp.", "num"), ("saldo", "Vig.", "num"),
        ("por_atendido", "% Aten.", "pct"), ("cajas", "Cajas", "num"),
        ("valor_pedido", "Monto S/", "num"), ("por_atendido_valor", "% Monto", "pct"),
        ("stock_VES", "Stock VES", "num"), ("disp_cub_VES", "Disp. Cub.", "num"),
    ]
    _COLS_LINEAS_DRILL = [
        ("ID_PEDIDO", "ID Pedido", None), ("NRO_DOCUMENTO", "OC", None),
        ("SKU", "SKU", None), ("NOM_ARTICULO", "Producto", None),
        ("estado_linea", "Estado Linea", None),
        ("CAN_PEDIDO", "Pedido", "num"), ("CAN_DESPACHO", "Desp.", "num"),
        ("saldo", "Vig.", "num"), ("cajas", "Cajas", "num"),
        ("stock_api_ves", "Stock VES", "num"), ("valor_saldo", "Valor S/", "num"),
    ]

    def __init__(self, colors: dict) -> None:
        super().__init__(colors)
        self._ruta: list[dict] = []

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para ver el resumen operativo")
        df = self._filtered()
        if df is None or len(df) == 0:
            return empty_state(self.c, "Sin resultados con la condicion seleccionada")

        summ = summarize_df(df)

        banner = self._stock_banner()
        kpis = [
            ("Pendiente S/", f"S/ {summ['valor']:,.0f}", "valor"),
            ("Unidades", f"{summ['unidades']:,.0f}", "saldo"),
            ("Cajas", f"{summ['cajas']:,}", "cajas"),
            ("Pedidos", f"{summ['pedidos']:,}", "items"),
            ("Clientes", f"{summ['clientes']:,}", "porcentaje"),
            ("Vendedores", f"{summ['vendedores']:,}", "porcentaje"),
        ]
        kpi_row = _kpi_row(self.c, kpis)

        venc, porv, atend = 0, 0, 0
        if "saldo" in df.columns:
            pend = df[df["saldo"] > 0]
            if "estado_vigencia" in pend.columns:
                ev = pend["estado_vigencia"].astype(str)
                venc = int(ev.eq("VENCIDO").sum())
                porv = int(ev.eq("POR VENCER").sum())
            atend = int(summ["atendibles"])

        sev = [
            _severity_card(self.c, "Vencidos", f"{venc:,}", self.c["error"]),
            _severity_card(self.c, "Por vencer", f"{porv:,}", self.c["warning"]),
            _severity_card(self.c, "Atend. 100%",
                           f"{atend:,} ({summ['atendibles_pct']:.0f}%)", self.c["success"]),
        ]
        sev_row = ft.Row(sev, spacing=SPACING_2XL)

        an = PedidosAnalytics(df)
        vendedores = an.get_vendedores_pendientes(top=5)
        clientes = an.get_top_clientes_deudores(top=5, by="valor")

        def build_t(key: str, title: str, icon, table_df, columns, on_row_click=None):
            if table_df is None or len(table_df) == 0:
                body = empty_state(self.c, "Sin datos")
            else:
                body = build_sortable_table(self.c, table_df, _present(table_df, columns),
                                            key, self._sort_states, self._on_toggle_sort,
                                            on_row_click=on_row_click,
                                            page_limit=6)
            return _card(self.c, _section_header(self.c, title, icon,
                                                 f"{len(table_df) if table_df is not None else 0} registros"),
                         body)

        tab_rank = ft.Row([
            build_t("res_vendedores", "Top vendedores mom", ft.Icons.PERSON, vendedores, self._COLS_VENDEDORES,
                    self._on_vendedor_click),
            build_t("res_clientes", "Top clientes (nos deben)", ft.Icons.PEOPLE, clientes, self._COLS_CLIENTES,
                    self._on_cliente_click),
        ], spacing=SPACING_2XL, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

        children: list[ft.Control] = [
            banner,
            ft.Container(height=SPACING_SM),
            self._cond_box(),
            ft.Container(height=SPACING_SM),
            ft.Text("KPIs (pendientes con saldo > 0)", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
            kpi_row,
            ft.Container(height=SPACING_SM),
            sev_row,
            ft.Container(height=SPACING_SM),
            tab_rank,
        ]

        drill = self._build_drill_panel()
        if drill is not None:
            children += [
                ft.Container(height=SPACING_SM),
                drill,
            ]

        return ft.Column(children, spacing=SPACING_MD, expand=True, scroll=ft.ScrollMode.AUTO)

    # ------------------------------------------------------------------
    # Flujo drill: vendedor -> clientes -> pedidos -> lineas
    # ------------------------------------------------------------------
    def _on_cond(self, label: str, e=None) -> None:
        self._cond = label
        self._ruta = []
        self._render_into()

    def _on_vendedor_click(self, row: dict) -> None:
        vid = str(row.get("ID_VENDEDOR", "") or "")
        if not vid:
            return
        vn = str(row.get("NOM_VENDEDOR", "") or "")
        self._ruta = [{"tipo": "vendedor", "id": vid, "label": vn or vid}]
        self._render_into()

    def _on_cliente_click(self, row: dict) -> None:
        cid = str(row.get("COD_CLIENTE", "") or "")
        if not cid:
            return
        cn = str(row.get("NOM_CLIENTE", "") or "")
        if self._df is None or "COD_CLIENTE" not in self._df.columns:
            return
        self._ruta = [{"tipo": "cliente", "id": cid, "label": cn or cid}]
        self._render_into()

    def _on_cliente_drill(self, row: dict) -> None:
        cid = str(row.get("COD_CLIENTE", "") or "")
        if not cid:
            return
        cn = str(row.get("NOM_CLIENTE", "") or "")
        base = self._nivel_df()
        if base is None or "COD_CLIENTE" not in base.columns:
            return
        if base[base["COD_CLIENTE"].astype(str) == cid].empty:
            return
        self._ruta = self._ruta[:1] + [{"tipo": "cliente", "id": cid, "label": cn or cid}]
        self._render_into()

    def _on_pedido_drill(self, row: dict) -> None:
        pid = str(row.get("ID_PEDIDO", "") or "")
        if not pid:
            return
        base = self._nivel_df()
        if base is None or "ID_PEDIDO" not in base.columns:
            return
        if base[base["ID_PEDIDO"].astype(str) == pid].empty:
            return
        label = str(row.get("NRO_DOCUMENTO", "") or pid)
        self._ruta = self._ruta[:2] + [{"tipo": "pedido", "id": pid, "label": label}]
        self._render_into()

    def _nivel_df(self) -> pd.DataFrame | None:
        """DataFrame de lineas del nivel actual del drill (filtrado por la ruta)."""
        if self._df is None:
            return None
        base = self._filtered()
        if base is None:
            return None
        for nivel in self._ruta:
            col = {"vendedor": "ID_VENDEDOR", "cliente": "COD_CLIENTE", "pedido": "ID_PEDIDO"}[nivel["tipo"]]
            if col not in base.columns:
                return None
            base = base[base[col].astype(str) == str(nivel["id"])]
        return base.reset_index(drop=True)

    def _volver(self, idx: int | None = None) -> None:
        """Vuelve a un nivel del drill (None = raiz/sin drill)."""
        if idx is None:
            self._ruta = []
        else:
            self._ruta = self._ruta[: idx + 1]
        self._render_into()

    def _build_drill_panel(self) -> ft.Control | None:
        if not self._ruta:
            return None
        base = self._nivel_df()
        if base is None or len(base) == 0:
            return None
        an = PedidosAnalytics(base)
        nivel = self._ruta[-1]
        tipo = nivel["tipo"]

        crumb_parts: list[ft.Control] = []
        crumb_parts.append(ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ARROW_BACK, size=14, color=self.c["accent"]),
                ft.Text("Resumen", size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_600, color=self.c["text_muted"]),
            ], spacing=SPACING_XS),
            padding=PADDING_SM,
            border_radius=RADIUS_SM,
            on_click=lambda e: self._volver(None),
            ink=True,
        ))
        for i, nivel_i in enumerate(self._ruta):
            es_actual = i == len(self._ruta) - 1
            crumb_parts.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=14, color=self.c["text_muted"]))
            crumb_parts.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.UNFOLD_MORE if es_actual else ft.Icons.ARROW_FORWARD,
                            size=13, color=self.c["accent"] if es_actual else self.c["text_muted"]),
                    ft.Text(nivel_i["label"], size=FONT_SIZE_SMALL,
                            weight=ft.FontWeight.W_700 if es_actual else ft.FontWeight.W_500,
                            color=self.c["text_primary"] if es_actual else self.c["text_muted"]),
                ], spacing=SPACING_XS),
                padding=PADDING_SM,
                border_radius=RADIUS_SM,
                bgcolor=self.c["surface_variant"] if es_actual else None,
                border=ft.BorderSide(1, self.c["accent"] if es_actual else self.c["border"]),
                on_click=lambda e, idx=i: self._volver(idx),
                ink=True,
            ))

        titulo = {
            "vendedor": "Clientes del vendedor",
            "cliente": "Pedidos del cliente",
            "pedido": "Lineas del pedido",
        }.get(tipo, "Desglose")
        subt = {
            "vendedor": f"{base['COD_CLIENTE'].nunique() if 'COD_CLIENTE' in base else 0} clientes",
            "cliente": f"{base['ID_PEDIDO'].nunique() if 'ID_PEDIDO' in base else 0} pedidos",
            "pedido": f"{len(base)} lineas",
        }.get(tipo, f"{len(base)} registros")

        body: ft.Control
        cols = None
        row_click = None
        if tipo == "vendedor":
            tbl = an.get_clientes_by_vendedor(nivel["id"])
            cols = self._COLS_CLIENTES_DRILL
            row_click = self._on_cliente_drill
        elif tipo == "cliente":
            tbl = an.get_pedidos_by_cliente(nivel["id"])
            cols = self._COLS_PEDIDOS_DRILL
            row_click = self._on_pedido_drill
        else:
            tbl = base
            cols = self._COLS_LINEAS_DRILL
            row_click = None
            subt = f"{len(base)} lineas"

        if tbl is None or len(tbl) == 0:
            body = empty_state(self.c, "Sin resultados en este nivel")
        else:
            body = build_sortable_table(self.c, tbl, _present(tbl, cols),
                                        f"res_drill_{tipo}_{nivel['id']}", self._sort_states,
                                        self._on_toggle_sort, on_row_click=row_click, page_limit=10)

        return _card(
            self.c,
            _section_header(self.c, titulo, ft.Icons.SOUTH_WEST, subt),
            ft.Column([
                ft.Row(crumb_parts, spacing=SPACING_XS, wrap=True),
                ft.Container(height=SPACING_SM),
                body,
            ], spacing=SPACING_SM, tight=True),
        )

    def _stock_banner(self) -> ft.Container:
        df = self._df
        if df is not None and "stock_origen" in df.columns:
            origen_counts = df["stock_origen"].value_counts().to_dict()
            tiene_api = origen_counts.get("API", 0) > 0
        else:
            tiene_api = self._api_state == "online"
        ok = tiene_api
        color = self.c["success"] if ok else self.c["warning"]
        icon = ft.Icons.CLOUD_DONE if ok else ft.Icons.CLOUD_OFF
        text = "Stock 100% del API de Render (actualizado)" if ok else \
            "Stock SIN API: todo en 0, solo saldo de pedidos (refresca el API)"
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=18, color=color),
                ft.Text(text, size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_700, color=color),
                ft.Container(expand=True),
                ft.Text(self._api_state.upper(), size=FONT_SIZE_TINY, color=self.c["text_muted"]),
            ], spacing=SPACING_SM),
            padding=ft.Padding(PADDING_SM, PADDING_SM, PADDING_SM, PADDING_SM),
            bgcolor=self.c["surface"],
            border_radius=RADIUS_SM,
            border=ft.BorderSide(1, color),
        )


# ---------------------------------------------------------------------------
# AlertsView (Alertas)
# ---------------------------------------------------------------------------
class AlertsView(_MonitorBase):
    _COLS_DETALLE = [
        ("ID_PEDIDO", "ID Pedido", None),
        ("NRO_DOCUMENTO", "OC", None),
        ("ID_ARTICULO", "SKU", None),
        ("NOM_ARTICULO", "Producto", None),
        ("cond_familia", "Familia", None),
        ("saldo", "Pendiente", "num"),
        ("stock_real", "Stock VES", "num"),
        ("valor_saldo", "Valor S/", "num"),
        ("estado_vigencia", "Vigencia", None),
    ]

    def __init__(self, colors: dict, config: UserConfig | None = None) -> None:
        super().__init__(colors)
        self._config = config or UserConfig()
        self._sel_key: str | None = None

    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            return empty_state(self.c, "Carga datos para ver alertas")
        df = self._filtered()
        if df is None or len(df) == 0:
            return empty_state(self.c, "Sin resultados con la condicion seleccionada")

        alerts = compute_alerts(
            df,
            umbral_por_vencer_pct=float(self._config.get("umbral_por_vencer_pct", 75.0)),
            toggles=self._config.get("alerta_toggles", {}),
            api_state=self._api_state,
        )

        header = _section_header(self.c, "Alertas operativas", ft.Icons.NOTIFICATIONS,
                                 f"{len(alerts)} reglas activas")

        alert_cards = [self._alert_clickable(al) for al in alerts]
        if not alert_cards:
            alert_cards = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=self.c["success"]),
                        ft.Text("Sin alertas activas", size=FONT_SIZE_SMALL, color=self.c["text_muted"]),
                    ], spacing=SPACING_SM),
                    padding=PADDING_MD,
                    bgcolor=self.c["surface"],
                    border_radius=RADIUS_MD,
                    border=ft.BorderSide(1, self.c["success"]),
                )
            ]

        detail = None
        for al in alerts:
            if al["key"] == self._sel_key:
                detail = al
                break

        children: list[ft.Control] = [
            header,
            ft.Container(height=SPACING_SM),
            self._cond_box("Condicion de pago (chips)"),
            ft.Container(height=SPACING_SM),
            *alert_cards,
        ]
        if detail is not None and len(detail.get("lines", pd.DataFrame())) > 0:
            lines = detail["lines"]
            children += [
                ft.Container(height=SPACING_SM),
                _card(
                    self.c,
                    _section_header(self.c, f"Detalle: {detail['title']}", ft.Icons.LIST_ALT,
                                    f"{detail['count_pedidos']} pedidos / {detail['lineas']} lineas"),
                    build_sortable_table(self.c, lines, _present(lines, self._COLS_DETALLE),
                                         f"alert_{detail['key']}", self._sort_states,
                                         self._on_toggle_sort, page_limit=10)
                    if len(lines) else empty_state(self.c, "Sin lineas"),
                ),
            ]

        return ft.Column(children, spacing=SPACING_SM, expand=True, scroll=ft.ScrollMode.AUTO)

    def _alert_clickable(self, al: dict) -> ft.Container:
        color = _severity_color(self.c, al["severity"])
        selected = self._sel_key == al["key"]
        return ft.Container(
            content=ft.Row([
                ft.Icon(al["icon"], size=22, color=color),
                ft.Column([
                    ft.Text(al["title"], size=FONT_SIZE_MEDIUM + 2, weight=ft.FontWeight.W_700,
                            color=self.c["text_primary"]),
                    ft.Text(al["description"], size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                ], spacing=SPACING_XS, expand=True),
                ft.Column([
                    ft.Text(f"{al['count_pedidos']} pedidos", size=FONT_SIZE_SMALL,
                            weight=ft.FontWeight.W_700, color=self.c["text_primary"]),
                    ft.Text(f"{al['lineas']} lineas", size=FONT_SIZE_TINY, color=self.c["text_muted"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=SPACING_XS),
                ft.Column([
                    ft.Text(f"{al['unidades']:,.0f} und", size=FONT_SIZE_SMALL,
                            color=self.c["text_primary"]),
                    ft.Text(f"S/ {al['valor']:,.0f}", size=FONT_SIZE_SMALL,
                            color=color, weight=ft.FontWeight.W_700),
                ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=SPACING_XS),
                ft.Icon(ft.Icons.UNFOLD_MORE if selected else ft.Icons.UNFOLD_LESS,
                        size=16, color=self.c["text_muted"]),
            ], spacing=SPACING_MD, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(PADDING_SM, PADDING_SM, PADDING_SM, PADDING_SM),
            bgcolor=self.c["surface_variant"] if selected else self.c["surface"],
            border_radius=RADIUS_MD,
            border=ft.BorderSide(1, color),
            ink=True,
            on_click=lambda e, k=al["key"]: self._toggle(k),
        )

    def _toggle(self, key: str) -> None:
        self._sel_key = key if self._sel_key != key else None
        self._render_into()


# ---------------------------------------------------------------------------
# ConfigView (Configuracion)
# ---------------------------------------------------------------------------
class ConfigView(_MonitorBase):
    def __init__(self, colors: dict, config: UserConfig | None = None,
                 on_saved=None) -> None:
        super().__init__(colors)
        self._config = config or UserConfig()
        self._on_saved = on_saved
        self._umbral_tf = ft.TextField(
            label="Umbral 'por vencer' (% de vigencia consumida)",
            value=str(self._config.get("umbral_por_vencer_pct", 75.0)),
            width=280, text_size=FONT_SIZE_SMALL,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._snap_auto = ft.Checkbox(
            label="Guardar snapshot automatico al cargar datos",
            value=bool(self._config.get("snapshot_auto", True)),
        )
        self._snap_keep_dd = _dropdown(
            [ft.dropdown.Option(str(k), f"{k}") for k in (10, 30, 60, 100)],
            value=str(self._config.get("snapshot_keep", 30)),
            label="Mantener ultimos N snapshots", width=220,
        )
        self._api_url_tf = ft.TextField(
            label="URL API stock (Render)", value=str(self._config.get("api_url", S1_API_URL)),
            width=420, text_size=FONT_SIZE_SMALL,
        )
        self._api_key_tf = ft.TextField(
            label="API key", value=str(self._config.get("api_key", S1_API_KEY)),
            width=200, text_size=FONT_SIZE_SMALL,
            password=True, can_reveal_password=True,
        )
        self._toggles: dict[str, ft.Checkbox] = {}
        for rule in ALERTS:
            self._toggles[rule["key"]] = ft.Checkbox(
                label=rule["title"], value=self._config.alert_enabled(rule["key"]),
            )

    def _build_content(self) -> ft.Control:
        header = _section_header(self.c, "Configuracion", ft.Icons.SETTINGS, "guarda en .cache/config.json")

        alert_box = _card(
            self.c,
            _section_header(self.c, "Reglas de alerta", ft.Icons.NOTIFICATIONS, "activa/desactiva"),
            ft.Column(list(self._toggles.values()), spacing=SPACING_XS, tight=True),
        )
        vig_box = _card(
            self.c,
            _section_header(self.c, "Vigencia", ft.Icons.ACCESS_TIME, ""),
            ft.Column([self._umbral_tf], spacing=SPACING_SM, tight=True),
        )
        snap_box = _card(
            self.c,
            _section_header(self.c, "Snapshots", ft.Icons.HISTORY, ""),
            ft.Column([self._snap_auto, self._snap_keep_dd], spacing=SPACING_MD, tight=True),
        )
        api_box = _card(
            self.c,
            _section_header(self.c, "Stock API", ft.Icons.CLOUD, "el stock siempre viene de aqui"),
            ft.Column([self._api_url_tf, self._api_key_tf], spacing=SPACING_MD, tight=True),
        )

        filas = ft.Row([
            ft.Column([vig_box, snap_box], spacing=SPACING_LG, expand=True),
            ft.Column([alert_box], spacing=SPACING_LG, expand=2),
        ], spacing=SPACING_2XL, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

        btn = ft.ElevatedButton("Guardar configuracion", icon=ft.Icons.SAVE, on_click=self._on_save)
        reset = ft.OutlinedButton("Restaurar valores", icon=ft.Icons.RESTART_ALT, on_click=self._on_reset)

        return ft.Column([
            header,
            ft.Container(height=SPACING_SM),
            filas,
            ft.Container(height=SPACING_MD),
            ft.Row([btn, reset], spacing=SPACING_SM),
        ], spacing=SPACING_SM, expand=True, scroll=ft.ScrollMode.AUTO)

    def _on_save(self, e=None) -> None:
        try:
            umbral = float((self._umbral_tf.value or "").replace(",", ".").strip() or 75.0)
            umbral = max(1.0, min(100.0, umbral))
        except ValueError:
            umbral = 75.0
        self._config.set("umbral_por_vencer_pct", umbral)
        self._config.set("snapshot_auto", bool(self._snap_auto.value))
        keep = int((self._snap_keep_dd.value or "30").strip() or 30)
        self._config.set("snapshot_keep", max(1, keep))
        url = (self._api_url_tf.value or "").strip()
        key = (self._api_key_tf.value or "").strip()
        if url:
            self._config.set("api_url", url)
        if key:
            self._config.set("api_key", key)
        self._config.set("alerta_toggles", {k: bool(c.value) for k, c in self._toggles.items()})
        self._config.save()
        _log.info("[Config] Configuracion guardada: %s", self._config.data)
        if self._on_saved:
            self._on_saved()
        else:
            self._render_into()

    def _on_reset(self, e=None) -> None:
        self._config.reset().save()
        self._umbral_tf.value = str(self._config.get("umbral_por_vencer_pct", 75.0))
        self._snap_auto.value = bool(self._config.get("snapshot_auto", True))
        self._snap_keep_dd.value = str(self._config.get("snapshot_keep", 30))
        self._api_url_tf.value = str(self._config.get("api_url", S1_API_URL))
        self._api_key_tf.value = str(self._config.get("api_key", S1_API_KEY))
        for key, cb in self._toggles.items():
            cb.value = self._config.alert_enabled(key)
        self._render_into()
        if self._on_saved:
            self._on_saved()