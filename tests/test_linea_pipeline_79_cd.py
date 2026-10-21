"""Test de INTEGRACION: el pipeline completo no mezcla 79 (tijeras) y CD (Crayola).

Mete un pedido con una tijera (linea 79) y un pincel Crayola (linea CD) con el
MISMO nombre de linea ('ACCESORIOS') y confirma que salen en lineas distintas
a traves de la ingesta + allowlist.
"""

import pandas as pd

from src.core.ingest import Ingester


def _df_con_tijera_y_crayola():
    # Forma del export de vigencias del ERP
    base = {
        "ID_PEDIDO": ["P1", "P1"],
        "NRO_DOCUMENTO": ["OC1", "OC1"],
        "ID_VENDEDOR": ["V1", "V1"],
        "NOM_VENDEDOR": ["NV1", "NV1"],
        "COD_CLIENTE": ["C1", "C1"],
        "NOM_CLIENTE": ["NC1", "NC1"],
        "SKU": ["79026", "CD001"],
        "ID_ARTICULO": ["79026", "CD001"],
        "NOM_ARTICULO": ["TIJERA VINIFAN PANDA", "CRAYOLA PINCELES PLANOS"],
        "linea": ["01CD", "01CD"],  # ambas vienen como 01CD del ERP
        "grupo": ["02", "02"],
        "categoria": ["VINIFAN", "VINIFAN"],
        "CAN_PEDIDO": [10, 20],
        "CAN_DESPACHO": [0, 0],
        "PEDIDO_IMPORTE_ARITCULO": [100, 200],
        "PRE_ARTICULO": [10, 10],
        "PEDIDO_FECHA": ["01/01/2026", "01/01/2026"],
        "PEDIDO_ESTADO": ["APROBADO", "APROBADO"],
        "CONDICION_PAGO": ["ANTICIPO EN LETRAS", "ANTICIPO EN LETRAS"],
    }
    return pd.DataFrame(base)


def test_pipeline_separa_tijera_79_de_crayola_cd():
    """Si el catalogo dice 79 para la tijera y CD para el pincel, no se mezclan."""
    ing = Ingester()
    # Catalogo Render: la tijera es 79 y el pincel es CD (mismo nombre).
    ing._render_catalog = {
        "79026": {
            "linea_id": "79",
            "linea": "79",
            "linea_nombre": "ACCESORIOS",
            "grupo": "02",
            "categoria": "VINIFAN",
            "estado_linea": "NUEVO",
        },
        "CD001": {
            "linea_id": "CD",
            "linea": "CD",
            "linea_nombre": "ACCESORIOS",
            "grupo": "02",
            "categoria": "VINIFAN",
            "estado_linea": "NUEVO",
        },
    }
    df = _df_con_tijera_y_crayola()
    out = ing._apply_render_catalog(df, ing._render_catalog)
    out = ing.normalizar_lineas(out)
    por_sku = dict(zip(out["SKU"], out["linea"]))
    assert por_sku["79026"] == "79", f"la tijera debe ser 79: {por_sku}"
    assert por_sku["CD001"] == "CD", f"el pincel Crayola debe ser CD: {por_sku}"


def test_nombre_de_linea_ambiguo_no_pisa_el_codigo():
    """Aunque el nombre sea 'ACCESORIOS' en ambas, el codigo manda."""
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["79026", "CD001"],
            "linea": ["79", "CD"],
            "linea_nombre": ["ACCESORIOS", "ACCESORIOS"],
            "_linea_pre": ["ACCESORIOS", "ACCESORIOS"],
            "_linea_de_render": [True, True],
        }
    )
    out = ing.normalizar_lineas(df)
    assert list(out["linea"]) == ["79", "CD"]
