"""Tests de la resolucion de linea cuando dos lineas comparten NOMBRE.

En el maestro hay dos lineas con el mismo nombre: la 79 (ACCESORIOS /
TIJERAS / LIMPIATIPO) y la CD (ACCESORIOS / PINCELES Crayola). El catalogo
unico indexa por nombre, asi que resolver el codigo de linea por el NOMBRE
atribuia los SKUs de la 79 a la CD (y mezclaba los pedidos con la linea "CD").

Regla: el CODIGO de linea (linea_id del catalogo) manda sobre el nombre, y un
nombre AMBIGUO (dos lineas distintas) no resuelve codigo por si solo.
"""

import pandas as pd

from src.core.ingest import Ingester


def _item(sku, linea_id, linea, grupo="02 - TIJERAS"):
    """Item con la forma que publica el API de stock (/stock?search=)."""
    return {
        "sku": sku,
        "linea_id": linea_id,
        "linea": linea,
        "grupo": grupo,
        "categoria": "VINIFAN",
        "estado_linea": "NUEVO",
    }


def test_el_codigo_de_linea_manda_sobre_el_nombre():
    """linea_id='79' con linea='ACCESORIOS' no debe caer en la linea CD."""
    cat = {"79026": Ingester._catalog_from_item(_item("79026", "79", "ACCESORIOS"))}
    assert cat["79026"]["linea_id"] == "79"
    assert cat["79026"]["linea"] == "79"
    # el nombre de la linea 79 es ACCESORIOS, no el codigo CD
    assert cat["79026"]["linea_nombre"] == "ACCESORIOS"


def test_linea_id_cd_conserva_su_codigo():
    """La linea CD tambien comparte nombre: su codigo no puede perderse."""
    cat = {"79165": Ingester._catalog_from_item(_item("79165", "CD", "ACCESORIOS"))}
    assert cat["79165"]["linea_id"] == "CD"
    assert cat["79165"]["linea"] == "CD"


def test_el_nombre_de_linea_no_puede_ser_un_codigo():
    """Si el catalogo no expone nombre, no se guarda el codigo como nombre."""
    cat = {"79026": Ingester._catalog_from_item(_item("79026", "79", "79"))}
    assert cat["79026"]["linea_nombre"] == ""
    assert cat["79026"]["linea_id"] == "79"


def test_normalizar_lineas_no_re_resuelve_por_nombre():
    """El nombre de una linea no debe re-resolver el codigo de la propia linea.

    Reproduce el bug: `linea` venia correcta ("79") y `linea_nombre` =
    "ACCESORIOS"; al re-resolver por nombre, el catalogo unico devolvia "CD".
    """
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["79026"],
            "linea": ["79"],
            "linea_nombre": ["ACCESORIOS"],
            "_linea_pre": ["ACCESORIOS"],
            "_linea_de_render": [True],
        }
    )
    out = ing.normalizar_lineas(df)
    assert str(out.loc[0, "linea"]) == "79"
    assert str(out.loc[0, "linea_nombre"]) == "ACCESORIOS"


def test_apply_render_catalog_escribe_el_nombre_de_la_linea():
    """Render sobrescribe `linea`; el nombre debe seguir a la linea elegida."""
    ing = Ingester()
    df = pd.DataFrame(
        {
            "SKU": ["79026"],
            "linea": ["77"],  # catalogo local previo (equivocado)
            "linea_nombre": ["PINTURA"],
        }
    )
    catalog = {"79026": Ingester._catalog_from_item(_item("79026", "79", "ACCESORIOS"))}
    out = ing._apply_render_catalog(df, catalog)
    assert str(out.loc[0, "linea"]) == "79"
    assert str(out.loc[0, "linea_nombre"]) == "ACCESORIOS"


# --- Blindaje contra el nombre AMBIGUO "ACCESORIOS" --------------------------
# El nombre "ACCESORIOS" designa a DOS lineas: 79 (tijeras, limpiatipo) y CD
# (pinceles Crayola). Ningun nombre ambiguo puede resolver un codigo por si
# solo, o los SKUs de una linea se atribuyen a la otra.


def test_build_alias_descarta_nombre_ambiguo():
    """Un nombre que apunta a dos codigos no se mapea (ni depende del orden)."""
    cat = {
        "79026": {"linea": "79", "linea_nombre": "ACCESORIOS", "linea_id": "79"},
        "CD001": {"linea": "CD", "linea_nombre": "ACCESORIOS", "linea_id": "CD"},
    }
    alias = Ingester._build_alias(cat)
    assert "ACCESORIOS" not in alias, f"nombre ambiguo no debe mapear: {alias}"

    # El resultado tiene que ser el MISMO sin importar el orden de las claves.
    cat_rev = dict(reversed(list(cat.items())))
    assert Ingester._build_alias(cat_rev) == alias


def test_build_alias_conserva_nombres_no_ambiguos():
    """Un nombre con un solo codigo si se mapea."""
    cat = {
        "01001": {"linea": "01", "linea_nombre": "PELOTAS"},
        "78001": {"linea": "78", "linea_nombre": "ARCHIVO"},
    }
    alias = Ingester._build_alias(cat)
    assert alias == {"PELOTAS": "01", "ARCHIVO": "78"}


def test_nombre_ambiguo_no_resuelve_codigo():
    """`codigo_linea('ACCESORIOS')` no debe devolver 79 ni CD."""
    from src.core.allowlist import codigo_linea

    assert codigo_linea("ACCESORIOS") == ""
    assert codigo_linea("ACCESORIOS", {"ACCESORIOS": "79"}) == ""
    assert codigo_linea("ACCESORIOS", {"ACCESORIOS": "CD"}) == ""
    # Pero con su codigo explicito si resuelve.
    assert codigo_linea("0179 - ACCESORIOS") == "79"
    assert codigo_linea("01CD - ACCESORIOS") == "CD"
    assert codigo_linea("79") == "79"
    assert codigo_linea("CD") == "CD"


def test_nombre_a_codigo_excluye_ambiguos():
    """El mapa nombre->codigo no debe traer el nombre ambiguo de la semilla."""
    ing = Ingester()
    df = pd.DataFrame({"linea": ["79", "CD"]})
    mapa = ing._nombre_a_codigo(df)
    assert "ACCESORIOS" not in mapa
    assert mapa.get("PELOTAS") == "01"  # los no ambiguos siguen


def test_catalogo_unico_codigo_linea_ignora_ambiguo():
    """El alias del cartucho tampoco debe resolver un nombre ambiguo."""
    from src.core.catalogo_unico import CatalogoUnico

    cu = CatalogoUnico.__new__(CatalogoUnico)
    cu._data = {
        "lineas": {"79": {"nombre": "ACCESORIOS"}, "CD": {"nombre": "ACCESORIOS"}},
        "alias_linea": {"ACCESORIOS": "79", "PELOTAS": "01"},
        "allowlist": ["79", "CD", "01"],
    }
    assert cu.codigo_linea("ACCESORIOS") == ""
    assert cu.codigo_linea("PELOTAS") == "01"
    assert cu.codigo_linea("01CD - ACCESORIOS") == "CD"
    assert cu.codigo_linea("0179 - ACCESORIOS") == "79"


def test_tijeras_y_crayola_no_se_mezclan():
    """Caso real: tijera 79 y pincel CD comparten nombre y deben separarse."""
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
    assert str(out.loc[0, "linea"]) == "79", "la tijera debe seguir en 79"
    assert str(out.loc[1, "linea"]) == "CD", "el pincel Crayola debe seguir en CD"
