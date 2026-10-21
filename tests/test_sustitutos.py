"""Tests del motor de sustitucion (4 niveles, EAN-first)."""

from src.core.sustitutos import (
    MotorSustitutos,
    cargar_sustitutos_csv,
    enriquecer_con_sustitutos,
    indice_ean,
    jaccard,
)


def _universo():
    import pandas as pd

    # Replica de los 3 pares validados del usuario + ruido del mismo grupo.
    return pd.DataFrame(
        [
            {
                "SKU": "02176",
                "NOM_ARTICULO": "BOLSA X10 FORRO EXPRESS ECO NP",
                "linea": "02",
                "grupo": "EXPRESS",
                "un_bx": 36,
                "precio_unitario": 4.40,
                "stock_real": 0,
                "producto_descontinuado": True,
            },
            {
                "SKU": "02196",
                "NOM_ARTICULO": "BLS X10 FORRO EXPRESS ECO NEW",
                "linea": "02",
                "grupo": "EXPRESS",
                "un_bx": 36,
                "precio_unitario": 4.24,
                "stock_real": 50,
                "producto_descontinuado": False,
            },
            {
                "SKU": "02210",
                "NOM_ARTICULO": "VINIFAN OF CR 26",
                "linea": "02",
                "grupo": "VINIFAN",
                "un_bx": 100,
                "precio_unitario": 7.23,
                "stock_real": 0,
                "producto_descontinuado": True,
            },
            {
                "SKU": "02217",
                "NOM_ARTICULO": "VINIFAN OF CR 27",
                "linea": "02",
                "grupo": "VINIFAN",
                "un_bx": 100,
                "precio_unitario": 7.31,
                "stock_real": 80,
                "producto_descontinuado": False,
            },
            {
                "SKU": "02193",
                "NOM_ARTICULO": "VINIFORRO OFICIO CRISTAL 23",
                "linea": "02",
                "grupo": "VINIFAN",
                "un_bx": 100,
                "precio_unitario": 4.13,
                "stock_real": 30,
                "producto_descontinuado": False,
            },
        ]
    )


def _productos():
    return {
        "02176": {"ean13": "7754807021968"},
        "02196": {"ean13": "7754807021968"},
        "02210": {"ean13": "7754807020015"},
        "02217": {"ean13": "7754807020015"},
        "02193": {"ean13": "7754807021203"},
    }


class TestIndiceEan:
    def test_agrupa_skus_por_ean(self):
        idx = indice_ean(_productos())
        assert sorted(idx["7754807021968"]) == ["02176", "02196"]
        assert sorted(idx["7754807020015"]) == ["02210", "02217"]

    def test_descarta_ean_vacio_o_cero(self):
        idx = indice_ean({"X": {"ean13": "0"}, "Y": {"ean13": ""}, "Z": {}})
        assert idx == {}

    def test_descarta_nan_como_texto(self):
        # Regresion: el maestro entrega ean14='nan' (texto). Sin filtrar,
        # TODOS los SKUs sin EAN colisionaban en la clave 'nan' y el NIVEL 1
        # agrupaba productos distintos como si fueran el mismo.
        idx = indice_ean(
            {
                "A": {"ean13": "7754807143752", "ean14": "nan"},
                "B": {"ean13": "7754807110280", "ean14": "nan"},
                "C": {"ean13": "7754807160049", "ean14": "NaN"},
            }
        )
        assert len(idx) == 3, f"no debe agrupar por 'nan': {idx}"
        assert "nan" not in idx and "NaN" not in idx

    def test_normaliza_float(self):
        idx = indice_ean(
            {
                "A": {"ean13": "7754807110280.0"},
                "B": {"ean13": "7754807110280"},
            }
        )
        assert idx == {"7754807110280": ["A", "B"]}


class TestJaccard:
    def test_identicos(self):
        assert jaccard("BOLSA X10 FORRO EXPRESS", "BOLSA X10 FORRO EXPRESS") == 1.0

    def test_sin_tokens(self):
        assert jaccard("", "algo") == 0.0


