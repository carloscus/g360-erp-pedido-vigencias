"""Funnel prototipo Vigencias: sufijo linea valida + anticipo + aprobado + VES."""

from __future__ import annotations

import pandas as pd

from src.core.analytics import PedidosAnalytics
from src.core.ingest import Ingester, es_linea_valida, linea_sufijo, resolver_codigo_linea


def test_linea_sufijo():
    assert linea_sufijo("0101") == "01"
    assert linea_sufijo("01MA") == "MA"
    assert linea_sufijo(" 01ca ") == "CA"
    assert linea_sufijo("") == ""
    assert linea_sufijo(None) == ""


def test_es_linea_valida_sufijo():
    assert es_linea_valida("0101") is True  # -> 01
    assert es_linea_valida("01MA") is True  # -> MA
    assert es_linea_valida("9999") is True  # sufijo 99 valido
    assert es_linea_valida("98XX", "CB") is True  # fallback grupo
    assert es_linea_valida("98XX", "ZZ") is False
    assert es_linea_valida("") is False


def test_resolver_codigo_linea_formatos():
    assert resolver_codigo_linea("0101") == "01"
    assert resolver_codigo_linea("01MA") == "MA"
    assert resolver_codigo_linea("MA") == "MA"
    assert resolver_codigo_linea("0178 - ARCHIVO") == "78"
    assert resolver_codigo_linea("01 - PELOTAS") == "01"
    assert resolver_codigo_linea("01AD - ACCESORIOS") == "AD"
    assert resolver_codigo_linea("MA - MASCOTAS") == "MA"
    assert resolver_codigo_linea("PELOTAS", {"PELOTAS": "01"}) == "01"
    assert resolver_codigo_linea("PELOTAS") == ""


def test_es_linea_valida_por_nombre():
    name_to_code = {"PELOTAS": "01", "ARCHIVO": "78"}
    assert es_linea_valida("PELOTAS", name_to_code=name_to_code) is True
    assert es_linea_valida("ARCHIVO", name_to_code=name_to_code) is True
    assert es_linea_valida("PELOTAS") is False  # sin mapa: sufijo AS no valido
    assert es_linea_valida("0178 - ARCHIVO") is True  # formato con codigo


def test_funnel_rescata_lineas_por_nombre():
    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["P1", "P2"],
            "SKU": ["S1", "S2"],
            "linea": ["PELOTAS", "LINEA INVENTADA"],
            "grupo": ["", ""],
            "categoria": ["VINIBALL", "X"],
            "CAN_PEDIDO": [100, 30],
            "CAN_DESPACHO": [40, 10],
            "PEDIDO_IMPORTE_ARITCULO": [1000, 300],
            "PRE_ARTICULO": [1000, 300],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS", "ANTICIPO EN LETRAS"],
            "PEDIDO_ESTADO": ["APROBADO", "APROBADO"],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 0},
                {"CENTRO LOGISTICO VES": 0},
            ],
        }
    )
    out = ing.compute_derived(df)
    # PELOTAS resuelve por semilla estatica -> valida; inventada no
    assert bool(out.loc[0, "es_linea_valida"]) is True
    assert bool(out.loc[1, "es_linea_valida"]) is False
    assert out.loc[0, "linea_cod"] == "01"
    assert getattr(ing, "_linea_rescatadas", -1) == 1
    assert getattr(ing, "_linea_rechazadas", -1) == 1


def _df_funnel() -> pd.DataFrame:
    # Pedido P1 mixto: 1 valida + 1 invalida -> se conserva solo la valida
    # Pedido P2: solo invalida -> se descarta
    # Pedido P3: valida pero INGRESADO -> fuera de prototipo
    return pd.DataFrame(
        {
            "ID_PEDIDO": ["P1", "P1", "P2", "P3"],
            "ID_VENDEDOR": ["V1", "V1", "V2", "V1"],
            "COD_CLIENTE": ["C1", "C1", "C2", "C1"],
            "SKU": ["S1", "S2", "S3", "S4"],
            "linea": ["0101", "99ZZ", "99ZZ", "0102"],
            "grupo": ["01", "ZZ", "ZZ", "01"],
            "categoria": ["VINIFAN", "X", "X", "VINIFAN"],
            "CAN_PEDIDO": [100, 50, 30, 80],
            "CAN_DESPACHO": [40, 50, 10, 10],
            "PEDIDO_IMPORTE_ARITCULO": [1000, 500, 300, 800],
            "PRE_ARTICULO": [1000, 500, 300, 800],
            "un_bx": [10, 10, 10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 4,
            "PEDIDO_ESTADO": ["APROBADO", "APROBADO", "APROBADO", "INGRESADO"],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 100},
            ],
        }
    )


