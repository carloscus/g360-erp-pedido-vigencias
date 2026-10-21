"""Shared UI components for g360-erp-pedido-vigencias."""

from __future__ import annotations

import flet as ft
import pandas as pd

from src.config.theme import rgba
from src.ui.config import (
    FONT_SIZE_3XL,
    FONT_SIZE_LARGE,
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    MAX_TABLE_CELL_LENGTH,
    PADDING_LG,
    PADDING_SM,
    PADDING_XL,
    RADIUS_LG,
    RADIUS_MD,
    SPACING_SM,
    SPACING_XS,
    TABLE_PAGE_SIZE,
    kpi_card_style,
)


def kpi_card(colors: dict, label: str, value: str, color_key: str, size: str = "large") -> ft.Container:
    """Create a KPI card control.

    Args:
        colors: Theme color dict.
        label: Upper-label text.
        value: Main value text.
        color_key: Key into colors["kpis"] for the value color.
        size: "large" (dashboard-style, FONT_SIZE_3XL value, FONT_SIZE_TINY label)
              or "small" (detail-style, FONT_SIZE_LARGE value, FONT_SIZE_SMALL label).
    """
    if size == "large":
        value_size = FONT_SIZE_3XL
        label_size = FONT_SIZE_TINY
        label_weight = ft.FontWeight.W_600
        style = kpi_card_style()
        fallback = colors.get("accent", "#10B981")
    else:
        value_size = FONT_SIZE_LARGE
        label_size = FONT_SIZE_SMALL
        label_weight = ft.FontWeight.W_500
        style = {"spacing": 4, "padding": PADDING_LG, "border_radius": RADIUS_LG}
        fallback = colors.get("text_primary", colors.get("accent", "#10B981"))

    color = colors["kpis"].get(color_key, fallback)

    return ft.Container(
        content=ft.Column([
            ft.Text(value, size=value_size, weight=ft.FontWeight.W_700, color=color,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(
                label.upper() if size == "large" else label,
                size=label_size,
                weight=label_weight,
                color=colors["text_muted"],
            ),
        ], spacing=style["spacing"]),
        padding=style["padding"],
        bgcolor=colors["surface"],
        border_radius=style["border_radius"],
        border=ft.BorderSide(1, colors["border"]),
        expand=True,
    )


def empty_state(colors: dict, message: str = "Carga datos para ver esta vista") -> ft.Container:
    """Common empty-state placeholder."""
    return ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.INBOX_OUTLINED, size=48, color=colors["text_muted"], opacity=0.5),
            ft.Text(message, size=12, color=colors["text_muted"]),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
        padding=ft.Padding(40, 32, 40, 32),
    )


def _fmt_num(val) -> str:
    try:
        return f"{float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct(val) -> str:
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return str(val)


def format_cell_value(val, fmt: str | None = None) -> str:
    """Format a cell value for display in the tabular report."""
    if val is None or (isinstance(val, float) and val != val):
        return ""
    if fmt == "num":
        return _fmt_num(val)
    if fmt == "pct":
        return _fmt_pct(val)
    txt = str(val)
    return txt[:MAX_TABLE_CELL_LENGTH]


def _resolve_color(colors: dict, ref: str) -> str:
    """Return a theme color by key, or pass through a raw hex/name."""
    if ref in colors:
        return colors[ref]
    return ref


