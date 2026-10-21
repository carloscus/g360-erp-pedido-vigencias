"""Validacion critica: 01240 no se confunde con 001240 ni con 1240."""

from __future__ import annotations

import json

import pandas as pd

from src.core.ingest import Ingester


def _make_catalogo(tmp_path):
    productos = [
        {"sku": "01240", "categoria": "VINIBALL", "un_bx": 60},
        {"sku": "001240", "categoria": "REPRESENTADAS", "un_bx": 12},
        {"sku": "1240", "categoria": "OTRA", "un_bx": 3},
    ]
    path = tmp_path / "cat.json"
    path.write_text(json.dumps({"productos": productos}), encoding="utf-8")
    return str(path)


def test_01240_no_se_confunde_con_001240(tmp_path):
    """Cada SKU se resuelve con su propia entrada del catalogo."""
    ing = Ingester(catalog_path=_make_catalogo(tmp_path))
    df = pd.DataFrame({"ID_ARTICULO": ["01240", "001240", "1240"]})
    out = ing.enrich_with_catalog(df)
    assert out.loc[0, "categoria"] == "VINIBALL"
    assert out.loc[1, "categoria"] == "REPRESENTADAS"
    assert out.loc[2, "categoria"] == "OTRA"


def test_preserva_longitud_tras_lectura(tmp_path):
    """Al leer un archivo real, el SKU no cambia de longitud ni pierde ceros."""
    df_in = pd.DataFrame({"ID_ARTICULO": ["01240", "001240", "1240", "011019"]})
    path = tmp_path / "sku.xlsx"
    df_in.to_excel(path, index=False, engine="openpyxl")
    ing = Ingester()
    df = ing.load_file(str(path))
    assert list(df["ID_ARTICULO"]) == ["01240", "001240", "1240", "011019"]
    assert all(len(s) in (5, 6) or s == "1240" for s in df["ID_ARTICULO"])