def test_funnel_prototipo_fila_sku():
    ing = Ingester()
    df = ing.compute_derived(_df_funnel())
    # sufijo: 0101->01 valida, 99ZZ->ZZ invalida, 0102->02 valida
    assert df.loc[0, "es_linea_valida"] == True
    assert df.loc[1, "es_linea_valida"] == False
    assert df.loc[2, "es_linea_valida"] == False
    # saldo>0 en 0,2,3 (fila 1 saldo 0)
    assert df.loc[0, "saldo"] == 60
    # es_prototipo: valida + anticipo + aprobado + saldo>0
    assert bool(df.loc[0, "es_prototipo"]) is True
    assert bool(df.loc[1, "es_prototipo"]) is False  # invalida + saldo 0
    assert bool(df.loc[2, "es_prototipo"]) is False  # invalida
    assert bool(df.loc[3, "es_prototipo"]) is False  # INGRESADO
    # val_atencion: fila 0 cubre (VES 100 >= saldo 60)
    assert df.loc[0, "val_atencion"] > 0
    assert df.loc[0, "val_pendiente"] == 0

    an = PedidosAnalytics(df)
    validas = an.filtrar_lineas_validas()
    # filas 0 y 3 (validas con saldo>0)
    assert set(validas["SKU"]) == {"S1", "S4"}
    proto = an.filtrar_prototipo()
    assert list(proto["SKU"]) == ["S1"]
    assert list(an.get_val_atencion()["SKU"]) == ["S1"]
    assert an.get_val_pendiente().empty


def test_val_pendiente_sin_stock():
    ing = Ingester()
    df = _df_funnel().iloc[[0]].copy()
    df["stock_api_disponible"] = [{"CENTRO LOGISTICO VES": 10}]
    out = ing.compute_derived(df)
    assert out.loc[0, "val_atencion"] == 0
    assert out.loc[0, "val_pendiente"] > 0


def test_render_catalog_es_verdad_y_recalcula_prototipo(monkeypatch, tmp_path):
    """Render aporta categoria/linea/un_bx + stock y dispara val_atencion."""
    import src.core.ingest as ingest_module

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "items": [
                    {
                        "sku": "S1",
                        "linea": "01 - PELOTAS",
                        "linea_id": "01",
                        "grupo": "01 - NACIONAL",
                        "categoria": "viniball",
                        "estado_linea": "nacional",
                        "un_bx": 60,
                        "nombre_corto": "PELOTA X",
                        "almacenes": [{"almacen": "VES", "disponible": 100}],
                    }
                ]
            }

    def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr(ingest_module.requests, "get", fake_get)
    monkeypatch.setattr(ingest_module, "DATA_DIR", tmp_path)
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["S1"],
            "linea": [""],
            "grupo": [""],
            "categoria": [""],
            "CAN_PEDIDO": [100],
            "CAN_DESPACHO": [40],
            "PEDIDO_IMPORTE_ARITCULO": [1000],
            "un_bx": [1],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"],
            "PEDIDO_ESTADO": ["APROBADO"],
        }
    )
    out = ing.enrich_with_stock_api(df)
    assert out.loc[0, "categoria"] == "VINIBALL"
    assert out.loc[0, "linea"] == "01"
    assert out.loc[0, "un_bx"] == 60
    assert out.loc[0, "stock_real"] == 100
    assert bool(out.loc[0, "es_linea_valida"]) is True
    assert bool(out.loc[0, "es_prototipo"]) is True
    assert out.loc[0, "val_atencion"] > 0


def test_verify_clientes_vendedores_flag():
    ing = Ingester()
    df = pd.DataFrame(
        {
            "COD_CLIENTE": ["C1", "C1", ""],
            "NOM_CLIENTE": ["NOM", "OTRO", "NOM"],
            "ID_VENDEDOR": ["V1", "V1", "V2"],
            "NOM_VENDEDOR": ["VEN", "VEN", ""],
        }
    )
    out = ing.verify_clientes_vendedores(df)
    # C1 con 2 nombres -> inconsistente; vacio -> inconsistente
    assert list(out["es_cliente_consistente"]) == [False, False, False]
    assert list(out["es_vendedor_consistente"]) == [True, True, False]


