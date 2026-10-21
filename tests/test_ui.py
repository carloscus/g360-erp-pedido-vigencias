"""Tests de UI: registro y apertura del FilePicker, y rebuild de tema."""

from types import SimpleNamespace

import flet as ft

from src.config.theme import get_colors
from src.core.ingest import Ingester
from src.ui.upload_view import UploadView


class _FakePage:
    """Pagina Flet minima para instanciar vistas sin servidor."""

    def __init__(self):
        self.overlay = []

    def update(self, *args):
        pass

    def add(self, *controls):
        for c in controls:
            self._attach(c)

    def _attach(self, control):
        """Adjunta control y todo su subarbol (como hace Page.update real)."""
        object.__setattr__(control, "_Control__page", self)
        children = []
        content = getattr(control, "content", None)
        if content is not None:
            children.append(content)
        controls = getattr(control, "controls", None) or []
        if isinstance(controls, (list, tuple)):
            children.extend(controls)
        else:
            children.append(controls)
        for ch in children:
            if isinstance(ch, ft.Control):
                self._attach(ch)


def _make_view() -> UploadView:
    return UploadView(
        _FakePage(),
        get_colors("dark"),
        Ingester(),
        on_processed=lambda df: None,
        on_api_state=lambda state: None,
    )


def test_file_picker_registered_in_overlay():
    page = _FakePage()
    uv = UploadView(page, get_colors("dark"), Ingester(), on_processed=lambda df: None)
    assert len(page.overlay) == 1
    assert isinstance(page.overlay[0], ft.FilePicker)
    assert uv._file_picker_ref.current is page.overlay[0]


