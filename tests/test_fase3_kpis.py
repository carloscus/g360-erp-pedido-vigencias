"""Tests Fase 3: KPIs separados, desglose por estado_linea y faltantes exactos."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.analytics import PedidosAnalytics  # noqa: E402


def _df_analitica():
    """DataFrame con lo que el motor de analitica necesita."""
    return pd.DataFrame(
        [
            {
                "ID_PEDIDO": "P1",
                "ID_ARTICULO": "SKU_A",
                "SKU": "SKU_A",
                "CONDICION_PAGO": "ANTICIPO EN LETRAS",
                "PEDIDO_ESTADO": "APROBADO",
                "NOM_ESTADO_PLANILLA_ANTICIPO": "APROBADO",
                "CAN_PEDIDO": 100,
                "CAN_DESPACHO": 40,
                "saldo": 60,
                "valor_saldo": 600.0,
                "un_bx": 10,
                "linea": "78",
                "categoria": "VINIFAN",
                "estado_linea": "NUEVO",
                "stock_real": 60,
                "stock_api_ves": 60,
                "stock_api_121": 500,
                "val_atencion": 400.0,
                "val_pendiente": 200.0,
            },
            {
                "ID_PEDIDO": "P1",
                "ID_ARTICULO": "SKU_B",
                "SKU": "SKU_B",
                "CONDICION_PAGO": "ANTICIPO EN LETRAS",
                "PEDIDO_ESTADO": "APROBADO",
                "NOM_ESTADO_PLANILLA_ANTICIPO": "APROBADO",
                "CAN_PEDIDO": 50,
                "CAN_DESPACHO": 0,
                "saldo": 50,
                "valor_saldo": 250.0,
                "un_bx": 5,
                "linea": "79",
                "categoria": "VINIFAN",
                "estado_linea": "TRADICIONAL",
                "stock_real": 0,
                "stock_api_ves": 0,
                "stock_api_121": 500,
                "val_atencion": 0.0,
                "val_pendiente": 250.0,
            },
            {
                "ID_PEDIDO": "P2",
                "ID_ARTICULO": "SKU_C",
                "SKU": "SKU_C",
                "CONDICION_PAGO": "ANTICIPO EN LETRAS",
                "PEDIDO_ESTADO": "APROBADO",
                "NOM_ESTADO_PLANILLA_ANTICIPO": "APROBADO",
                "CAN_PEDIDO": 20,
                "CAN_DESPACHO": 20,
                "saldo": 0,
                "valor_saldo": 0.0,
                "un_bx": 2,
                "linea": "78",
                "categoria": "VINIFAN",
                "estado_linea": "NUEVO",
                "stock_real": 20,
                "stock_api_ves": 20,
                "stock_api_121": 0,
                "val_atencion": 200.0,
                "val_pendiente": 0.0,
            },
        ]
    )


class TestKPIsSeparados:
    def test_pendiente_cubrible_liberado_son_distintos(self):
        """Las tres medidas no se confunden: pendiente > cubrible > liberado."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        assert not acc.empty
        # P1: saldo 110, VES cubre 60, 121 cubre 50 -> cubrible 110
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        assert float(row["saldo"]) == 110
        # 121 cubre el resto (50 <= 500 disponible)
        assert float(row["trasladable"]) == 50

    def test_cubrible_usa_ves_mas_121(self):
        """El saldo cubrible es VES + 121 (aun sin autorizacion)."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        # 60 cubiertos por VES + 50 por 121 = 110 (todo el saldo)
        assert float(row["saldo"]) == 110
        assert float(row["trasladable"]) == 50

    def test_liberado_exige_autorizacion(self):
        """Lo bloqueado por planilla NO es saldo liberado."""
        df = _df_analitica()
        # P1 pasa a planilla INGRESADO -> bloqueado
        df.loc[df["ID_PEDIDO"] == "P1", "NOM_ESTADO_PLANILLA_ANTICIPO"] = "INGRESADO"
        an = PedidosAnalytics(df)
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        assert float(row["despachable_hoy"]) == 0
        assert float(row["si_se_aprueba"]) > 0


class TestFaltantesExactos:
    def test_skus_faltantes_cuenta(self):
        """skus_faltantes = cuantos SKU con saldo sin cubrir."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        # SKU_A: 60 saldo, VES 60 -> cubierto. SKU_B: 50 saldo, VES 0 -> falta
        assert int(row["skus_faltantes"]) == 1
        assert float(row["unidades_faltantes"]) == 50

    def test_detalle_faltantes_dice_que_sku(self):
        """detalle_faltantes lista SKU:unidades de lo que falta."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        det = str(row["detalle_faltantes"])
        assert "SKU_B" in det
        assert "50" in det

    def test_pedido_sin_faltantes_detalle_vacio(self):
        """Un pedido con saldo cubierto por VES no lista faltantes."""
        df = _df_analitica()
        # P2 pasa a tener saldo pendiente pero cubierto por VES
        df.loc[df["ID_PEDIDO"] == "P2", "CAN_DESPACHO"] = 0
        df.loc[df["ID_PEDIDO"] == "P2", "saldo"] = 20
        an = PedidosAnalytics(df)
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P2"].iloc[0]
        assert int(row["skus_faltantes"]) == 0
        assert str(row["detalle_faltantes"]) == ""
        assert float(row["unidades_faltantes"]) == 0


class TestDesgloseEstadoLinea:
    def test_desglose_por_estado_linea_cuadra(self):
        """La suma por estado_linea debe igualar el saldo pendiente total."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        total = float(acc["saldo"].sum())
        por_estado = acc.groupby("estados_linea")["saldo"].sum()
        assert abs(float(por_estado.sum()) - total) < 0.01

    def test_estados_linea_agrupados_por_pedido(self):
        """estados_linea lista los estados presentes en el pedido."""
        an = PedidosAnalytics(_df_analitica())
        acc = an.resumen_accion_pedido("ANTICIPO", 1200.0)
        row = acc[acc["ID_PEDIDO"] == "P1"].iloc[0]
        assert "NUEVO" in str(row["estados_linea"])
        assert "TRADICIONAL" in str(row["estados_linea"])
