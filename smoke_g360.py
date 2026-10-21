"""Smoke test: build + navegacion completa con fake page de Flet."""
import asyncio
import traceback

import flet as ft
import pandas as pd

from src.app import PedidoVigenciasApp


class P:
    def __init__(self):
        self.overlay = []
        self.controls = []
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.theme_mode = ft.ThemeMode.LIGHT
        self.window_width = 0
        self.window_height = 0
        self.window_min_width = 0
        self.window_min_height = 0
        self.on_close = None

    def window_center(self): pass

    def update(self, *a): pass

    def open(self, *a): pass

    def add(self, *cs):
        for c in cs:
            self._attach(c)

    def _attach(self, control):
        object.__setattr__(control, "_Control__page", self)
        ch = []
        content = getattr(control, "content", None)
        if content is not None:
            ch.append(content)
        controls = getattr(control, "controls", None) or []
        if isinstance(controls, (list, tuple)):
            ch.extend(controls)
        elif controls is not None:
            ch.append(controls)
        for c in ch:
            if isinstance(c, ft.Control):
                self._attach(c)

    def run_task(self, handler, *args):
        asyncio.run(handler(self, *args))


def click(ctrl):
    h = getattr(ctrl, "on_click", None)
    if h:
        h(type("E", (), {"control": ctrl, "data": ""})())


n = 300
df = pd.DataFrame({
    "COD_CLIENTE": [f"C{i%50:03d}" for i in range(n)],
    "NOM_CLIENTE": [f"Cli {i%50}" for i in range(n)],
    "NOM_VENDEDOR": ["V1"] * n,
    "ID_VENDEDOR": ["1"] * n,
    "SKU": [f"S{i%30:03d}" for i in range(n)],
    "NOM_ARTICULO": ["Prod"] * n,
    "NOM_ALMACEN": ["VES"] * n,
    "ID_PEDIDO": [f"P{i}" for i in range(n)],
    "CAN_PEDIDO": [10] * n,
    "CAN_DESPACHO": [5] * n,
    "saldo": [5] * n,
    "cajas": [1] * n,
    "valor_saldo": [50.0] * n,
    "categoria": [f"CAT{i%4}" for i in range(n)],
    "estado_linea": ["NUEVO" if i % 2 else "TRAD" for i in range(n)],
    "_fuente": ["a.csv"] * n,
})

try:
    app = PedidoVigenciasApp(P())
    print("BUILD_OK")
    app._df = df
    app._on_processed(df)
    print("DATA_OK")

    for nid, ctrl in app.dashboard._nav_items.items():
        click(ctrl)
        print("NAV_OK", nid)

    app.open_cliente_detail("C001", "Cli 1")
    print("DETAIL_OK")
    app._router.back()
    print("BACK_OK")
    click(app.dashboard._back_btn)
    print("BACKBTN_OK")
    app._toggle_theme()
    app._toggle_theme()
    print("THEME_OK")
    print("ALL_OK")
except Exception:
    traceback.print_exc()
