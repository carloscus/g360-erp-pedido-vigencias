"""
Vista Prioridades: seguimiento manual persistente por pedido o cliente.

Lo que no esta en el Excel ni en el API:
- Prioridad (P1..P5) asignada por el usuario.
- Ancla (importante para el usuario, no un filtro).
- Observaciones y fecha de proxima revision.

Todo se persiste en SQLite (tabla `seguimiento`) y sobrevive a cada carga.
La vista agrega el pendiente real desde el DataFrame actual (valor S/, saldo,
antiguedad) y lo combina con el estado de seguimiento guardado.

Misma convencion que las vistas del monitor: set_colors / set_data / build().
"""

from __future__ import annotations

import logging

import flet as ft
import pandas as pd

from src.core.db import PedidosDB
from src.ui.config import (
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    PADDING_LG,
    PADDING_SM,
    RADIUS_SM,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)
from src.ui.monitor_views import _card, _chip, _kpi_row, _section_header

_log = logging.getLogger("g360.pedido_vigencias")

MAX_FILAS = 120

_PRIO_OPTS: list[ft.dropdown.Option] = [
    ft.dropdown.Option("", "—"),
    ft.dropdown.Option("1", "P1"),
    ft.dropdown.Option("2", "P2"),
    ft.dropdown.Option("3", "P3"),
    ft.dropdown.Option("4", "P4"),
    ft.dropdown.Option("5", "P5"),
]

# Etiqueta de la vista -> tipo persistido en `seguimiento`
_DB_TIPO = {"pedidos": "pedido", "clientes": "cliente"}


def _db_tipo(tipo: str) -> str:
    return _DB_TIPO.get(tipo, tipo)


def _opt(df: pd.DataFrame, col: str, default=""):
    """Valor default para columnas opcionales."""
    return col if col in df.columns else default


