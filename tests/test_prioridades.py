"""Pruebas de la vista Prioridades (src/ui/prioridades_view.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.core.db import PedidosDB
from src.ui.prioridades_view import PrioridadesView

COLORS = {
    "accent": "#008F5D",
    "text_primary": "#1F2937",
    "text_secondary": "#4B5563",
    "text_muted": "#9CA3AF",
    "surface": "#FFFFFF",
    "surface_variant": "#F3F4F6",
    "surface_sunken": "#E5E7EB",
    "border": "#E5E7EB",
    "background": "#F9FAFB",
}


@pytest.fixture
def db(tmp_path) -> PedidosDB:
    return PedidosDB(tmp_path / "pedidos.db").ensure_schema()


def _df():
    return pd.DataFrame({
        "ID_PEDIDO": ["FC0001", "FC0001", "FC0002"],
        "COD_CLIENTE": ["C001", "C001", "C002"],
        "NOM_CLIENTE": ["CLIENTE A", "CLIENTE A", "CLIENTE B"],
        "ID_VENDEDOR": ["177", "177", "178"],
        "NOM_VENDEDOR": ["VEND A", "VEND A", "VEND B"],
        "CAN_PEDIDO": [100, 50, 30],
        "CAN_DESPACHO": [40, 50, 0],
        "saldo": [60, 0, 30],
        "valor_saldo": [6000, 0, 3000],
        "dias_desde_pedido": [10, 10, 3],
        "PEDIDO_ESTADO": ["APROBADO", "APROBADO", "INGRESADO"],
    })


def _make_view(db, df=None):
    v = PrioridadesView(COLORS, db=db, on_snack=lambda *_: None)
    if df is not None:
        v.set_data(df)
    return v


def test_build_sin_datos_muestra_empty_state(db):
    v = _make_view(db)
    ctrl = v.build()
    assert ctrl is not None
    col = ctrl.content.content
    textos = [getattr(t, "value", "") for t in col.controls]
    assert "Carga datos" in str(textos)


def test_agregar_por_pedidos_agrega_valor_y_saldo(db):
    v = _make_view(db, _df())
    agg = v._agregar()
    assert len(agg) == 2
    f1 = agg[agg["referencia"] == "FC0001"].iloc[0]
    assert f1["valor"] == 6000.0
    assert f1["saldo"] == 60.0
    assert f1["cliente"] == "C001"
    assert f1["antiguedad"] == 10
    f2 = agg[agg["referencia"] == "FC0002"].iloc[0]
    assert f2["valor"] == 3000.0
    assert f2["saldo"] == 30.0


def test_agregar_por_clientes_agrupa_por_cliente(db):
    v = _make_view(db, _df())
    v._tipo = "clientes"
    agg = v._agregar()
    assert len(agg) == 2
    c1 = agg[agg["referencia"] == "C001"].iloc[0]
    assert c1["pedidos"] == 1
    assert c1["valor"] == 6000.0
    assert c1["saldo"] == 60.0


def test_asignar_prioridad_persiste_y_priorizado_filtra(db):
    df = _df()
    v = _make_view(db, df)
    v._on_prio("pedidos", "FC0001", SimpleNamespace(control=SimpleNamespace(value="1")))
    row = db.get_seguimiento("pedido", "FC0001")
    assert row["prioridad"] == 1

    v._filtro = "priorizados"
    filas = v._filas()
    assert [f["ref"] for f in filas] == ["FC0001"]


def test_anclar_persiste_y_filtro_anclados(db):
    df = _df()
    v = _make_view(db, df)
    v._on_pin("pedidos", "FC0002")
    row = db.get_seguimiento("pedido", "FC0002")
    assert row["anclado"] == 1

    v._filtro = "anclados"
    filas = v._filas()
    assert [f["ref"] for f in filas] == ["FC0002"]


def test_observaciones_y_fecha_se_persisten_sin_perder_prioridad(db):
    df = _df()
    v = _make_view(db, df)
    v._on_prio("pedidos", "FC0001", SimpleNamespace(control=SimpleNamespace(value="2")))
    v._on_obs("pedidos", "FC0001", SimpleNamespace(control=SimpleNamespace(value="esperar liberacion")))
    v._on_fecha("pedidos", "FC0001", SimpleNamespace(control=SimpleNamespace(value="20/09/2026")))
    row = db.get_seguimiento("pedido", "FC0001")
    assert row["prioridad"] == 2
    assert row["observaciones"] == "esperar liberacion"
    assert row["fecha_revision"] == "20/09/2026"


def test_estado_combinado_en_filas(db):
    v = _make_view(db, _df())
    v._on_pin("pedidos", "FC0001")
    filas = v._filas()
    f1 = [f for f in filas if f["ref"] == "FC0001"][0]
    assert f1["anclado"] is True
    f2 = [f for f in filas if f["ref"] == "FC0002"][0]
    assert f2["anclado"] is False