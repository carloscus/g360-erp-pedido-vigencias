"""Pruebas de ingesta: dtype=str, matching SKU directo y enrichment con catalogo."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.core.ingest import Ingester, _detect_engine


@pytest.fixture
def mini_catalogo(tmp_path):
    """Catalogo maestro de prueba con SKUs de 5 y 6 digitos."""
    productos = [
        {
            "sku": "01240",
            "nombre": "N SEMIDEPORTIVA FUTBOL CRACKCITO BL/AZL",
            "categoria": "VINIBALL",
            "estado_linea": "NACIONAL",
            "un_bx": 60,
        },
        {
            "sku": "011019",
            "nombre": "BOLSA BASURA VINIFAN",
            "categoria": "VINIFAN",
            "estado_linea": "TRADICIONAL",
            "un_bx": 100,
        },
        {
            "sku": "001240",
            "nombre": "OTRO SKU PARECIDO",
            "categoria": "REPRESENTADAS",
            "estado_linea": "IMPORTADO",
            "un_bx": 12,
        },
    ]
    path = tmp_path / "catalogo.json"
    path.write_text(json.dumps({"productos": productos}), encoding="utf-8")
    return str(path)


def test_detect_engine_xls():
    """Un archivo .xls usa el motor xlrd."""
    assert _detect_engine("reporte.xls") == "xlrd"


def test_detect_engine_xlsx():
    """Un archivo .xlsx usa el motor openpyxl."""
    assert _detect_engine("reporte.XLSX") == "openpyxl"


def test_detect_engine_invalido():
    """Un formato no soportado lanza ValueError."""
    with pytest.raises(ValueError):
        _detect_engine("reporte.csv")


def test_load_file_preserva_ceros(tmp_path):
    """Al leer con dtype=str, el SKU 01240 no se convierte a 1240."""
    df_in = pd.DataFrame({"ID_ARTICULO": ["01240", "011019", "1240"]})
    path = tmp_path / "test.xlsx"
    df_in.to_excel(path, index=False, engine="openpyxl")
    ing = Ingester()
    df = ing.load_file(str(path))
    assert list(df["ID_ARTICULO"]) == ["01240", "011019", "1240"]


def test_load_multiple_marca_fuente(tmp_path):
    """Cada fila queda marcada con el nombre del archivo de origen."""
    p1 = tmp_path / "a.xlsx"
    p2 = tmp_path / "b.xlsx"
    pd.DataFrame({"ID_ARTICULO": ["01240"]}).to_excel(p1, index=False, engine="openpyxl")
    pd.DataFrame({"ID_ARTICULO": ["011019"]}).to_excel(p2, index=False, engine="openpyxl")
    ing = Ingester()
    df = ing.load_multiple([str(p1), str(p2)])
    assert len(df) == 2
    assert "_fuente" in df.columns
    assert sorted(df["_fuente"].unique()) == ["a.xlsx", "b.xlsx"]


def test_enrich_with_catalog_matching_directo(mini_catalogo):
    """El SKU se busca tal cual en el catalogo: 01240 != 001240 != 1240."""
    df = pd.DataFrame({"ID_ARTICULO": ["01240", "001240", "011019", "99999"]})
    ing = Ingester(catalog_path=mini_catalogo)
    out = ing.enrich_with_catalog(df)
    assert out.loc[0, "categoria"] == "VINIBALL"
    assert out.loc[1, "categoria"] == "REPRESENTADAS"
    assert out.loc[2, "categoria"] == "VINIFAN"
    assert out.loc[2, "un_bx"] == 100
    # SKU sin catalogo: categoria vacia y un_bx=1
    assert out.loc[3, "categoria"] == ""
    assert out.loc[3, "un_bx"] == 1


def test_compute_derived_formulas():
    """Saldo, porcentajes, cajas y valor del saldo se calculan bien."""
    df = pd.DataFrame(
        {
            "CAN_PEDIDO": [540, 384, 0],
            "CAN_DESPACHO": [540, 0, 0],
            "PRE_ARTICULO": [5400, 7680, 0],
            "un_bx": [48, 48, 48],
        }
    )
    ing = Ingester()
    out = ing.compute_derived(df)
    assert out.loc[0, "saldo"] == 0
    assert out.loc[0, "por_atendido"] == 100.0
    assert out.loc[1, "saldo"] == 384
    assert out.loc[1, "por_pendiente"] == 100.0
    assert out.loc[1, "cajas"] == 8.0
    assert out.loc[1, "valor_saldo"] == pytest.approx(7680.0, abs=0.01)


def test_detect_unmatched(mini_catalogo):
    """Identifica SKUs sin catalogo."""
    df = pd.DataFrame({"ID_ARTICULO": ["01240", "99999"]})
    ing = Ingester(catalog_path=mini_catalogo)
    out = ing.enrich_with_catalog(df)
    unmatched = ing.detect_unmatched(out)
    assert len(unmatched) == 1
    assert unmatched.iloc[0]["SKU"] == "99999"


def test_stock_api_uses_single_snapshot_request(monkeypatch, tmp_path):
    """El enriquecimiento no debe hacer una petición por SKU."""
    import src.core.ingest as ingest_module

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "items": [
                    {
                        "sku": "01240",
                        "almacenes": [
                            {"almacen": "VES", "disponible": 25},
                        ],
                    }
                ]
            }

    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(ingest_module.requests, "get", fake_get)
    monkeypatch.setattr(ingest_module, "DATA_DIR", tmp_path)
    df = pd.DataFrame({"SKU": ["01240", "011019", "01240"]})
    out = Ingester().enrich_with_stock_api(df)
    assert len(calls) == 1
    assert calls[0][1]["params"] == {"fuente": "todas"}
    assert out.loc[0, "stock_api_disponible"] == {"VES": 25}


def test_compute_derived_pedido_fecha_day_first():
    """La fecha dd/mm/yyyy produce dias y rango de antiguedad."""
    df = pd.DataFrame(
        {
            "CAN_PEDIDO": [100, 100, 100],
            "CAN_DESPACHO": [0, 0, 0],
            "PRE_ARTICULO": [1000, 1000, 1000],
            "un_bx": [10, 10, 10],
            "PEDIDO_FECHA": ["08/06/2026", "01/08/2026", "31/08/2026"],
        }
    )
    out = Ingester().compute_derived(df, fecha_corte=pd.to_datetime("15/08/2026", dayfirst=True))
    assert out["dias_desde_pedido"].tolist() == [68, 14, 0]
    assert out["antiguedad_pedido"].tolist() == [">60 dias", "8-15 dias", "FUTURA"]


def test_compute_derived_prefers_order_line_amount():
    """El valor de saldo usa el importe original, no PRE_ARTICULO duplicado."""
    df = pd.DataFrame(
        {
            "CAN_PEDIDO": [100],
            "CAN_DESPACHO": [40],
            "PRE_ARTICULO": [600],
            "PEDIDO_IMPORTE_ARITCULO": [1000],
            "un_bx": [10],
        }
    )
    out = Ingester().compute_derived(df)
    assert out.loc[0, "valor_pedido"] == 1000
    assert out.loc[0, "valor_saldo"] == 600


class _FakeCatalogo:
    """Catalogo unico falso para tests (misma interfaz que CatalogoUnico)."""

    unavailable = False
    error_msg = ""

    def __init__(self, articulos=None, disponible=True):
        self._articulos = articulos or {}
        self._disponible = disponible

    def cargar(self, forzar=False):
        return self._disponible

    def articulo(self, sku):
        if not sku:
            return None
        return self._articulos.get(str(sku).strip())

    @property
    def allowlist(self):
        return ["01", "78"]


def test_enrich_with_db_lines_rellena_vacios():
    """El catalogo unico completa la taxonomia donde el catalogo local no la tiene."""
    ing = Ingester()
    ing._catalogo_unico = _FakeCatalogo(
        {
            "01240": {
                "linea": "0101",
                "linea_nombre": "PELOTAS",
                "grupo": "01",
                "grupo_nombre": "NACIONAL",
                "familia": "01",
                "familia_nombre": "FUTBOL",
                "nombre": "X",
            },
            "99999": {
                "linea": "0178",
                "linea_nombre": "INDUMENTARIA",
                "grupo": "02",
                "grupo_nombre": "OTRO",
                "familia": "02",
                "familia_nombre": "Y",
                "nombre": "Y",
            },
        }
    )
    df = pd.DataFrame(
        {
            "SKU": ["01240", "99999"],
            "linea": ["EXISTENTE", ""],
            "grupo": ["", "GRUPO_VAL"],
            "nom_linea": [None, None],
            "nom_grupo": [None, None],
        }
    )
    out = ing.enrich_with_db_lines(df)
    # '01240' ya tenia linea -> se conserva; grupo se rellena
    assert out.loc[0, "linea"] == "EXISTENTE"
    assert out.loc[0, "grupo"] == "01"
    # '99999' tenia linea vacia -> el maestro la rellena; grupo se conserva
    assert out.loc[1, "linea"] == "0178"
    assert out.loc[1, "grupo"] == "GRUPO_VAL"
    assert out.loc[1, "nom_linea"] == "INDUMENTARIA"
    # la familia del maestro es una dimension nueva
    assert out.loc[1, "familia"] == "02"
    assert out.loc[1, "nom_familia"] == "Y"


def test_enrich_with_db_lines_offline_devuelve_sin_cambios(monkeypatch):
    """Si el catalogo unico no esta, el DataFrame no se modifica (degradacion)."""
    import src.core.ingest as ing_mod

    class _Caido(_FakeCatalogo):
        unavailable = True
        error_msg = "catalogo caido"

        def __init__(self):
            super().__init__(disponible=False)

    monkeypatch.setattr(ing_mod, "get_catalogo", lambda *a, **k: _Caido())
    ing = Ingester()
    df = pd.DataFrame({"SKU": ["01240"], "linea": [""]})
    out = ing.enrich_with_db_lines(df)
    # Sin error: sigue funcionando con catalogo local
    assert "SKU" in out.columns
    assert out.loc[0, "SKU"] == "01240"
    assert ing.db_unavailable is True


def test_flag_relevante_bloqueado():
    """es_relevante cruza categoria + stock API >0 + saldo>0."""
    df = pd.DataFrame(
        {
            "CAN_PEDIDO": [100, 100, 100, 100],
            "CAN_DESPACHO": [40, 40, 100, 40],
            "PRE_ARTICULO": [1000, 1000, 1000, 1000],
            "un_bx": [10, 10, 10, 10],
            "categoria": ["VINIFAN", "VINIFAN", "VINIFAN", ""],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 10},
                {},
                {"CENTRO LOGISTICO VES": 10},
                {"CENTRO LOGISTICO VES": 10},
            ],
        }
    )
    out = Ingester().compute_derived(df)
    # Fila 0: stock API ves 10, saldo 60, categoria ok -> relevante
    assert bool(out.loc[0, "es_relevante"]) is True
    # Fila 1: sin stock API -> bloqueado
    assert bool(out.loc[1, "es_relevante"]) is False
    assert bool(out.loc[1, "es_bloqueado"]) is True
    # Fila 2: saldo 0 -> ni relevante ni bloqueado
    assert bool(out.loc[2, "es_relevante"]) is False
    assert bool(out.loc[2, "es_bloqueado"]) is False
    # Fila 3: sin categoria -> no relevante
    assert bool(out.loc[3, "es_relevante"]) is False