def test_filtrar_familia_multifamilia_y_resumen():
    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["A1", "C1", "F1"],
            "NRO_DOCUMENTO": ["OC1", "OC2", "OC3"],
            "ID_VENDEDOR": ["V1", "V1", "V2"],
            "NOM_VENDEDOR": ["NV1", "NV1", "NV2"],
            "COD_CLIENTE": ["C1", "C2", "C3"],
            "NOM_CLIENTE": ["NC1", "NC2", "NC3"],
            "SKU": ["S1", "S2", "S3"],
            "linea": ["0101", "0102", "0172"],
            "grupo": ["01", "02", "72"],
            "categoria": ["VINIFAN", "VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [100, 200, 100],
            "CAN_DESPACHO": [20, 0, 0],
            "PEDIDO_IMPORTE_ARITCULO": [1000, 2000, 500],
            "un_bx": [10, 10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS", "CONTADO", "FACTURA 60 DIAS"],
            "PEDIDO_ESTADO": ["APROBADO", "APROBADO", "APROBADO"],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 300},
                {"CENTRO LOGISTICO VES": 0},
            ],
        }
    )
    out = ing.compute_derived(df)
    an = PedidosAnalytics(out)
    assert len(an.filtrar_familia("ANTICIPO")) == 1
    assert len(an.filtrar_familia("CONTADO")) == 1
    assert len(an.filtrar_familia("FACTURA")) == 1
    assert len(an.filtrar_familia("LETRA")) == 0
    res = an.resumen_pedidos_familia("CONTADO")
    assert len(res) == 1
    # pct real a pedido total: 0/200 -> 0.0, val ordenado por monto
    assert float(res.iloc[0]["pct_cant"]) == 0.0
    assert PedidosAnalytics.n_letras("LETRA 45, 60 DIAS") == 2
    assert PedidosAnalytics.n_letras("LETRA 60 DIAS") == 1


def test_export_reporte_acciones_6_hojas(tmp_path):
    from src.core.exporters import export_reporte_acciones

    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["A1", "A2"],
            "NRO_DOCUMENTO": ["OC1", "OC2"],
            "ID_VENDEDOR": ["V1", "V1"],
            "NOM_VENDEDOR": ["NV1", "NV1"],
            "COD_CLIENTE": ["C1", "C2"],
            "NOM_CLIENTE": ["NC1", "NC2"],
            "SKU": ["S1", "S2"],
            "ID_ARTICULO": ["S1", "S2"],
            "NOM_ARTICULO": ["N1", "N2"],
            "linea": ["0101", "0101"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [100, 10],
            "CAN_DESPACHO": [40, 0],
            "PEDIDO_IMPORTE_ARITCULO": [5000, 100],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 2,
            "PEDIDO_ESTADO": ["APROBADO"] * 2,
            "PEDIDO_FECHA": ["01/09/2026"] * 2,
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 100},
            ],
        }
    )
    out = ing.compute_derived(df)
    path = export_reporte_acciones(
        out,
        familia="ANTICIPO",
        umbral=1200.0,
        output_path=str(tmp_path / "reaccion.xlsx"),
        guardar_foto=False,
    )
    assert path.exists()
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True)
    # Hojas de accion: el orden importa (BLOQUE A primero).
    esperadas = [
        "LEEME",
        "PANEL",
        "POR_VENDEDOR",
        "PEDIDOS",
        "AVANCE_PEDIDO",
        "POR_CLIENTE",
        "DESPACHO_HOY",
        "TRASLADO_121",
        "COBRANZA",
        "SANEAMIENTO",
        "YA_ENTREGADO",
        "DETALLE_PEDIDO",
        "FOTO_DIA",
    ]
    for hoja in esperadas:
        assert hoja in wb.sheetnames, f"Falta hoja {hoja}: {wb.sheetnames}"