def build_tabular_report(
    colors: dict,
    df,
    columns: list[tuple[str, str, str | None]],
    key: str = "",
    sort_states: dict[str, tuple[str | None, bool]] | None = None,
    on_toggle_sort: callable | None = None,
    sort_col: str | None = None,
    sort_desc: bool = False,
    on_row_click: callable | None = None,
    drillable_cols: set[str] | None = None,
    color_overrides: dict[str, str] | None = None,
    page_limit: int = TABLE_PAGE_SIZE,
    show_totals: bool = True,
) -> ft.Container:
    """Build a tabular report: sortable headers, zebra rows, totals row.

    No ft.DataTable: each row is a plain text row that is easy to read and copy.

    Args:
        colors: Theme color dict.
        df: DataFrame to display.
        columns: List of (col_key, label, fmt) tuples.
        key: Lookup key for sort_states.
        sort_states: Mutable dict {key: (sort_col, sort_desc)}.
        on_toggle_sort: Optional callback(key, col) on header click.
        sort_col / sort_desc: Sort to apply before render (wins over sort_states).
        on_row_click: Optional callback(row_dict) for row clicks.
        drillable_cols: Column keys rendered as accent links.
        color_overrides: {col_key: theme color key or hex} for emphasis.
        page_limit: Max rows to render.
        show_totals: Sums all "num" columns into a totals row.
    """
    if df is None or df.empty:
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.SEARCH_OFF, size=40, color=colors["text_muted"], opacity=0.5),
                ft.Text("Sin datos para mostrar", size=FONT_SIZE_SMALL, color=colors["text_muted"]),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=SPACING_SM),
            padding=PADDING_XL,
            alignment=ft.alignment.center,
            expand=True,
        )

    drillable = drillable_cols or set()
    overrides = color_overrides or {}

    display_df = df.copy()
    if sort_col is None and sort_states is not None:
        sort_col, sort_desc = sort_states.get(key, (None, False))
    if sort_col and sort_col in display_df.columns:
        try:
            display_df = display_df.sort_values(sort_col, ascending=not sort_desc,
                                                na_position="last").reset_index(drop=True)
        except Exception:
            pass

    def _fmt_for(fmt: str | None) -> tuple[bool, str, ft.alignment]:
        _num = fmt == "num"
        align = ft.alignment.center_right if _num else ft.alignment.center_left
        text_align = ft.TextAlign.RIGHT if _num else ft.TextAlign.LEFT
        return _num, text_align, align

    # --- Header row ---
    header_cells = []
    for col_key, label, fmt in columns:
        is_sorted = on_toggle_sort is not None and sort_col == col_key
        arrow = (" ↓" if sort_desc else " ↑") if is_sorted else ""
        _num, text_align, align = _fmt_for(fmt)
        cell = ft.Container(
            content=ft.Text(
                label + arrow,
                size=FONT_SIZE_SMALL,
                weight=ft.FontWeight.W_700,
                color=colors["accent"] if is_sorted else colors["text_secondary"],
                text_align=text_align,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            expand=True,
            padding=ft.Padding(8, 4, 8, 4),
            alignment=align,
        )
        if on_toggle_sort is not None:
            cell.on_click = lambda _, c=col_key, k=key: on_toggle_sort(k, c)
            cell.tooltip = f"Ordenar por {label}"
        header_cells.append(cell)

    header_row = ft.Container(
        content=ft.Row(header_cells, spacing=0, tight=True),
        bgcolor=colors["surface_sunken"],
        border=ft.BorderSide(1, colors["border"]),
        padding=ft.Padding(0, 2, 0, 2),
    )

    # --- Zebra rows ---
    row_containers = []
    for i, (_, r) in enumerate(display_df.head(page_limit).iterrows()):
        cells = []
        for col_key, _, fmt in columns:
            val = r.get(col_key, "") if col_key in display_df.columns else ""
            txt = format_cell_value(val, fmt)
            _num, text_align, align = _fmt_for(fmt)
            color = colors["text_primary"]
            weight = ft.FontWeight.W_400
            if col_key in overrides:
                color = _resolve_color(colors, overrides[col_key])
                weight = ft.FontWeight.W_700
            elif col_key in drillable:
                color = colors["accent"]
                weight = ft.FontWeight.W_700
            cells.append(ft.Container(
                content=ft.Text(txt, size=FONT_SIZE_SMALL, color=color, weight=weight,
                                text_align=text_align, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                expand=True,
                padding=ft.Padding(8, 3, 8, 3),
                alignment=align,
            ))
        row = ft.Container(
            content=ft.Row(cells, spacing=0, tight=True),
            bgcolor=colors["surface_variant"] if i % 2 else colors["surface"],
        )
        if on_row_click is not None:
            row_vals = {col_key: r.get(col_key, "") for col_key, _, _ in columns}
            row.on_click = lambda _, rv=row_vals: on_row_click(rv)
            row.tooltip = "Ver detalle"
        row_containers.append(row)

    # --- Totals row ---
    totals_row = None
    if show_totals:
        totals_cells = []
        for j, (col_key, _, fmt) in enumerate(columns):
            _num, text_align, align = _fmt_for(fmt)
            if _num and col_key in display_df.columns:
                vals = pd.to_numeric(df[col_key], errors="coerce")
                txt = _fmt_num(vals.dropna().sum())
            else:
                txt = "TOTAL" if j == 0 else ""
            totals_cells.append(ft.Container(
                content=ft.Text(txt, size=FONT_SIZE_SMALL, color=colors["accent"],
                                weight=ft.FontWeight.W_700, text_align=text_align,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                expand=True,
                padding=ft.Padding(8, 4, 8, 4),
                alignment=align,
            ))
        totals_row = ft.Container(
            content=ft.Row(totals_cells, spacing=0, tight=True),
            bgcolor=rgba(colors["accent"], 0.08),
            border=ft.BorderSide(1, rgba(colors["accent"], 0.35)),
        )

    # --- Footer ---
    total = len(df)
    showing = min(total, page_limit)
    footer = ft.Row([
        ft.Text(f"Mostrando {showing:,} de {total:,} registros",
                size=FONT_SIZE_TINY, color=colors["text_muted"]),
        ft.Container(expand=True),
        ft.Text(f"Limite: {page_limit:,}" if total > page_limit else "",
                size=FONT_SIZE_TINY, color=colors["text_muted"], opacity=0.7),
    ], spacing=SPACING_SM)
    footer_wrap = ft.Container(content=footer, padding=ft.Padding(8, 3, 8, 3))

    children = [header_row, *row_containers]
    if totals_row is not None:
        children.append(totals_row)
    children.append(footer_wrap)

    return ft.Container(
        content=ft.Column(children, spacing=0, scroll=ft.ScrollMode.AUTO, tight=True),
        bgcolor=colors["surface"],
        border_radius=RADIUS_MD,
        border=ft.BorderSide(1, colors["border"]),
        expand=True,
    )


def build_sortable_table(
    colors: dict,
    df,
    columns: list[tuple[str, str, str | None]],
    key: str,
    sort_states: dict[str, tuple[str | None, bool]],
    on_toggle_sort: callable,
    on_row_click: callable | None = None,
    page_limit: int = TABLE_PAGE_SIZE,
) -> ft.Container:
    """Sortable tabular report (delegates to build_tabular_report)."""
    sort_states = sort_states or {}
    s_col, s_desc = sort_states.get(key, (None, False))
    return build_tabular_report(
        colors, df, columns,
        key=key, sort_states=sort_states, on_toggle_sort=on_toggle_sort,
        sort_col=s_col, sort_desc=s_desc, on_row_click=on_row_click,
        page_limit=page_limit,
    )


def build_simple_table(
    colors: dict,
    df,
    columns: list[str],
    headers: list[str],
    page_limit: int = 50,
) -> ft.Container:
    """Simple non-sortable tabular report (delegates to build_tabular_report)."""
    if df.empty:
        return ft.Container()
    cols = [
        (c, h, "num" if c in ("saldo", "cajas", "pedido", "desp", "valor") else None)
        for c, h in zip(columns, headers)
    ]
    return build_tabular_report(colors, df, cols, page_limit=page_limit, show_totals=False)


def build_master_table(
    colors: dict,
    df,
    columns: list[tuple[str, str, str | None]],
    filter_values: dict[str, str],
    sort_col: str | None,
    sort_desc: bool,
    on_filter_change: callable,
    on_sort_change: callable,
    on_clear_filters: callable,
    on_row_click: callable | None = None,
    drillable_cols: set[str] | None = None,
    page_limit: int = TABLE_PAGE_SIZE,
) -> ft.Container:
    """Master tabular report (delegates to build_tabular_report).

    Keeps sorting + row clicks; per-column filter inputs are intentionally
    dropped in favor of the simpler report layout.
    """
    return build_tabular_report(
        colors, df, columns,
        sort_col=sort_col, sort_desc=sort_desc,
        on_toggle_sort=lambda _k, c: on_sort_change(c),
        on_row_click=on_row_click, drillable_cols=drillable_cols,
        page_limit=page_limit,
    )
