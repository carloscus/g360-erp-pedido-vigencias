"""Pruebas del motor de analisis: KPIs, segmentacion y query natural."""

from __future__ import annotations

import pandas as pd

from src.core.analytics import PedidosAnalytics, summarize_df


def _build_df() -> pd.DataFrame:
    """DataFrame enriquecido de prueba (ya con campos derivados)."""
    return pd.DataFrame({
        "ID_ARTICULO": ["02187", "02187", "01240", "011019", "02187"],
        "NOM_ARTICULO": ["FORRO N VINIFORRITO CRISTAL 20-25"] * 3
                       + ["N SEMIDEPORTIVA FUTBOL CRACKCITO"] + ["FORRO N VINIFORRITO CRISTAL 20-25"],
        "categoria": ["VINIFAN", "VINIFAN", "VINIBALL", "REPRESENTADAS", "VINIFAN"],
        "estado_linea": ["TRADICIONAL", "NUEVO", "NACIONAL", "IMPORTADO", "TRADICIONAL"],
        "COD_CLIENTE": ["2241", "2241", "10214", "10214", "2241"],
        "NOM_CLIENTE": ["CLIENTE A", "CLIENTE A", "CLIENTE B", "CLIENTE B", "CLIENTE A"],
        "ID_VENDEDOR": ["177", "177", "177", "178", "177"],
        "NOM_VENDEDOR": ["VENDEDOR 1", "VENDEDOR 1", "VENDEDOR 1", "VENDEDOR 2", "VENDEDOR 1"],
        "NOM_ALMACEN": ["CENTRO LOGISTICO VES", "CENTRO LOGISTICO VES", "VES", "CIPTECH", "VES"],
        "CONDICION_PAGO": ["CONTADO", "FACTURA 60 DIAS", "CONTADO", "CONTADO", "CONTADO"],
        "CAN_PEDIDO": [100, 200, 384, 540, 300],
        "CAN_DESPACHO": [0, 50, 0, 540, 100],
        "PRE_ARTICULO": [178, 400, 7680, 5400, 534],
        "saldo": [100, 150, 384, 0, 200],
        "por_atendido": [0, 25, 0, 100, 33.33],
        "cajas": [1, 1.5, 8, 0, 2],
        "valor_saldo": [178, 300, 7680, 0, 356],
        "un_bx": [100, 100, 48, 48, 100],
    })


def test_get_kpis():
    an = PedidosAnalytics(_build_df())
    k = an.get_kpis()
    assert k["total_items"] == 5
    assert k["total_pedido"] == 1524
    assert k["total_despachado"] == 690
    assert k["saldo_total"] == 834
    assert k["cajas_total"] == 12.5
    assert k["valor_total"] == 8514
    assert k["n_clientes"] == 2
    assert k["n_vendedores"] == 2
    assert k["n_almacenes"] == 3


def test_get_by_category():
    an = PedidosAnalytics(_build_df())
    out = an.get_by_category()
    assert out.shape[0] == 3
    vinifan = out[out["categoria"] == "VINIFAN"].iloc[0]
    assert vinifan["items"] == 3
    assert vinifan["saldo"] == 450


def test_get_by_estado_linea():
    an = PedidosAnalytics(_build_df())
    out = an.get_by_estado_linea("VINIFAN")
    estados = set(out["estado_linea"])
    assert "NUEVO" in estados and "TRADICIONAL" in estados
    nuevo = out[out["estado_linea"] == "NUEVO"].iloc[0]
    assert nuevo["saldo"] == 150


def test_get_qc_alerts():
    an = PedidosAnalytics(_build_df())
    alerts = an.get_qc_alerts(threshold=100)
    # saldo > 100 en almacen VES
    assert not alerts.empty
    assert alerts.iloc[0]["saldo"] >= 150


def test_get_vinifan_client_summary():
    an = PedidosAnalytics(_build_df())
    res = an.get_vinifan_client_summary(2241)
    assert res["units_saldo"] == 450
    assert res["cajas"] == 4.5
    assert res["estado_linea_breakdown"]["NUEVO"] == 300