def test_export_incluye_detalle_opcional(tmp_path):
    """DETALLE solo aparece con incluir_detalle=True."""
    from openpyxl import load_workbook

    from src.core.exporters import export_reporte_acciones

    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["A1", "A2"],
            "NRO_DOCUMENTO": ["OC1", "OC2"],
            "ID_VENDEDOR": ["V1", "V1"],
            "NOM_VENDEDOR": ["NV1", "NV1"],
            "COD_CLIENTE": ["C1", "C2"],
            "NOM_CLIENTE": ["NC1", "NC2"],
            "SKU": ["S1", "S2"],
            "ID_ARTICULO": ["S1", "S2"],
            "NOM_ARTICULO": ["N1", "N2"],
            "linea": ["0101", "0101"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [100, 100],
            "CAN_DESPACHO": [100, 40],
            "PEDIDO_IMPORTE_ARITCULO": [1000, 1000],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 2,
            "PEDIDO_ESTADO": ["APROBADO"] * 2,
            "PEDIDO_FECHA": ["01/09/2026"] * 2,
            "stock_api_disponible": [{"CENTRO LOGISTICO VES": 10}, {"CENTRO LOGISTICO VES": 10}],
        }
    )
    out = ing.compute_derived(df)
    base = str(tmp_path / "lean.xlsx")
    wb = load_workbook(export_reporte_acciones(out, output_path=base, guardar_foto=False))
    assert "DETALLE" not in wb.sheetnames
    wb2 = load_workbook(
        export_reporte_acciones(
            out, output_path=str(tmp_path / "full.xlsx"), guardar_foto=False, incluir_detalle=True
        )
    )
    assert "DETALLE" in wb2.sheetnames


def test_pedidos_unificados_incluye_bloqueados():
    """PEDIDOS junta los pedidos de la familia y los bloqueados en una tabla."""
    from src.core.exporters import _pedidos_unificados

    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["A1", "B1"],
            "NRO_DOCUMENTO": ["OC1", "OC2"],
            "ID_VENDEDOR": ["V1", "V1"],
            "NOM_VENDEDOR": ["NV1", "NV1"],
            "COD_CLIENTE": ["C1", "C2"],
            "NOM_CLIENTE": ["NC1", "NC2"],
            "SKU": ["S1", "S2"],
            "linea": ["0101", "0101"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [100, 100],
            "CAN_DESPACHO": [40, 0],
            "PEDIDO_IMPORTE_ARITCULO": [5000, 5000],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS", "CANJE CON LETRA"],
            "PEDIDO_ESTADO": ["APROBADO", "INGRESADO"],
            "PEDIDO_FECHA": ["01/09/2026", "01/09/2026"],
            "stock_api_disponible": [{"CENTRO LOGISTICO VES": 100}, {"CENTRO LOGISTICO VES": 100}],
        }
    )
    out = ing.compute_derived(df)
    an = PedidosAnalytics(out)
    ped = _pedidos_unificados(an, "ANTICIPO", 1200.0)
    estados = dict(zip(ped["ID_PEDIDO"], ped["estado_accion"]))
    assert "A1" in estados and "B1" in estados
    assert estados["B1"] == "BLOQUEADO_ESTADO"
    fams = dict(zip(ped["ID_PEDIDO"], ped["familia"]))
    assert fams["B1"] == "CANJE"
    for col in ("despachable_hoy", "si_se_aprueba", "accion_1", "pct_cubierto"):
        assert col in ped.columns


def test_despacho_hoy_solo_lineas_libres():
    """DESPACHO_HOY excluye lineas con planilla INGRESADO."""
    from src.core.exporters import _despacho_hoy

    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["A1", "A1"],
            "NRO_DOCUMENTO": ["OC1", "OC1"],
            "ID_VENDEDOR": ["V1", "V1"],
            "NOM_VENDEDOR": ["NV1", "NV1"],
            "COD_CLIENTE": ["C1", "C1"],
            "NOM_CLIENTE": ["NC1", "NC1"],
            "SKU": ["S1", "S2"],
            "linea": ["0101", "0101"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [100, 100],
            "CAN_DESPACHO": [0, 0],
            "PEDIDO_IMPORTE_ARITCULO": [5000, 5000],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 2,
            "PEDIDO_ESTADO": ["APROBADO"] * 2,
            "PEDIDO_FECHA": ["01/09/2026"] * 2,
            "ID_PLANILLA_ANTICIPO": ["PL1", "PL2"],
            "NOM_ESTADO_PLANILLA_ANTICIPO": ["APROBADO", "INGRESADO"],
            "stock_api_disponible": [{"CENTRO LOGISTICO VES": 500}] * 2,
        }
    )
    out = ing.compute_derived(df)
    an = PedidosAnalytics(out)
    entrega = an.get_val_atencion("ANTICIPO")
    resumen = an.resumen_pedidos_familia("ANTICIPO")
    hoy = _despacho_hoy(entrega, resumen, 1200.0)
    assert list(hoy["SKU"]) == ["S1"]


