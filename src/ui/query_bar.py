"""
Barra de busqueda multi-campo.

Acepta OC / numero de documento, nombre de cliente, SKU, nombre de producto,
condicion de pago o estado de pedido. Al enviar, delega en analytics.query_natural
y muestra el resultado textual junto con la tabla filtrada.
"""

from __future__ import annotations

import logging

import flet as ft

from src.ui.config import (
    FONT_SIZE_3XL,
    FONT_SIZE_LARGE,
    PADDING_LG,
    RADIUS_MD,
    SEARCH_HINT,
    SPACING_LG,
    SPACING_XL,
)

_log = logging.getLogger("g360.pedido_vigencias")


class QueryBar:
    """Barra de busqueda prominente con placeholder dinamico."""

    def __init__(self, colors: dict, on_submit) -> None:
        self.c = colors
        self._on_submit = on_submit
        self._text_field = ft.TextField(
            hint_text=SEARCH_HINT,
            prefix_icon=ft.Icons.SEARCH,
            text_size=FONT_SIZE_LARGE,
            color=self.c["text_primary"],
            bgcolor=self.c["surface_variant"],
            border_color=self.c["border"],
            filled=True,
            expand=True,
            on_submit=self._submit,
        )

    # ---------------------------------------------------------------
    def build(self) -> ft.Row:
        """Construye la barra con el campo de texto y el boton de envio."""
        return ft.Row([
            self._text_field,
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ARROW_FORWARD, size=FONT_SIZE_3XL, color=ft.Colors.WHITE),
                ], spacing=SPACING_LG),
                padding=PADDING_LG,
                bgcolor=self.c["accent_dark"],
                border_radius=RADIUS_MD,
                on_click=self._submit_click,
            ),
        ], spacing=SPACING_XL)

    def set_placeholder(self, text: str) -> None:
        """Actualiza el placeholder de forma dinamica."""
        _log.info("[QueryBar] set_placeholder: %s", text)
        self._text_field.hint_text = text
        self._text_field.update()

    def clear(self) -> None:
        """Limpia el texto de busqueda."""
        _log.info("[QueryBar] clear")
        self._text_field.value = ""
        self._text_field.update()

    def get_value(self) -> str:
        return (self._text_field.value or "").strip()

    # ---------------------------------------------------------------
    def _submit(self, e) -> None:
        _log.info("[QueryBar] _submit: value=%s", self.get_value())
        self._fire()

    def _submit_click(self, _) -> None:
        _log.info("[QueryBar] _submit_click: value=%s", self.get_value())
        self._fire()

    def _fire(self) -> None:
        value = self.get_value()
        _log.info("[QueryBar] _fire: value=%r", value)
        if self._on_submit:
            self._on_submit(value)