def test_pick_files_handles_flet_event_arg(monkeypatch):
    """Flet invoca on_click con un argumento de evento: no debe lanzar TypeError."""
    calls = {}

    def fake_pick_files(self, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(ft.FilePicker, "pick_files", fake_pick_files)
    uv = _make_view()
    uv._pick_files_dialog(object())  # evento simulado
    assert calls.get("allow_multiple") is True
    assert "xlsx" in calls.get("allowed_extensions", [])


def test_pick_files_uses_correct_args(monkeypatch):
    calls = {}

    def fake_pick_files(self, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(ft.FilePicker, "pick_files", fake_pick_files)
    uv = _make_view()
    uv._pick_files_dialog()
    assert calls.get("allow_multiple") is True
    assert calls.get("dialog_title") == "Seleccionar archivos de vigencias"
    assert set(calls.get("allowed_extensions", [])) == {"xlsx", "xls"}


def test_on_file_picker_result_adds_files():
    """El resultado del picker agrega archivos y muestra el contenedor de lista."""
    page = _FakePage()
    uv = UploadView(page, get_colors("dark"), Ingester(), on_processed=lambda df: None)
    page.add(uv.build())
    assert uv._file_list_container.visible is False
    uv._on_file_picker_result(SimpleNamespace(files=[SimpleNamespace(path="C:/x/a.xlsx")]))
    assert uv._archivos == ["C:/x/a.xlsx"]
    assert uv._file_list_container.visible is True
    assert len(uv._file_list.controls) == 1


def test_update_theme_rebuilds_preserving_files():
    uv = _make_view()
    uv._archivos = ["C:/x/a.xlsx", "C:/x/b.xls"]
    new_ctrl = uv.update_theme(get_colors("light"))
    assert uv.c == get_colors("light")
    assert uv._archivos == ["C:/x/a.xlsx", "C:/x/b.xls"]
    assert uv._btn_procesar is not None
    assert uv._btn_procesar._enabled is True
    assert new_ctrl is not None


def test_dashboard_data_flow_with_theme_switch():
    """Flujo completo con datos: update_data, status, filtros, y switch de tema."""
    import pandas as pd

    from src.ui.dashboard import Dashboard

    df = pd.DataFrame([
        {"SKU": "01240", "categoria": "VINIFAN", "estado_linea": "ACTIVO", "NOM_ARTICULO": "Art A",
         "NOM_CLIENTE": "Cliente 1", "NOM_VENDEDOR": "V1", "NOM_ALMACEN": "VES",
         "CAN_PEDIDO": 100, "CAN_DESPACHO": 30, "CONDICION_PAGO": "LETRA", "un_bx": 12,
         "PRE_ARTICULO": 5000.0, "stock_api_disponible": 80,
         "saldo": 70, "por_atendido": 30.0, "cajas": 5.8, "valor_saldo": 3500.0, "_fuente": "a.xls"},
        {"SKU": "02187", "categoria": "VINIBALL", "estado_linea": "BLOQUEADO", "NOM_ARTICULO": "Art B",
         "NOM_CLIENTE": "Cliente 2", "NOM_VENDEDOR": "V2", "NOM_ALMACEN": "121",
         "CAN_PEDIDO": 50, "CAN_DESPACHO": 50, "CONDICION_PAGO": "CONTADO", "un_bx": 100,
         "PRE_ARTICULO": 8000.0, "stock_api_disponible": 5,
         "saldo": 0, "por_atendido": 100.0, "cajas": 0.0, "valor_saldo": 0.0, "_fuente": "a.xls"},
    ])

    page = _FakePage()
    d = Dashboard(page, get_colors("dark"), "dark")
    page.add(d.build())
    d.show_analytics()
    d.update_data(df, source_names=["a.xls"], api_state="offline", ts="12:00")
    assert d._status_text.value.startswith("2 registros")

    d.update_theme("light")
    assert d._theme_mode == "light"
    assert d._status_text.value.startswith("2 registros")


def test_palette_keys_parity():
    """Ambos temas deben exponer exactamente las mismas claves de color."""
    from src.config.theme import DARK_COLORS, LIGHT_COLORS

    assert set(DARK_COLORS.keys()) == set(LIGHT_COLORS.keys()), (
        set(DARK_COLORS.keys()) ^ set(LIGHT_COLORS.keys())
    )
    assert set(DARK_COLORS["kpis"].keys()) == set(LIGHT_COLORS["kpis"].keys())


def test_theme_has_required_keys():
    from src.config.theme import get_colors

    required = {
        "background", "sidebar_bg", "border", "surface", "surface_variant",
        "surface_sunken", "text_primary", "text_secondary", "text_muted",
        "accent", "accent_dark", "error", "warning", "success", "info", "kpis",
    }
    for mode in ("dark", "light"):
        missing = required - set(get_colors(mode).keys())
        assert not missing, (mode, missing)


def test_dashboard_update_theme_rebuilds():
    from src.ui.dashboard import Dashboard

    page = _FakePage()
    d = Dashboard(page, get_colors("dark"), "dark")
    root = d.build()
    page.add(root)
    assert root is not None
    d.update_theme("light")
    assert d._theme_mode == "light"
    assert root.bgcolor == get_colors("light")["background"]


def test_filters_panel_set_active_y_callback():
    """El panel del sidebar es navegacion: set_active y click disparan callback."""
    from src.ui.filters import FiltersPanel

    clicks = []
    fp = FiltersPanel(get_colors("dark"), on_view_change=lambda vid: clicks.append(vid))
    fp.build()
    fp.set_active("pedido")
    assert fp.state["view"] == "pedido"
    fp._on_click("cliente")
    assert fp.state["view"] == "cliente"
    assert clicks == ["cliente"]
    fp.reset()  # no-op de compatibilidad
    assert fp.state["view"] == "cliente"


def test_filters_set_options_y_reset_sin_montar_no_lanzan():
    """Operaciones sobre el panel sin pagina adjunta no deben fallar."""
    from src.ui.filters import FiltersPanel

    fp = FiltersPanel(get_colors("dark"), on_view_change=lambda vid: None)
    fp.set_options(categorias=["A"], vendedores=["V1"])  # no-op sin montar
    fp.set_active("dashboard")
    fp.reset()
    assert fp.state["view"] == "dashboard"


def test_apply_filters_con_columnas_faltantes_no_lanza():
    """Filtrar con columnas ausentes degrada sin KeyError."""
    import pandas as pd

    from src.ui.dashboard import Dashboard

    df = pd.DataFrame([
        {"SKU": "01240", "CAN_PEDIDO": 100, "saldo": 70, "cajas": 5.8, "_fuente": "a.xls"},
    ])
    page = _FakePage()
    d = Dashboard(page, get_colors("dark"), "dark")
    page.add(d.build())
    d.show_analytics()
    d._df = df
    # Sin columna es_relevante: conserva el universo completo sin fallar
    d._apply_filters()
    assert len(d._view_df) == 1


def test_apply_filters_excluye_lineas_no_relevantes():
    """_apply_filters conserva solo lineas con es_relevante=True."""
    import pandas as pd

    from src.ui.dashboard import Dashboard

    df = pd.DataFrame([
        {"SKU": "001", "NOM_VENDEDOR": "V1", "COD_CLIENTE": "C1", "NOM_CLIENTE": "Cli 1",
         "es_relevante": True, "saldo": 5,
         "CAN_PEDIDO": 10, "CAN_DESPACHO": 5, "cajas": 1, "valor_saldo": 50.0, "_fuente": "a.xls"},
        {"SKU": "002", "NOM_VENDEDOR": "V2", "COD_CLIENTE": "C2", "NOM_CLIENTE": "Cli 2",
         "es_relevante": False, "saldo": 3,
         "CAN_PEDIDO": 8, "CAN_DESPACHO": 5, "cajas": 1, "valor_saldo": 30.0, "_fuente": "a.xls"},
        {"SKU": "003", "NOM_VENDEDOR": "V1", "COD_CLIENTE": "C1", "NOM_CLIENTE": "Cli 1",
         "es_relevante": True, "saldo": 2,
         "CAN_PEDIDO": 4, "CAN_DESPACHO": 2, "cajas": 1, "valor_saldo": 20.0, "_fuente": "a.xls"},
    ])
    page = _FakePage()
    d = Dashboard(page, get_colors("dark"), "dark")
    page.add(d.build())
    d.show_analytics()
    d.update_data(df, source_names=["a.xls"])

    # Solo las lineas relevantes (V1 x2) quedan en la vista filtrada
    assert len(d._view_df) == 2
    assert set(d._view_df["NOM_VENDEDOR"]) == {"V1"}

    # Sin la columna es_relevante no debe filtrar (universo completo)
    d.update_data(df.drop(columns=["es_relevante"]), source_names=["a.xls"])
    assert len(d._view_df) == 3


def test_nav_sin_datos_vuelve_al_home():
    """Nav con datos vacios muestra el welcome en lugar de fallar en silencio."""
    from src.ui.dashboard import Dashboard

    page = _FakePage()
    d = Dashboard(page, get_colors("dark"), "dark")
    page.add(d.build())
    welcome = ft.Text("home")
    d.show_welcome(welcome)
    assert d._main_col.controls == [welcome]
    d.show_analytics()
    assert d._main_col.controls == d._analytics_controls
    d.show_home()
    assert d._main_col.controls == [welcome]


def test_router_go_back_y_reset():
    """El router apila rutas, permite back y reset limpia el historial."""
    from src.ui.router import Router

    rendered = []
    r = Router(on_change=lambda router: rendered.append(router.current))
    r.register("home", lambda: rendered.append("home"))
    r.register("dashboard", lambda: rendered.append("dashboard"))
    r.register("detalle_cliente", lambda cliente="": rendered.append(f"detalle:{cliente}"))

    assert r.current is None and not r.can_back
    r.go("home")
    assert r.current == "home" and not r.can_back
    r.go("dashboard")
    assert r.can_back
    r.go("detalle_cliente", cliente="C001")
    assert "detalle:C001" in rendered
    r.back()
    assert r.current == "dashboard"
    r.back()
    assert r.current == "home" and not r.can_back
    r.back()  # no debe fallar sin historial
    assert r.current == "home"
    r.reset("dashboard")
    assert r.current == "dashboard" and not r.can_back
    r.go("ruta_inexistente")  # no debe fallar
    assert r.current == "dashboard"


def test_client_detail_view_builds_with_minimal_columns():
    """La vista de detalle de cliente construye con columnas minimas."""
    import pandas as pd

    from src.ui.client_detail import ClientDetailView

    df = pd.DataFrame({
        "COD_CLIENTE": ["C001", "C001"],
        "SKU": ["S1", "S2"],
        "CAN_PEDIDO": [10, 5],
        "CAN_DESPACHO": [4, 5],
        "saldo": [6, 0],
    })
    view = ClientDetailView(df, get_colors("dark"), nombre="Cliente Test")
    control = view.build()
    assert control is not None

    # DataFrame vacio: estado vacio sin fallar
    empty = ClientDetailView(df.iloc[0:0], get_colors("dark"))
    assert empty.build() is not None


def test_client_row_click_opens_detalle():
    """Click en fila de clientes dispara el callback de detalle."""
    import pandas as pd

    from src.ui.dashboard import Dashboard

    page = _FakePage()
    opened = []
    d = Dashboard(page, get_colors("dark"), "dark", on_open_detail=lambda cod, nom: opened.append((cod, nom)))
    page.add(d.build())
    d.show_analytics()
    d._df = pd.DataFrame({
        "COD_CLIENTE": ["C001"],
        "NOM_CLIENTE": ["Cliente Uno"],
        "CAN_PEDIDO": [10],
        "CAN_DESPACHO": [5],
        "saldo": [5],
        "cajas": [1],
        "valor_saldo": [50.0],
    })
    d._tabs_view.update_data(d._df, "offline")
    # Drill limpia inicia en vendedor; para este test usar linea (fallback -> detalle)
    d._tabs_view._dimension = "linea"
    d._tabs_view._on_row_click({"COD_CLIENTE": "C001", "NOM_CLIENTE": "Cliente Uno"})
    assert opened == [("C001", "Cliente Uno")]