def test_alias_pelotas_a_01_y_origen():
    """DB con nombres (PELOTAS) se normaliza a 01 via semilla estatica."""
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["S9"],
            "linea": ["PELOTAS"],
            "grupo": ["NACIONAL"],
            "CAN_PEDIDO": [100],
            "CAN_DESPACHO": [40],
            "PEDIDO_IMPORTE_ARITCULO": [1000],
            "un_bx": [10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"],
            "PEDIDO_ESTADO": ["APROBADO"],
            "stock_api_disponible": [{"CENTRO LOGISTICO VES": 100}],
        }
    )
    out = ing.compute_derived(df)
    assert out.loc[0, "linea_cod"] == "01"
    assert out.loc[0, "origen_linea"] == "ALIAS"
    assert bool(out.loc[0, "es_linea_valida"]) is True
    assert bool(out.loc[0, "es_prototipo"]) is True


def test_build_alias_desde_snapshot():
    cat = {
        "A": {"linea": "01", "linea_nombre": "PELOTAS", "grupo": "01", "grupo_nombre": "NACIONAL"},
        "B": {
            "linea": "78",
            "linea_nombre": "PEGAMENTOS",
            "grupo": "02",
            "grupo_nombre": "IMPORTADO",
        },
    }
    alias = Ingester._build_alias(cat)
    assert alias == {"PELOTAS": "01", "NACIONAL": "01", "PEGAMENTOS": "78", "IMPORTADO": "02"}
    code, name = Ingester._split_code_name("01 - PELOTAS")
    assert (code, name) == ("01", "PELOTAS")
    assert Ingester._split_code_name("PELOTAS") == ("", "PELOTAS")


def test_resumen_accion_y_cobranza():
    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["E1", "E1", "O1", "B1"],
            "NRO_DOCUMENTO": ["OC1"] * 4,
            "ID_VENDEDOR": ["V1"] * 4,
            "NOM_VENDEDOR": ["NV1"] * 4,
            "COD_CLIENTE": ["C1"] * 4,
            "NOM_CLIENTE": ["NC1"] * 4,
            "SKU": ["S1", "S2", "S3", "S4"],
            "NOM_ARTICULO": ["N1", "N2", "N3", "N4"],
            "linea": ["0101", "0101", "0101", "0101"],
            "grupo": ["01"] * 4,
            "categoria": ["VINIFAN"] * 4,
            "CAN_PEDIDO": [100, 100, 10, 50],
            "CAN_DESPACHO": [40, 40, 0, 0],
            "PEDIDO_IMPORTE_ARITCULO": [5000, 5000, 100, 800],
            "un_bx": [10, 10, 10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 3 + ["CANJE CON LETRA"],
            "PEDIDO_ESTADO": ["APROBADO"] * 3 + ["INGRESADO"],
            "PEDIDO_FECHA": ["01/09/2026"] * 4,
            "ID_PLANILLA_ANTICIPO": ["PL1", "PL1", "PL2", ""],
            "NOM_ESTADO_PLANILLA_ANTICIPO": ["APROBADO", "APROBADO", "INGRESADO", ""],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 100},
                {"CENTRO LOGISTICO VES": 0},
                {"CENTRO LOGISTICO VES": 50},
                {"CENTRO LOGISTICO VES": 50},
            ],
        }
    )
    out = ing.compute_derived(df)
    # dias_planilla proxy + bucket + cajas_estimada
    assert "dias_planilla" in out.columns
    assert "planilla_bucket" in out.columns
    assert "cajas_estimada" in out.columns
    an = PedidosAnalytics(out)
    acc = an.resumen_accion_pedido("ANTICIPO", umbral=1200.0)
    estados = dict(zip(acc["ID_PEDIDO"], acc["estado_accion"]))
    # E1: val_atencion 6000>=1200 y 1/2 cubiertas -> PARCIAL
    assert estados["E1"] == "PARCIAL"
    # O1: val 100<1200 -> OBSERVACION
    assert estados["O1"] == "OBSERVACION"
    bloq = an.get_pedidos_bloqueados()
    assert list(bloq["ID_PEDIDO"]) == ["B1"]
    assert bloq.iloc[0]["estado_accion"] == "BLOQUEADO_ESTADO"
    cob = an.resumen_cobranza(umbral_dias=10)
    assert list(cob["ID_PEDIDO"]) == ["O1"]
    assert cob.iloc[0]["accion"] in ("escalar", "seguimiento normal")