class PrioridadesView:
    """Prioridad, anclas y observaciones persistentes por pedido o cliente."""

    def __init__(self, colors: dict, db: PedidosDB | None = None, on_snack=None) -> None:
        self.c = colors
        self._db = db or PedidosDB()
        self._on_snack = on_snack
        self._df: pd.DataFrame | None = None
        self._api_state = "offline"
        self._tipo = "pedidos"          # pedidos | clientes
        self._filtro = "todos"          # todos | anclados | priorizados
        self._host: ft.Container | None = None

    # ---------------------------------------------------------------
    # API publica (convencion del monitor)
    # ---------------------------------------------------------------
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
            _log.warning("[Prioridades] _render_into fallo: %s", ex)

    # ---------------------------------------------------------------
    # Datos
    # ---------------------------------------------------------------
    def _agregar(self) -> pd.DataFrame:
        """Agrega el pendiente por pedido o cliente con datos disponibles."""
        df = self._df
        if df is None or len(df) == 0:
            return pd.DataFrame()

        if self._tipo == "clientes":
            ref_col = "COD_CLIENTE"
            g = df.groupby(ref_col, dropna=False)
            ana_col = "COD_CLIENTE"
            deta = "pedidos"
        else:
            ref_col = "ID_PEDIDO"
            g = df.groupby(ref_col, dropna=False)
            ana_col = "ID_PEDIDO"
            deta = "antiguedad"

        valor_col = "valor_saldo" if "valor_saldo" in df.columns else "PEDIDO_IMPORTE_ARITCULO"
        saldo_col = "saldo" if "saldo" in df.columns else "CAN_PEDIDO"

        agg = g.agg(
            referencia=(ref_col, "first"),
            cliente=(_opt(df, "COD_CLIENTE", ""), "first"),
            nombre_cliente=(_opt(df, "NOM_CLIENTE", ""), "first"),
            vendedor=(_opt(df, "ID_VENDEDOR", ""), "first"),
            nombre_vendedor=(_opt(df, "NOM_VENDEDOR", ""), "first"),
            valor=(valor_col, "sum"),
            saldo=(saldo_col, "sum"),
            pedidos=(_opt(df, "ID_PEDIDO", ""), "nunique"),
            antiguedad=(_opt(df, "dias_desde_pedido", ""), "max"),
            estado=(_opt(df, "PEDIDO_ESTADO", ""), "first"),
        ).reset_index(drop=True)

        # Seleccion de columnas segun tipo
        if self._tipo == "clientes":
            out = agg[["referencia", "nombre_cliente", "vendedor", "nombre_vendedor",
                       "valor", "saldo", "pedidos"]]
            out["detalle"] = out["pedidos"].astype(int).astype(str) + " pedidos"
        else:
            out = agg[["referencia", "cliente", "nombre_cliente", "vendedor", "nombre_vendedor",
                       "valor", "saldo", "antiguedad", "estado"]]
            out["detalle"] = (
                out["antiguedad"].fillna(0).astype(int).astype(str) + " dias"
            )
        return out

    def _seguimiento_map(self) -> dict:
        try:
            regs = self._db.get_seguimientos(limit=5000)
            return {(r["tipo"], r["referencia"]): r for r in regs}
        except Exception as ex:
            _log.warning("[Prioridades] leer seguimiento fallo: %s", ex)
            return {}

    def _filas(self) -> list[dict]:
        """Construye las filas combinando agregado actual + seguimiento,
        aplica el filtro activo y ordena."""
        agregado = self._agregar()
        seg = self._seguimiento_map()

        filas: list[dict] = []
        db_t = _db_tipo(self._tipo)
        for _, r in agregado.iterrows():
            ref = str(r["referencia"])
            sg = seg.get((db_t, ref))
            filas.append({
                "ref": ref,
                "label": (r.get("nombre_cliente") or r.get("cliente") or r.get("vendedor") or ""),
                "detalle": str(r.get("detalle", "")),
                "valor": float(r.get("valor", 0) or 0),
                "saldo": float(r.get("saldo", 0) or 0),
                "estado": str(r.get("estado", "")) if self._tipo == "pedidos" else "",
                "anclado": bool(sg and sg.get("anclado")),
                "prioridad": sg.get("prioridad") if sg else None,
                "obs": (sg.get("observaciones") or "") if sg else "",
                "fecha": (sg.get("fecha_revision") or "") if sg else "",
                "_sg": sg,
            })

        if self._filtro == "anclados":
            filas = [f for f in filas if f["anclado"]]
        elif self._filtro == "priorizados":
            filas = [f for f in filas if f["prioridad"] is not None]

        filas.sort(key=lambda f: (not f["anclado"], f["prioridad"] is None, f["prioridad"] or 999, -f["valor"]))
        return filas[:MAX_FILAS]

    # ---------------------------------------------------------------
    # Acciones (persisten y refrescan)
    # ---------------------------------------------------------------
    def _sms(self, msg: str, color: str = "#10B981") -> None:
        if self._on_snack:
            self._on_snack(msg, color)

    def _on_tipo(self, label: str, e=None) -> None:
        self._tipo = label
        self._render_into()

    def _on_filtro(self, label: str, e=None) -> None:
        self._filtro = label
        self._render_into()

    def _on_prio(self, tipo: str, ref: str, e) -> None:
        val = (e.control.value or "").strip()
        self._db.upsert_seguimiento(_db_tipo(tipo), ref, prioridad=int(val) if val else None)
        self._sms(f"{tipo.upper()} {ref}: prioridad {val or 'sin prioridad'}")
        self._render_into()

    def _on_pin(self, tipo: str, ref: str, e=None) -> None:
        db_t = _db_tipo(tipo)
        estado = self._db.get_seguimiento(db_t, ref)
        anclado = not bool(estado and estado.get("anclado"))
        self._db.upsert_seguimiento(db_t, ref, anclado=anclado)
        self._sms(f"{tipo.upper()} {ref}: {'anclado' if anclado else 'desanclado'}")
        self._render_into()

    def _on_fecha(self, tipo: str, ref: str, e) -> None:
        val = (e.control.value or "").strip()
        self._db.upsert_seguimiento(_db_tipo(tipo), ref, fecha_revision=val or None)
        self._sms(f"{tipo.upper()} {ref}: revision {val or 'sin fecha'}")
        self._render_into()

    def _on_obs(self, tipo: str, ref: str, e) -> None:
        val = (e.control.value or "").strip()
        self._db.upsert_seguimiento(_db_tipo(tipo), ref, observaciones=val or None)
        # No se refresca para no perder el foco del campo
        self._sms(f"{tipo.upper()} {ref}: observaciones guardadas")

    # ---------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------
    def _build_content(self) -> ft.Control:
        if self._df is None or len(self._df) == 0:
            from src.ui.components import empty_state
            return empty_state(self.c, "Carga datos para asignar prioridades")

        agregado = self._agregar()
        filas = self._filas()

        total_valor = sum(f["valor"] for f in filas)
        total_saldo = sum(f["saldo"] for f in filas)
        n_ancl = sum(1 for f in filas if f["anclado"])
        n_prio = sum(1 for f in filas if f["prioridad"] is not None)

        chips = ft.Row([
            _chip("Pedidos", lambda e: self._on_tipo("pedidos"), self._tipo == "pedidos", self.c),
            _chip("Clientes", lambda e: self._on_tipo("clientes"), self._tipo == "clientes", self.c),
            ft.Container(width=SPACING_LG),
            _chip("Todos", lambda e: self._on_filtro("todos"), self._filtro == "todos", self.c),
            _chip("Anclados", lambda e: self._on_filtro("anclados"), self._filtro == "anclados", self.c),
            _chip("Priorizados", lambda e: self._on_filtro("priorizados"), self._filtro == "priorizados", self.c),
        ], spacing=SPACING_SM, wrap=True)

        kpis = _kpi_row(self.c, [
            ("Valor pendiente", f"S/ {total_valor:,.0f}", "valor"),
            ("Saldo units", f"{total_saldo:,.0f}", "saldo"),
            ("Anclados", f"{n_ancl:,}", "items"),
            ("Priorizados", f"{n_prio:,}", "porcentaje"),
        ])

        tabla = self._tabla(filas) if filas else self._sin_filas()

        hint = ft.Text(
            "La prioridad, anclas, observaciones y fecha de revision se guardan en SQLite "
            "y NO se pierden al cargar un nuevo archivo.",
            size=FONT_SIZE_TINY, color=self.c["text_muted"],
        )

        return ft.Column([
            _section_header(self.c, "Prioridades", ft.Icons.PRIORITY_HIGH,
                            f"{len(filas)} de {len(agregado)} referencias"),
            ft.Container(height=SPACING_SM),
            chips,
            ft.Container(height=SPACING_SM),
            kpis,
            ft.Container(height=SPACING_SM),
            tabla,
            hint,
        ], spacing=SPACING_SM, expand=True, scroll=ft.ScrollMode.AUTO)

    def _sin_filas(self) -> ft.Control:
        return _card(
            self.c,
            _section_header(self.c, "Nada para mostrar", ft.Icons.INBOX_OUTLINED),
            ft.Text("Cambia el filtro o selecciona otra fuente.", size=FONT_SIZE_SMALL,
                    color=self.c["text_muted"]),
        )

    def _tabla(self, filas: list[dict]) -> ft.Control:
        """Lista de filas editables: prio, pin, fecha y observaciones."""
        header = ft.Container(
            content=ft.Row([
                ft.Text("Referencia", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], width=110, expand=1),
                ft.Text("Cliente / Vendedor", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], expand=3),
                ft.Text("Detalle", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], width=110),
                ft.Text("Valor S/", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], width=100, text_align=ft.TextAlign.RIGHT),
                ft.Text("Prio", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], width=96),
                ft.Text("", width=36),
                ft.Text("Prox. revision", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], width=122),
                ft.Text("Observaciones", size=FONT_SIZE_TINY, weight=ft.FontWeight.W_700,
                        color=self.c["text_muted"], expand=2),
            ], spacing=SPACING_SM, tight=True),
            padding=ft.Padding(8, 4, 8, 4),
            bgcolor=self.c["surface_sunken"],
            border=ft.BorderSide(1, self.c["border"]),
        )

        rows = []
        for i, f in enumerate(filas):
            sel = self._tipo
            ref = f["ref"]
            seg = f["_sg"] or {}
            anclado = f["anclado"]
            prio = str(f["prioridad"]) if f["prioridad"] is not None else ""

            prio_dd = ft.Dropdown(
                value=prio, options=_PRIO_OPTS, width=96,
                text_size=FONT_SIZE_SMALL,
                on_change=lambda e, t=sel, r=ref: self._on_prio(t, r, e),
            )
            pin = ft.IconButton(
                icon=ft.Icons.PUSH_PIN if anclado else ft.Icons.PUSH_PIN_OUTLINED,
                icon_color=self.c["accent"] if anclado else self.c["text_muted"],
                icon_size=16,
                tooltip="Anclar / desanclar",
                on_click=lambda e, t=sel, r=ref: self._on_pin(t, r),
                padding=ft.Padding(2, 2, 2, 2),
            )
            fecha_tf = ft.TextField(
                value=f["fecha"], hint_text="dd/mm/aaaa", width=122,
                text_size=FONT_SIZE_SMALL,
                on_submit=lambda e, t=sel, r=ref: self._on_fecha(t, r, e),
                dense=True,
            )
            obs_tf = ft.TextField(
                value=f["obs"], hint_text="Observaciones...",
                text_size=FONT_SIZE_SMALL, expand=True,
                on_submit=lambda e, t=sel, r=ref: self._on_obs(t, r, e),
            )

            fila = ft.Container(
                content=ft.Row([
                    ft.Text(f["ref"], size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_700,
                            color=self.c["accent"] if anclado else self.c["text_primary"],
                            width=110, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=1),
                    ft.Text(str(f["label"])[:32], size=FONT_SIZE_SMALL,
                            color=self.c["text_secondary"], max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS, expand=3),
                    ft.Text(f["detalle"], size=FONT_SIZE_SMALL,
                            color=self.c["text_muted"], width=110),
                    ft.Text(f"S/ {f['valor']:,.0f}", size=FONT_SIZE_SMALL,
                            color=self.c["text_primary"], width=100,
                            text_align=ft.TextAlign.RIGHT, weight=ft.FontWeight.W_600),
                    prio_dd,
                    pin,
                    fecha_tf,
                    obs_tf,
                ], spacing=SPACING_SM, tight=False),
                padding=ft.Padding(8, 3, 8, 3),
                bgcolor=self.c["surface_variant"] if i % 2 else self.c["surface"],
                border_radius=RADIUS_SM,
            )
            rows.append(fila)

        return ft.Container(
            content=ft.Column([header, *rows], spacing=SPACING_XS, scroll=ft.ScrollMode.AUTO, tight=True),
            bgcolor=self.c["surface"],
            border_radius=RADIUS_SM,
            border=ft.BorderSide(1, self.c["border"]),
            padding=PADDING_SM,
            expand=True,
        )