def test_get_sku_box_query():
    an = PedidosAnalytics(_build_df())
    res = an.get_sku_box_query("02187")
    assert res["units_pendientes"] == 450
    assert res["cajas"] == 4.5


def test_query_natural_categoria():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("VINIFAN")
    assert len(df) == 3
    assert "categoria=VINIFAN" in expl


def test_query_natural_vinifan_cliente():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("VINIFAN cliente 2241")
    assert len(df) == 3
    assert "cliente=2241" in expl


def test_query_natural_sku():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("cajas de 02187")
    assert len(df) == 3
    assert "SKU=02187" in expl


def test_query_natural_condicion():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("contado")
    assert len(df) == 4
    assert "condicion=CONTADO" in expl


def test_query_natural_sin_match():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("xyz abcdef")
    assert df.empty
    assert "Sin resultados" in expl



def test_query_operational_order_oc_and_status():
    df = _build_df().copy()
    df["ID_PEDIDO"] = ["CC000050"] * len(df)
    df["PEDIDO_ORD_COMPRA"] = ["OC-7788"] * len(df)
    df["PEDIDO_ESTADO"] = ["APROBADO"] * len(df)
    df["NOM_ESTADO_PLANILLA_ANTICIPO"] = ["INGRESADO"] * len(df)
    an = PedidosAnalytics(df)
    result, explanation = an.query_natural("oc OC-7788 estado aprobado")
    assert len(result) == len(df)
    assert "OC~'oc-7788'" in explanation or "OC~'oc-7788'".lower() in explanation.lower()


def test_query_natural_sku_condicion_combinado():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("02187 contado")
    assert len(df) == 2
    assert "SKU=02187" in expl and "condicion=CONTADO" in expl


def test_query_natural_vendedor_id_suelto():
    an = PedidosAnalytics(_build_df())
    df, expl = an.query_natural("178 contado")
    assert len(df) == 1
    assert "vendedor=178" in expl and "condicion=CONTADO" in expl


def test_query_natural_anticipo_sin_letras():
    df = pd.DataFrame({
        "ID_PEDIDO": ["P1", "P2", "P3"],
        "ID_ARTICULO": ["A1", "A1", "A2"],
        "NOM_ARTICULO": ["PROD X"] * 3,
        "CONDICION_PAGO": ["ANTICIPO EN LETRAS", "CONTADO", "LETRA"],
        "CAN_PEDIDO": [10, 10, 5],
        "CAN_DESPACHO": [2, 10, 0],
        "saldo": [8, 0, 5],
        "cajas": [1, 1, 1],
        "valor_saldo": [80.0, 0.0, 50.0],
    })
    an = PedidosAnalytics(df)
    out, expl = an.query_natural("anticipo")
    assert "condicion=ANTICIPO" in expl
    assert len(out) == 1 and out.iloc[0]["ID_PEDIDO"] == "P1"
    out2, expl2 = an.query_natural("anticipo en letras")
    assert "condicion=ANTICIPO" in expl2
    assert len(out2) == 1


def test_query_natural_no_aprobadas():
    df = _build_df().copy()
    df["PEDIDO_ESTADO"] = ["INGRESADO", "APROBADO", "APROBADO", "INGRESADO", "APROBADO"]
    an = PedidosAnalytics(df)
    out, expl = an.query_natural("no aprobadas")
    assert "estado!=APROBADO" in expl
    assert list(out["PEDIDO_ESTADO"]) == ["INGRESADO", "INGRESADO"]


def test_summarize_df_cobertura():
    df = _build_df().copy()
    df["stock_api_ves"] = [120, 10, 400, 1, 300]
    s = summarize_df(df)
    assert s["pendientes"] == 4
    assert s["unidades"] == 834
    assert s["valor"] == 8514
    assert s["atendibles"] == 3
    assert s["usar_stock"] is True
    assert 70.0 < s["atendibles_pct"] < 80.0
    sin_stock = summarize_df(df.drop(columns=["stock_api_ves"]))
    assert sin_stock["usar_stock"] is False and sin_stock["atendibles"] == 0