def test_traslado_una_fila_por_sku_con_tope_121(tmp_path):
    """Varias lineas del mismo SKU: a_trasladar <= stock_121 y FIFO por fecha."""
    from openpyxl import load_workbook

    from src.core.exporters import export_reporte_acciones

    ing = Ingester()
    # Mismo SKU (S1) en 2 pedidos: 300 + 300 de faltante, 121 solo tiene 400.
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["VIEJO", "NUEVO"],
            "NRO_DOCUMENTO": ["OC1", "OC2"],
            "ID_VENDEDOR": ["V1", "V1"],
            "NOM_VENDEDOR": ["NV1", "NV1"],
            "COD_CLIENTE": ["C1", "C2"],
            "NOM_CLIENTE": ["NC1", "NC2"],
            "SKU": ["S1", "S1"],
            "ID_ARTICULO": ["S1", "S1"],
            "NOM_ARTICULO": ["N1", "N1"],
            "linea": ["0101", "0101"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "CAN_PEDIDO": [300, 300],
            "CAN_DESPACHO": [0, 0],
            "PEDIDO_IMPORTE_ARITCULO": [1000, 1000],
            "un_bx": [10, 10],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 2,
            "PEDIDO_ESTADO": ["APROBADO"] * 2,
            "PEDIDO_FECHA": ["01/09/2026", "20/09/2026"],
            "stock_api_disponible": [
                {"121": 400},
                {"121": 400},
            ],
        }
    )
    out = ing.compute_derived(df)
    path = export_reporte_acciones(
        out,
        familia="ANTICIPO",
        umbral=1200.0,
        output_path=str(tmp_path / "traslado.xlsx"),
        guardar_foto=False,
    )
    wb = load_workbook(path)
    ws = wb["TRASLADO_121"]
    rows = list(ws.iter_rows(values_only=True))
    # Fila 1-2 banda de titulo, 3 encabezados, 4 banda de solicitud, 5+ datos.
    hdr = rows[2]
    data = [r for r in rows[4:] if r and str(r[0]).strip() not in ("", "None")]
    # La banda de solicitud (fila 4) empieza con "TOTAL SOLICITUD".
    assert str(rows[3][0]).startswith("TOTAL SOLICITUD")
    assert len(data) == 1, "debe quedar UNA fila por SKU"
    rec = dict(zip(hdr, data[0]))
    assert rec["SKU"] == "S1"
    assert rec["a_trasladar"] == 400, "nunca mas que el stock 121"
    assert rec["faltante_total"] == 600
    assert rec["fuera_de_alcance_121"] == 200
    assert rec["SKUs_pedidos"] == 2
    # Nuevas columnas de impacto de la solicitud.
    assert rec["accion_si_no_alcanza"] == "TRASLADAR_PARCIAL_Y_REPONER"
    assert rec["valor_traslado"] > 0
    # FIFO: el pedido mas antiguo (VIEJO) consume primero
    assert rec["detalle_fifo"].startswith("VIEJO:300")
    assert "NUEVO:100" in rec["detalle_fifo"]


def test_cache_age_hours_devuelve_float(tmp_path, monkeypatch):
    import json
    import time

    import src.core.ingest as ingest_module

    monkeypatch.setattr(ingest_module, "DATA_DIR", tmp_path)
    (tmp_path / "stock_cache.json").write_text(
        json.dumps({"ts": time.time() - 7200, "stock": {}, "catalog": {}}),
        encoding="utf-8",
    )
    age = Ingester().cache_age_hours()
    assert age is not None and 1.9 < age < 2.1