class TestMotorSustitutos:
    def test_nivel_1_ean_gana(self):
        m = MotorSustitutos(_universo(), productos=_productos())
        s = m.sugerir("02176")
        assert s["sustituto_sugerido"] == "02196"
        assert s["nivel_confianza"] == "CERTEZA"
        assert s["sustituto_origen"] == "EAN"
        assert s["sustituto_stock"] == 50

    def test_nivel_1_segundo_par(self):
        m = MotorSustitutos(_universo(), productos=_productos())
        s = m.sugerir("02210")
        assert s["sustituto_sugerido"] == "02217"
        assert s["nivel_confianza"] == "CERTEZA"

    def test_prefiere_no_descontinuado_con_stock(self):
        productos = {"A": {"ean13": "111"}, "B": {"ean13": "111"}}
        import pandas as pd

        uni = pd.DataFrame(
            [
                {
                    "SKU": "A",
                    "NOM_ARTICULO": "X",
                    "linea": "1",
                    "grupo": "G",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 5,
                    "producto_descontinuado": True,
                },
                {
                    "SKU": "B",
                    "NOM_ARTICULO": "X",
                    "linea": "1",
                    "grupo": "G",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 5,
                    "producto_descontinuado": False,
                },
            ]
        )
        m = MotorSustitutos(uni, productos=productos)
        assert m.sugerir("A")["sustituto_sugerido"] == "B"

    def test_manual_pisa_heuristico(self):
        m = MotorSustitutos(
            _universo(),
            productos=_productos(),
            curados={"02176": {"sku": "02193", "motivo": "criterio comercial"}},
        )
        s = m.sugerir("02176")
        assert s["sustituto_sugerido"] == "02193"
        assert s["nivel_confianza"] == "CURADO"
        assert s["sustituto_origen"] == "CURADO"

    def test_nivel_4_sin_candidato(self):
        import pandas as pd

        uni = pd.DataFrame(
            [
                {
                    "SKU": "ZZ1",
                    "NOM_ARTICULO": "PIEZA UNICA",
                    "linea": "99",
                    "grupo": "SOLO",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 0,
                    "producto_descontinuado": True,
                },
            ]
        )
        m = MotorSustitutos(uni, productos={})
        s = m.sugerir("ZZ1")
        assert s["sustituto_sugerido"] == ""
        assert s["nivel_confianza"] == "REQUIERE_CRITERIO"
        assert s["sustituto_origen"] == ""

    def test_nivel_2_homologo_por_nombre(self):
        import pandas as pd

        # sin EAN compartido: mismo linea+grupo+un_bx y nombre parecido
        uni = pd.DataFrame(
            [
                {
                    "SKU": "OLD1",
                    "NOM_ARTICULO": "FOLDER OFICIO AZUL CARTON",
                    "linea": "78",
                    "grupo": "FOLDER",
                    "un_bx": 25,
                    "precio_unitario": 5.0,
                    "stock_real": 0,
                    "producto_descontinuado": True,
                },
                {
                    "SKU": "NEW1",
                    "NOM_ARTICULO": "FOLDER OFICIO AZUL CARTON NP",
                    "linea": "78",
                    "grupo": "FOLDER",
                    "un_bx": 25,
                    "precio_unitario": 5.1,
                    "stock_real": 40,
                    "producto_descontinuado": False,
                },
            ]
        )
        m = MotorSustitutos(uni, productos={})
        s = m.sugerir("OLD1")
        assert s["sustituto_sugerido"] == "NEW1"
        assert s["nivel_confianza"] == "HOMOLOGO_DIRECTO"
        assert s["sustituto_origen"] == "HEURISTICA"

    def test_nivel_3_mismo_segmento(self):
        import pandas as pd

        uni = pd.DataFrame(
            [
                {
                    "SKU": "OLD2",
                    "NOM_ARTICULO": "GRAPAS 26/6 CAJA X 1000",
                    "linea": "11",
                    "grupo": "GRAPAS",
                    "un_bx": 20,
                    "precio_unitario": 8.0,
                    "stock_real": 0,
                    "producto_descontinuado": True,
                },
                {
                    "SKU": "NEW2",
                    "NOM_ARTICULO": "PERFORADOR METALICO GRANDE",
                    "linea": "11",
                    "grupo": "GRAPAS",
                    "un_bx": 20,
                    "precio_unitario": 8.2,
                    "stock_real": 15,
                    "producto_descontinuado": False,
                },
            ]
        )
        m = MotorSustitutos(uni, productos={})
        s = m.sugerir("OLD2")
        assert s["nivel_confianza"] == "MISMO_SEGMENTO"

    def test_no_sugiere_descontinuado_ni_sin_stock(self):
        import pandas as pd

        uni = pd.DataFrame(
            [
                {
                    "SKU": "OLD3",
                    "NOM_ARTICULO": "COSA",
                    "linea": "1",
                    "grupo": "G",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 0,
                    "producto_descontinuado": True,
                },
                {
                    "SKU": "D1",
                    "NOM_ARTICULO": "COSA NP",
                    "linea": "1",
                    "grupo": "G",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 9,
                    "producto_descontinuado": True,
                },
                {
                    "SKU": "S0",
                    "NOM_ARTICULO": "COSA NP2",
                    "linea": "1",
                    "grupo": "G",
                    "un_bx": 1,
                    "precio_unitario": 1,
                    "stock_real": 0,
                    "producto_descontinuado": False,
                },
            ]
        )
        m = MotorSustitutos(uni, productos={})
        assert m.sugerir("OLD3")["sustituto_sugerido"] == ""


class TestCsvCurado:
    def test_lee_csv(self, tmp_path):
        p = tmp_path / "sustitutos.csv"
        p.write_text(
            "sku_origen,sku_reemplazo,motivo,aprobado_por\n02176,02193,criterio,CARLOS\n",
            encoding="utf-8",
        )
        cur = cargar_sustitutos_csv(p)
        assert cur["02176"]["sku"] == "02193"
        assert cur["02176"]["aprobado_por"] == "CARLOS"

    def test_csv_inexistente(self):
        assert cargar_sustitutos_csv(None) == {}
        assert cargar_sustitutos_csv("no_existe.csv") == {}


class TestEnriquecer:
    def test_solo_llena_descontinuados(self):
        uni = _universo()
        out = enriquecer_con_sustitutos(uni, productos=_productos())
        # 02176 es descontinuado -> tiene sugerencia
        f = out[out["SKU"] == "02176"].iloc[0]
        assert f["sustituto_sugerido"] == "02196"
        assert f["nivel_confianza"] == "CERTEZA"
        # 02196 no es descontinuado -> queda vacio
        g = out[out["SKU"] == "02196"].iloc[0]
        assert g["sustituto_sugerido"] == ""
        assert g["nivel_confianza"] == ""
