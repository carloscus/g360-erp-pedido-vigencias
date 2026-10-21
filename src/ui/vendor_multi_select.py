"""
Multi-selector de vendedores con filtros de estado de línea.
"""

from __future__ import annotations

import flet as ft

from src.ui.config import (
    DROPDOWN_WIDTH_NARROW,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    MAX_SHORT_NAME_LENGTH,
    PADDING_SM,
    SPACING_SM,
)


class VendorMultiSelect(ft.Container):
    """Selector multiple de vendedores con badges de estado de línea."""

    STATE_BADGES = [
        ("todos", "Todos", ft.Icons.SELECT_ALL, "accent"),
        ("nuevo", "NUEVO", ft.Icons.NEW_RELEASES, "success"),
        ("tradicional", "TRADICIONAL", ft.Icons.HISTORY, "info"),
        ("importado", "IMPORTADO", ft.Icons.IMPORT_EXPORT, "warning"),
        ("sin_estado", "(Sin Estado)", ft.Icons.HELP_OUTLINE, "text_muted"),
    ]

    def __init__(
        self,
        colors: dict,
        on_change=None,
    ) -> None:
        super().__init__()
        self.c = colors
        self._on_change = on_change
        self._selected_vendors: list[str] = []
        self._selected_state = "todos"
        self._vendor_checks: dict[str, ft.Checkbox] = {}

        # Dropdown principal
        self._dropdown = ft.Dropdown(
            label="Vendedores",
            width=DROPDOWN_WIDTH_NARROW,
            text_size=FONT_SIZE_MEDIUM,
            options=[ft.dropdown.Option("all", "Todos los vendedores")],
            on_change=self._on_dropdown_change,
        )

        # Chips de estado de línea
        self._state_chips = ft.Row([
            ft.Chip(
                ft.Text(label, size=FONT_SIZE_SMALL),
                on_click=lambda _, key=key: self._on_state_click(key),
                bgcolor=self.c.get(color, self.c["accent"]) if key == "todos" else None,
                selected=(key == "todos"),
            )
            for key, label, icon, color in self.STATE_BADGES
        ], spacing=SPACING_SM, wrap=True)

    @property
    def selected_vendors(self) -> list[str]:
        return self._selected_vendors

    @property
    def selected_state(self) -> str:
        return self._selected_state

    def update_vendors(self, df) -> None:
        """Actualiza lista de vendedores desde DataFrame."""
        if df is None or "ID_VENDEDOR" not in df.columns:
            return

        vendors = df.groupby("ID_VENDEDOR").agg(
            nombre=("NOM_VENDEDOR", "first"),
            filas=("ID_PEDIDO", "count"),
        ).reset_index().sort_values("filas", ascending=False)

        self._dropdown.options = [
            ft.dropdown.Option("all", f"Todos ({len(vendors)} vendedores)")
        ]
        for _, row in vendors.iterrows():
            self._dropdown.options.append(
                ft.dropdown.Option(
                    row["ID_VENDEDOR"],
                    f"{row['ID_VENDEDOR']} - {row['nombre'][:MAX_SHORT_NAME_LENGTH]} ({row['filas']})"
                )
            )
        self._dropdown.update()

    def _on_dropdown_change(self, e):
        """Seleccion del dropdown."""
        val = e.control.value
        if val == "all":
            self._selected_vendors = []
        else:
            self._selected_vendors = [val] if val else []
        if self._on_change:
            self._on_change()

    def _on_state_click(self, state: str):
        """Click en badge de estado."""
        self._selected_state = state
        # Actualizar visual de chips
        for chip in self._state_chips.controls:
            chip_text = chip.content.value if hasattr(chip.content, "value") else ""
            is_selected = False
            for key, label, _, _ in self.STATE_BADGES:
                if key == state and chip_text == label:
                    is_selected = True
                    break
            chip.bgcolor = self.c["accent"] if is_selected else None
            chip.selected = is_selected
        self._state_chips.update()
        if self._on_change:
            self._on_change()

    def build(self) -> ft.Container:
        """Construye el layout."""
        return ft.Container(
            content=ft.Column([
                self._dropdown,
                ft.Container(height=SPACING_SM),
                self._state_chips,
            ], spacing=SPACING_SM),
            padding=PADDING_SM,
        )