def test_foto_del_dia_detecta_cambios(tmp_path):
    """La foto del dia clasifica atendido/avance/nuevo/regreso/sin cambio."""
    from src.core.photo import foto_del_dia
    from src.core.snapshot import SnapshotManager

    ayer = pd.DataFrame(
        {
            "ID_PEDIDO": ["A", "B", "C"],
            "ID_ARTICULO": ["S1", "S2", "S3"],
            "CAN_PEDIDO": [100, 100, 100],
            "CAN_DESPACHO": [0, 0, 0],
            "saldo": [100, 100, 100],
            "PEDIDO_ESTADO": ["APROBADO"] * 3,
        }
    )
    snap = SnapshotManager(tmp_path)
    snap.save_snapshot(ayer, label="foto_ayer")

    hoy = pd.DataFrame(
        {
            "ID_PEDIDO": ["A", "B", "C", "D"],
            "CAN_PEDIDO": [100, 100, 100, 50],
            "CAN_DESPACHO": [100, 40, 0, 0],
            "saldo": [0, 60, 100, 50],
            "valor_saldo": [0, 600, 1000, 500],
            "NOM_VENDEDOR": ["V1"] * 4,
            "NOM_CLIENTE": ["C1"] * 4,
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 4,
        }
    )
    foto, resumen = foto_del_dia(hoy, snap, "foto_ayer")
    camb = dict(zip(foto["ID_PEDIDO"], foto["cambio"]))
    assert camb["A"] == "ATENDIDO"
    assert camb["B"] == "AVANCE"
    assert camb["C"] == "SIN_CAMBIO"
    assert camb["D"] == "NUEVO"
    assert resumen["atendidos"] == 1
    assert resumen["avance"] == 1
    assert resumen["nuevos"] == 1
    assert resumen["delta_total"] == -90.0
    assert resumen["base"] == "foto_ayer"
    # sin base previa -> degrada sin inventar deltas
    foto2, res2 = foto_del_dia(hoy, SnapshotManager(tmp_path / "vacio"), None)
    assert res2["base"] is None
    assert foto2.empty


def test_split_planilla_y_prio_sugerida():
    """despachable_hoy (libre) vs si_se_aprueba (planilla INGRESADO) + P1..P5."""
    ing = Ingester()
    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["L1", "B1", "T1"],
            "NRO_DOCUMENTO": ["OC1"] * 3,
            "ID_VENDEDOR": ["V1"] * 3,
            "NOM_VENDEDOR": ["NV1"] * 3,
            "COD_CLIENTE": ["C1"] * 3,
            "NOM_CLIENTE": ["NC1"] * 3,
            "SKU": ["S1", "S2", "S3"],
            "NOM_ARTICULO": ["N1", "N2", "N3"],
            "linea": ["0101"] * 3,
            "grupo": ["01"] * 3,
            "categoria": ["VINIFAN"] * 3,
            "CAN_PEDIDO": [100, 100, 100],
            "CAN_DESPACHO": [0, 0, 0],
            "PEDIDO_IMPORTE_ARITCULO": [5000, 5000, 5000],
            "un_bx": [10] * 3,
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"] * 3,
            "PEDIDO_ESTADO": ["APROBADO"] * 3,
            "PEDIDO_FECHA": ["01/09/2026"] * 3,
            "ID_PLANILLA_ANTICIPO": ["P1", "P2", "P3"],
            "NOM_ESTADO_PLANILLA_ANTICIPO": ["APROBADO", "INGRESADO", "APROBADO"],
            "stock_api_disponible": [
                {"CENTRO LOGISTICO VES": 500},  # L1 cubierto
                {"CENTRO LOGISTICO VES": 500},  # B1 cubierto pero bloqueado
                {"CENTRO LOGISTICO VES": 0, "121": 500},  # T1 sin VES, con 121
            ],
        }
    )
    out = ing.compute_derived(df)
    an = PedidosAnalytics(out)
    acc = an.resumen_accion_pedido("ANTICIPO", umbral=1200.0).set_index("ID_PEDIDO")
    # L1: planilla APROBADO + cubierto -> libre, P1
    assert acc.loc["L1", "despachable_hoy"] > 0
    assert acc.loc["L1", "si_se_aprueba"] == 0
    assert acc.loc["L1", "prio_sugerida"] == "P1"
    assert acc.loc["L1", "accion_1"] == "DESPACHAR"
    # B1: planilla INGRESADO -> condicionado, P4
    assert acc.loc["B1", "despachable_hoy"] == 0
    assert acc.loc["B1", "si_se_aprueba"] > 0
    assert acc.loc["B1", "prio_sugerida"] == "P4"
    assert acc.loc["B1", "accion_1"] == "APROBAR_PLANILLA"
    # T1: sin VES pero 121 -> P3 traslado
    assert acc.loc["T1", "prio_sugerida"] == "P3"
    assert acc.loc["T1", "accion_1"] == "SOLICITAR_TRASLADO"
    assert acc.loc["T1", "pct_cubierto"] == 0.0
