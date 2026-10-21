"""
Tests del catalogo unico (cartucho), el allowlist estricto y las reglas de linea.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile

import pandas as pd
import pytest

from src.core.allowlist import (
    MOTIVO_FUERA,
    MOTIVO_LINEA_VACIA,
    MOTIVO_SIN_LINEA,
    aplicar_allowlist,
    cargar_allowlist,
    codigo_linea,
    codigo_y_validez,
)
from src.core.catalogo_unico import CatalogoUnico, normalizar_nombre
from src.core.lineas import linea_sufijo, resolver_codigo_linea

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_CATALOGO = {
    "meta": {
        "origen": "cartucho-test.zip",
        "sha256": "abc123",
        "generado_en": "2026-10-12T17:32:00",
        "ventana": {"anios": 5, "ancla": "2026-10-12", "desde": "2021-10-13"},
        "allowlist": ["01", "78", "MA"],
        "conteos": {"lineas": 3, "articulos": 2},
    },
    "lineas": {
        "01": {"nombre": "PELOTAS", "grupo": "01", "familia": "01"},
        "78": {"nombre": "ARCHIVO", "grupo": "01", "familia": "02"},
        "77": {"nombre": "PINTURA", "grupo": "02", "familia": "02"},
        "MA": {"nombre": "MASCOTAS", "grupo": "01", "familia": "03"},
        "20": {"nombre": "PRODUCTOS INDUSTRIALES", "grupo": "01", "familia": "13"},
    },
    "alias_linea": {
        "01": "01",
        "PELOTAS": "01",
        "78": "78",
        "ARCHIVO": "78",
        "77": "77",
        "PINTURA": "77",
        "MA": "MA",
        "MASCOTAS": "MA",
        "20": "20",
        "PRODUCTOS INDUSTRIALES": "20",
    },
    "articulos": {
        "011019": {
            "id_articulo": "011019",
            "nombre": "PELOTA",
            "linea": "01",
            "linea_nombre": "PELOTAS",
            "grupo": "01",
            "grupo_nombre": "NACIONAL",
            "familia": "01",
            "familia_nombre": "FUTBOL",
            "n_ventas": 10,
            "ultima_venta": "2026-09-28",
        },
        "A9999": {
            "id_articulo": "A9999",
            "nombre": "ARCHIVO X",
            "linea": "78",
            "linea_nombre": "ARCHIVO",
            "grupo": "01",
            "grupo_nombre": "NACIONAL",
            "familia": "02",
            "familia_nombre": "A4",
            "n_ventas": 3,
            "ultima_venta": "2026-09-01",
        },
    },
    "alias_sku": {"ART9999": "A9999"},
    "vendedores": {"178": {"nombre": "MILCA REYES", "n_ventas": 9}},
    "clientes": {
        "00002005": {
            "nombre": "TIENDAS DEL HOGAR S.A.",
            "doc": "20112273922",
            "dep": "LIMA",
            "prov": "LIMA",
            "dist": "SURQUILLO",
            "n_ventas": 4,
            "total_soles": 10.0,
            "ultima_compra": "2026-09-17",
        },
    },
    "alias_cliente": {"TIENDAS DEL HOGAR": "00002005"},
    "conteos": {"lineas": 4, "articulos": 2, "vendedores": 1, "clientes": 1},
}


@pytest.fixture()
def catalogo(tmp_path):
    """Catalogo unico de prueba en disco."""
    path = tmp_path / "catalogo_unico.json"
    path.write_text(json.dumps(_CATALOGO, ensure_ascii=False), encoding="utf-8")
    cat = CatalogoUnico(path)
    assert cat.cargar() is True
    return cat


# ---------------------------------------------------------------------------
# Reglas de linea (src/core/lineas.py)
# ---------------------------------------------------------------------------
def test_linea_sufijo_reglas():
    assert linea_sufijo("0101") == "01"
    assert linea_sufijo("01MA") == "MA"
    assert linea_sufijo(" 01ca ") == "CA"
    assert linea_sufijo("") == ""
    assert linea_sufijo(None) == ""


def test_resolver_codigo_linea_formatos():
    assert resolver_codigo_linea("0101") == "01"
    assert resolver_codigo_linea("01MA") == "MA"
    assert resolver_codigo_linea("0178 - ARCHIVO") == "78"
    assert resolver_codigo_linea("01 - PELOTAS") == "01"
    assert resolver_codigo_linea("PELOTAS", {"PELOTAS": "01"}) == "01"
    assert resolver_codigo_linea("PELOTAS") == ""


# ---------------------------------------------------------------------------
# Catalogo unico
# ---------------------------------------------------------------------------
def test_catalogo_resuelve_linea_por_codigo_y_nombre(catalogo):
    assert catalogo.codigo_linea("78") == "78"
    assert catalogo.codigo_linea("0178 - ARCHIVO") == "78"
    assert catalogo.codigo_linea("ARCHIVO") == "78"
    assert catalogo.codigo_linea("PELOTAS") == "01"
    assert catalogo.codigo_linea("01MA") == "MA"
    assert catalogo.codigo_linea("NO EXISTE") == ""


def test_catalogo_articulo_por_sku_y_por_id(catalogo):
    art = catalogo.articulo("011019")
    assert art is not None
    assert art["linea"] == "01"
    assert art["familia_nombre"] == "FUTBOL"
    # por id_articulo (via alias_sku)
    assert catalogo.articulo("ART9999")["linea"] == "78"
    assert catalogo.articulo("NO") is None


def test_catalogo_allowlist_y_origen(catalogo):
    assert catalogo.allowlist == ["01", "78", "MA"]
    assert "cartucho-test.zip" in catalogo.origen


def test_catalogo_es_linea_valida_usa_allowlist(catalogo):
    assert catalogo.es_linea_valida("78") is True
    assert catalogo.es_linea_valida("ARCHIVO") is True
    # 20 existe en el maestro pero NO esta en la allowlist
    assert catalogo.es_linea_valida("20") is False
    assert catalogo.es_linea_valida("99") is False


def test_catalogo_cliente_por_nombre_normalizado(catalogo):
    cli = catalogo.cliente_por_nombre("TIENDAS DEL HOGAR S.A.")
    assert cli is not None
    assert cli["doc"] == "20112273922"
    assert cli["dist"] == "SURQUILLO"
    # con acentos/puntuacion distintos
    assert catalogo.cliente_por_nombre("TIENDAS DEL HOGAR, S.A.") is not None
    assert catalogo.cliente_por_nombre("NO EXISTE SA") is None


def test_catalogo_vendedor_por_id(catalogo):
    assert catalogo.vendedor("178")["nombre"] == "MILCA REYES"
    assert catalogo.vendedor("999") is None


def test_catalogo_ausente_degrada_sin_error(tmp_path):
    cat = CatalogoUnico(tmp_path / "no_existe.json")
    assert cat.cargar() is False
    assert cat.disponible is False
    assert cat.articulo("X") is None
    assert cat.codigo_linea("78") == ""
    assert cat.allowlist  # cae al default


def test_normalizar_nombre_quita_forma_juridica():
    assert normalizar_nombre("3M PERU S.A.") == "3M PERU"
    assert normalizar_nombre("WLT PERU S.A.C.") == "WLT PERU"
    assert normalizar_nombre("  AÑOS  ") == "ANOS"
    assert normalizar_nombre("") == ""


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
def _df_lineas():
    return pd.DataFrame(
        {
            "SKU": ["S1", "S2", "S3", "S4"],
            "linea": ["78", "20", "ARCHIVO", ""],
            "grupo": ["01", "01", "01", "01"],
            "ID_PEDIDO": ["P1", "P2", "P3", "P4"],
            "saldo": [10, 20, 30, 40],
            "valor_saldo": [100, 200, 300, 400],
        }
    )


def test_aplicar_allowlist_separa_y_motiva():
    df = _df_lineas()
    ok, rej, resumen = aplicar_allowlist(df, ["01", "78"], resolver=codigo_linea)
    assert len(ok) == 2
    assert len(rej) == 2
    assert resumen["filas_aceptadas"] == 2
    assert resumen["filas_rechazadas"] == 2
    assert resumen["pedidos_rechazados"] == 2
    motivos = dict(zip(rej["ID_PEDIDO"], rej["motivo_rechazo"]))
    assert motivos["P2"] == MOTIVO_FUERA  # linea 20 no autorizada
    assert motivos["P4"] == MOTIVO_LINEA_VACIA  # linea vacia
    # 'ARCHIVO' (P3) se resuelve por maestro -> valida
    assert "P3" in set(ok["ID_PEDIDO"])


def test_allowlist_no_acepta_grupo_como_respaldo_de_linea_no_autorizada():
    """Regla estricta: la linea manda; el grupo no salva una linea industrial."""
    df = pd.DataFrame(
        {
            "SKU": ["S1"],
            "linea": ["20"],
            "grupo": ["01"],
            "ID_PEDIDO": ["P1"],
            "saldo": [1],
            "valor_saldo": [1],
        }
    )
    ok, rej, resumen = aplicar_allowlist(df, ["01"], resolver=codigo_linea)
    assert len(ok) == 0
    assert resumen["filas_rechazadas"] == 1


def test_codigo_y_validez_ignora_el_grupo_como_respaldo():
    """REGLA ESTRICTA: el grupo no rescata una linea vacia ni una no autorizada."""
    cod, ok = codigo_y_validez("", "01", {"01"}, None)
    assert cod == "" and ok is False
    cod, ok = codigo_y_validez("20", "01", {"01"}, None)
    assert cod == "20" and ok is False
    cod, ok = codigo_y_validez("78", "01", {"78"}, None)
    assert cod == "78" and ok is True


def test_cargar_allowlist_desde_texto_y_json(tmp_path):
    assert cargar_allowlist("01, 78 ,ma") == ["01", "78", "MA"]
    p = tmp_path / "al.json"
    p.write_text(json.dumps({"allowlist": ["78", "01"]}), encoding="utf-8")
    assert cargar_allowlist(str(p)) == ["01", "78"]
    with pytest.raises(ValueError):
        cargar_allowlist(str(tmp_path / "no_existe.json"))


def test_cargar_allowlist_vacio_es_error(tmp_path):
    p = tmp_path / "vacio.json"
    p.write_text(json.dumps({"allowlist": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        cargar_allowlist(str(p))


# ---------------------------------------------------------------------------
# Importador del cartucho (src/core/cartucho.py)
# ---------------------------------------------------------------------------
def _db_minima(path):
    """Crea un historial.db minimo con las dimensiones del contrato."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE dim_linea (id_linea TEXT PRIMARY KEY, nom_linea TEXT,
            id_grupo TEXT, nom_grupo TEXT, id_familia TEXT, nom_familia TEXT,
            n_ventas INTEGER DEFAULT 0, total_soles REAL DEFAULT 0);
        CREATE TABLE dim_articulo (id_articulo TEXT PRIMARY KEY, original_sku TEXT,
            nom_articulo TEXT NOT NULL, id_linea TEXT, nom_linea TEXT, id_grupo TEXT,
            nom_grupo TEXT, id_tipo TEXT, nom_tipo TEXT, id_familia TEXT, nom_familia TEXT,
            n_ventas INTEGER DEFAULT 0, total_cantidad REAL DEFAULT 0,
            total_soles REAL DEFAULT 0, precio_promedio REAL DEFAULT 0,
            ultima_venta TEXT);
        CREATE TABLE dim_cliente (id_cliente TEXT PRIMARY KEY, nom_cliente TEXT NOT NULL,
            doc_cliente TEXT, departamento TEXT, provincia TEXT, distrito TEXT,
            n_ventas INTEGER DEFAULT 0, total_soles REAL DEFAULT 0,
            total_dolares REAL DEFAULT 0, ultima_compra TEXT);
        CREATE TABLE dim_vendedor (id_vendedor TEXT PRIMARY KEY, nom_vendedor TEXT NOT NULL,
            n_ventas INTEGER DEFAULT 0, total_soles REAL DEFAULT 0, n_clientes INTEGER DEFAULT 0,
            ultima_venta TEXT);
        """
    )
    con.execute("INSERT INTO dim_linea VALUES ('78','ARCHIVO','01','NACIONAL','02','A4',5,10.0)")
    con.execute(
        "INSERT INTO dim_linea VALUES ('20','PRODUCTOS INDUSTRIALES','01','PVC','13','FILM',7,20.0)"
    )
    con.execute(
        "INSERT INTO dim_articulo VALUES ('011019','011019','PELOTA','01','PELOTAS','01','NACIONAL',"
        "'01','X','01','FUTBOL',3,10.0,100.0,10.0,'2026-09-28')"
    )
    con.execute(
        "INSERT INTO dim_articulo VALUES ('OLD1','OLD1','VIEJO','78','ARCHIVO','01','NACIONAL',"
        "'01','X','02','A4',1,1.0,1.0,1.0,'2019-01-01')"
    )
    con.execute(
        "INSERT INTO dim_cliente VALUES ('00002005','TIENDAS DEL HOGAR S.A.','20112273922',"
        "'LIMA','LIMA','SURQUILLO',4,50.0,0.0,'2026-09-17')"
    )
    con.execute(
        "INSERT INTO dim_cliente VALUES ('00009999','CLIENTE VIEJO','20119999999',"
        "'LIMA','LIMA','LIMA',1,1.0,0.0,'2018-01-01')"
    )
    con.execute("INSERT INTO dim_vendedor VALUES ('178','MILCA REYES',9,100.0,3,'2026-09-26')")
    con.execute("INSERT INTO dim_vendedor VALUES ('999','VENDEDOR VIEJO',1,1.0,1,'2018-01-01')")
    con.commit()
    con.close()


def test_construir_catalogo_filtra_ventana_de_anos(tmp_path):
    from src.core.cartucho import construir_catalogo

    db = tmp_path / "historial.db"
    _db_minima(db)
    cat = construir_catalogo(db, "2021-10-13")
    # lineas: completas (es el esqueleto)
    assert set(cat["lineas"]) == {"78", "20"}
    assert cat["alias_linea"]["ARCHIVO"] == "78"
    # articulos: solo con actividad en la ventana
    assert "011019" in cat["articulos"]
    assert "OLD1" not in cat["articulos"]
    # vendedores y clientes: idem
    assert "178" in cat["vendedores"]
    assert "999" not in cat["vendedores"]
    assert "00002005" in cat["clientes"]
    assert "00009999" not in cat["clientes"]
    # alias por nombre normalizado
    assert cat["alias_cliente"]["TIENDAS DEL HOGAR"] == "00002005"


def test_importar_cartucho_idempotente_por_sha(tmp_path):
    from src.core.cartucho import (
        CATALOGO_UNICO_PATH,
        buscar_cartucho,
        importar_cartucho,
        leer_manifiesto,
    )

    db = tmp_path / "historial.db"
    _db_minima(db)
    zip_path = tmp_path / "cartucho-test.zip"
    manifiesto = {
        "db": {"sha256": "sha-abc", "bytes": 1, "fecha_max": "2026-10-12"},
        "config": {"allowlist": ["78", "01"]},
        "contrato_version": 3,
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CARTUCHO.json", json.dumps(manifiesto))
        zf.write(db, "historial.db")

    destino = tmp_path / "catalogo_unico.json"
    cat = importar_cartucho(zip_path, destino=destino, anios=5, log=lambda *a: None)
    assert cat["meta"]["sha256"] == "sha-abc"
    assert cat["meta"]["allowlist"] == ["78", "01"]
    assert cat["meta"]["ventana"]["desde"] == "2021-10-13"
    assert destino.exists()

    # idempotente: no vuelve a extraer
    calls = []
    cat2 = importar_cartucho(zip_path, destino=destino, anios=5, log=lambda m: calls.append(m))
    assert any("Ya esta importado" in str(c) for c in calls)
    assert cat2["meta"]["sha256"] == "sha-abc"

    # el manifiesto se lee sin extraer la DB
    assert leer_manifiesto(zip_path)["db"]["sha256"] == "sha-abc"
    assert buscar_cartucho(tmp_path) == zip_path


def test_importar_cartucho_falla_si_no_es_cartucho(tmp_path):
    from src.core.cartucho import CartuchoError, leer_manifiesto

    falso = tmp_path / "cartucho-falso.zip"
    with zipfile.ZipFile(falso, "w") as zf:
        zf.writestr("otro.txt", "x")
    with pytest.raises(CartuchoError):
        leer_manifiesto(falso)


# ---------------------------------------------------------------------------
# Integracion: el reporte refleja el filtro de allowlist
# ---------------------------------------------------------------------------
def _xlsx_maestro(path, filas):
    """Maestro de productos del ERP en xlsx (mismas columnas que PRODUCTOS.xls)."""
    pd.DataFrame(filas).to_excel(path, index=False)
    return path


_MAESTRO = [
    {
        "CODIGO": "011019",
        "NOMBRE": "PELOTA",
        "COD_EAN": "7754807110198",
        "COD_EAN_14": "17754807110190",
        "CAN_KG_UM": "0.2",
        "LINEA": "PELOTAS",
        "GRUPO": "NACIONAL",
        "TIPO": "FUTBOL",
        "FAMILIA": "FUTBOL",
        "FLG_INACTIVO": "Unchecked",
        "FLG_DESCONTINUADO": "Unchecked",
        "PRECIO": "1.0",
    },
    {
        "CODIGO": "A9999",
        "NOMBRE": "ARCHIVO X",
        "COD_EAN": "",
        "COD_EAN_14": "",
        "CAN_KG_UM": "",
        "LINEA": "ARCHIVO",
        "GRUPO": "NACIONAL",
        "TIPO": "A4",
        "FAMILIA": "A4",
        "FLG_INACTIVO": "Unchecked",
        "FLG_DESCONTINUADO": "Checked",
        "PRECIO": "2.0",
    },
    {
        "CODIGO": "IND01",
        "NOMBRE": "PRODUCTO INDUSTRIAL",
        "COD_EAN": "",
        "COD_EAN_14": "",
        "CAN_KG_UM": "1.5",
        "LINEA": "PRODUCTOS INDUSTRIALES",
        "GRUPO": "PVC",
        "TIPO": "FILM",
        "FAMILIA": "FILM",
        "FLG_INACTIVO": "Unchecked",
        "FLG_DESCONTINUADO": "Unchecked",
        "PRECIO": "3.0",
    },
]


def test_catalogo_productos_lee_maestro_erp(tmp_path):
    from src.core.catalogo_productos import CatalogoProductos, detectar_catalogo_productos

    p = _xlsx_maestro(tmp_path / "codigos productos.xlsx", _MAESTRO)
    cat = CatalogoProductos(p)
    assert cat.cargar() is True
    prod = cat.producto("011019")
    assert prod["peso_kg"] == 0.2
    assert prod["ean13"] == "7754807110198"
    assert prod["linea_nombre"] == "PELOTAS"
    assert prod["familia_nombre"] == "FUTBOL"
    assert prod["descontinuado"] is False
    # descontinuado
    assert cat.producto("A9999")["descontinuado"] is True
    # sin peso
    assert cat.producto("A9999")["peso_kg"] == 0.0
    # deteccion por nombre
    assert detectar_catalogo_productos(tmp_path) == p


def test_catalogo_productos_ausente_degrada(tmp_path):
    from src.core.catalogo_productos import CatalogoProductos

    cat = CatalogoProductos(tmp_path / "no_existe.xls")
    assert cat.cargar() is False
    assert cat.producto("X") is None
    assert cat.unavailable is True


def test_fusion_maestro_erp_al_catalogo_unico(tmp_path):
    from src.core.cartucho import construir_catalogo
    from catalogo_import import importar_catalogo_productos

    # Catalogo unico minimo (como el del cartucho)
    destino = tmp_path / "catalogo_unico.json"
    destino.write_text(json.dumps(_CATALOGO, ensure_ascii=False), encoding="utf-8")
    p = _xlsx_maestro(tmp_path / "codigos productos.xlsx", _MAESTRO)

    base = importar_catalogo_productos(p, destino=destino, log=lambda *a: None)
    arts = base["articulos"]
    # agrega los que no estaban
    assert "IND01" in arts
    # completa peso/EAN del que ya existia
    assert arts["011019"]["peso_kg"] == 0.2
    assert arts["011019"]["ean13"] == "7754807110198"
    # marca descontinuado
    assert arts["A9999"]["descontinuado"] is True
    # resuelve la linea por nombre del maestro
    assert arts["IND01"]["linea"] == "20"
    # la taxonomia del maestro no se pierde
    assert arts["011019"]["linea"] == "01"
    # queda registrado el origen
    assert base["meta"]["productos_erp"]["archivo"] == "codigos productos.xlsx"
    # idempotente
    antes = len(arts)
    base2 = importar_catalogo_productos(p, destino=destino, log=lambda *a: None)
    assert len(base2["articulos"]) == antes


def test_ingester_enriquece_con_maestro_erp(tmp_path):
    from src.core.ingest import Ingester

    p = _xlsx_maestro(tmp_path / "codigos productos.xlsx", _MAESTRO)
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["011019", "A9999", "NOEXISTE"],
            "linea": ["", "", ""],
            "grupo": ["", "", ""],
        }
    )
    out = ing.enrich_with_catalogo_productos(df, p)
    # peso desde CAN_KG_UM
    assert float(out.loc[0, "peso_kg"]) == 0.2
    # EAN
    assert out.loc[0, "ean13"] == "7754807110198"
    # linea resuelta por nombre (via catalogo unico si esta disponible)
    assert out.loc[0, "nom_linea"] == "PELOTAS"
    # flag de descontinuado
    assert bool(out.loc[1, "producto_descontinuado"]) is True
    assert bool(out.loc[0, "producto_descontinuado"]) is False
    # un SKU fuera del maestro no rompe
    assert out.loc[2, "producto_descontinuado"] in (False, "False")


def _df_reporte(linea_industrial: bool = False):
    linea = "20" if linea_industrial else "78"
    return pd.DataFrame(
        {
            "ID_PEDIDO": ["P1"],
            "NRO_DOCUMENTO": ["D1"],
            "ID_VENDEDOR": ["178"],
            "NOM_VENDEDOR": ["MILCA REYES"],
            "COD_CLIENTE": ["10214"],
            "NOM_CLIENTE": ["CLIENTE SA"],
            "CONDICION_PAGO": ["ANTICIPO EN LETRAS"],
            "PEDIDO_ESTADO": ["APROBADO"],
            "PEDIDO_FECHA": ["15/10/2026"],
            "SKU": ["S1"],
            "NOM_ARTICULO": ["ARTICULO"],
            "linea": [linea],
            "grupo": ["01"],
            "categoria": ["VINIFAN"],
            "CAN_PEDIDO": [100],
            "CAN_DESPACHO": [40],
            "PEDIDO_IMPORTE_ARITCULO": [1000],
            "stock_api_disponible": [{"CENTRO LOGISTICO VES": 500}],
            "stock_api_121": [0],
            "un_bx": [10],
        }
    )


def test_kg_cobertura_indica_cuanto_peso_es_confiable():
    """El peso del maestro cubre ~52% de los SKUs: se mide la cobertura."""
    from src.core.analytics import PedidosAnalytics

    df = pd.DataFrame(
        {
            "ID_PEDIDO": ["P1", "P1"],
            "SKU": ["S1", "S2"],
            "linea": ["78", "78"],
            "grupo": ["01", "01"],
            "categoria": ["VINIFAN", "VINIFAN"],
            "saldo": [100.0, 100.0],
            "stock_real": [1000.0, 1000.0],
            "stock_api_121": [0, 0],
            "val_atencion": [100.0, 100.0],
            "val_pendiente": [0.0, 0.0],
            "peso_kg": [2.0, 0.0],  # el 2do SKU no tiene peso en el maestro
        }
    )
    acc = PedidosAnalytics(df).resumen_accion_pedido("ANTICIPO", 1200.0)
    assert not acc.empty
    row = acc.iloc[0]
    # 100 de 200 unidades con peso conocido -> 50%
    assert float(row["kg_cobertura"]) == 50.0
    assert bool(row["peso_estimada"]) is True
    # kg del pedido: solo las unidades con peso conocido
    assert float(row["kg_saldo"]) == 200.0


def test_categoria_se_deriva_de_la_linea():
    """La categoria comercial es funcion de la linea (0 ambiguedades)."""
    from src.core.ingest import Ingester

    ing = Ingester()
    ing._render_catalog = {
        "S1": {"linea": "78", "categoria": "VINIFAN", "nombre_catalogo": "X"},
        "S2": {"linea": "01", "categoria": "VINIBALL", "nombre_catalogo": "Y"},
    }
    df = pd.DataFrame(
        {
            "SKU": ["S1", "S2", "S3"],
            "linea": ["78", "01", "99"],
            "categoria": [float("nan"), float("nan"), float("nan")],
        }
    )
    out = ing.enrich_categorias_por_linea(df)
    assert out.loc[0, "categoria"] == "VINIFAN"
    assert out.loc[1, "categoria"] == "VINIBALL"
    # linea sin categoria definida (99) -> se queda vacio
    assert pd.isna(out.loc[2, "categoria"]) or str(out.loc[2, "categoria"]).strip() == ""
    # no pisa una categoria ya presente
    df2 = pd.DataFrame(
        {
            "SKU": ["S1"],
            "linea": ["78"],
            "categoria": ["OTRA"],
        }
    )
    out2 = ing.enrich_categorias_por_linea(df2)
    assert out2.loc[0, "categoria"] == "OTRA"


def test_detect_unmatched_trata_nan_como_sin_catalogo():
    """Regresion: bool(NaN) es True -> el flag 'sin_catalogo' nunca se activaba."""
    from src.core.ingest import Ingester

    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["S1", "S2"],
            "NOM_ARTICULO": ["A", "B"],
            "categoria": [float("nan"), "VINIFAN"],
            "sin_stock_api": [True, False],
        }
    )
    inc = ing.detect_unmatched(df)
    # detect_unmatched devuelve solo los problematicos (S2 esta completo)
    assert list(inc["SKU"]) == ["S1"]
    assert bool(inc.iloc[0]["sin_catalogo"]) is True
    # el filtro de la UI (mismo criterio) tambien debe encontrarlo
    vacio = df["categoria"].isna() | df["categoria"].astype(str).str.strip().isin(["", "nan"])
    assert list(df[vacio]["SKU"]) == ["S1"]


def test_normalizar_lineas_deja_siempre_el_codigo(catalogo):
    """La columna 'linea' debe quedar siempre en codigo canonico.

    Antes mezclaba codigos (de Render) con nombres (del catalogo local):
    la misma linea aparecia como "01" en un pedido y "PELOTAS" en otro.
    """
    from src.core.ingest import Ingester

    ing = Ingester()
    ing._catalogo_unico = catalogo
    df = pd.DataFrame(
        {
            "SKU": ["S1", "S2", "S3"],
            # S1: llega como nombre | S2: llega como codigo | S3: linea vacia
            "linea": ["ARCHIVO", "78", ""],
            "grupo": ["01", "01", "01"],
        }
    )
    out = ing.normalizar_lineas(df)
    # S3 venia con linea vacia -> se atribuye por el grupo ("01" = PELOTAS)
    assert list(out["linea"]) == ["78", "78", "01"]
    assert out.loc[0, "linea_nombre"] == "ARCHIVO"
    assert out.loc[1, "linea_nombre"] == "ARCHIVO"
    assert out.loc[2, "linea_nombre"] == "PELOTAS"
    # origen: el que llego como nombre queda como ALIAS, el codigo como CODIGO
    assert out.loc[0, "origen_linea"] == "ALIAS"
    assert out.loc[1, "origen_linea"] == "CODIGO"
    assert out.loc[2, "origen_linea"] == "VACIA"
    assert list(out["linea_cod"]) == ["78", "78", "01"]


def test_normalizar_lineas_no_confunde_codigo_con_nombre(catalogo):
    """Regresion: 'CA' es un CODIGO de linea, no un nombre.

    Render cambia la linea de 'CA' a '77'; el nombre debe seguir siendo el de
    la linea final (PINTURA), no el codigo original.
    """
    from src.core.ingest import Ingester

    ing = Ingester()
    ing._catalogo_unico = catalogo
    df = pd.DataFrame(
        {
            "SKU": ["CA008"],
            "linea": ["77"],  # lo que dejo Render
            "_linea_pre": ["CA"],  # el valor original (un codigo, no un nombre)
            "_linea_de_render": [True],
            "grupo": ["01"],
        }
    )
    out = ing.normalizar_lineas(df)
    assert out.loc[0, "linea"] == "77"
    assert out.loc[0, "linea_nombre"] == "PINTURA"  # no "CA"
    assert out.loc[0, "origen_linea"] == "RENDER"


def test_reporte_reporta_lo_descartado_por_allowlist(tmp_path):
    """Lo que el filtro descarta queda en SANEAMIENTO (nada en silencio)."""
    from openpyxl import load_workbook

    from src.core.exporters import export_reporte_acciones
    from src.core.ingest import Ingester

    ing = Ingester(lineas_validas=["78"])
    df = ing.compute_derived(_df_reporte(linea_industrial=True))
    df, rechazados, resumen = ing.aplicar_allowlist(df, ["78"])

    assert len(df) == 0
    assert len(rechazados) == 1
    assert resumen["filas_rechazadas"] == 1
    assert resumen["motivos"] == {MOTIVO_FUERA: 1}

    out = export_reporte_acciones(
        df,
        familia="ANTICIPO",
        output_path=str(tmp_path / "r.xlsx"),
        guardar_foto=False,
        allowlist_rechazados=rechazados,
        allowlist_resumen=resumen,
    )
    wb = load_workbook(out)
    san = wb["SANEAMIENTO"]
    filas = list(san.iter_rows(min_row=3, values_only=True))
    tipos = [f[0] for f in filas if f and f[0]]
    assert "FUERA_DE_ALLOWLIST" in tipos
    # el PANEL reporta el descarte
    panel = " ".join(str(c.value) for r in wb["PANEL"].iter_rows(max_col=2) for c in r if c.value)
    assert "Allowlist" in panel
