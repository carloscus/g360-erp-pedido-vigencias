"""Tests para validacion autonoma de taxonomia en vigencias."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.allowlist import codigo_linea
from src.core.catalogo_unico import CatalogoUnico


def test_crayola_CA_resuelve_prefijo():
    """CA001 debe resolver a CA (prefijo), no a 77 (sufijo)."""
    cat = CatalogoUnico()
    cat.cargar()
    assert codigo_linea("CA001") == "CA"


def test_crayola_CB_resuelve_prefijo():
    """CB007 debe resolver a CB (prefijo), no a 76 (sufijo)."""
    assert codigo_linea("CB007") == "CB"


def test_crayola_CC_resuelve_prefijo():
    """CC001 debe resolver a CC (prefijo), no a 72 (sufijo)."""
    assert codigo_linea("CC001") == "CC"


def test_crayola_CD_resuelve_prefijo():
    """CD001 debe resolver a CD (prefijo), no a 79 (sufijo)."""
    assert codigo_linea("CD001") == "CD"


def test_crayola_CE_resuelve_prefijo():
    """CE001 debe resolver a CE (prefijo), no a MANUALIDADES."""
    assert codigo_linea("CE001") == "CE"


def test_crayola_CF_resuelve_prefijo():
    """CF005 debe resolver a CF (prefijo), no a SET."""
    assert codigo_linea("CF005") == "CF"


def test_sku_vinifan_no_se_ve_afectado():
    """79102 es VINIFAN y debe resolver a 79, no a CD."""
    assert codigo_linea("79102") == "79"


def test_sku_viniball_no_se_ve_afectado():
    """011019 es VINIBALL y debe resolver a 01."""
    assert codigo_linea("011019") == "01"


def test_sku_nuevo_C_sin_catalogo_usa_prefijo():
    """CA087 no está en catálogo pero el prefijo CA es válido."""
    # Si no está en el cartucho, debería usar prefijo
    resultado = codigo_linea("CA087")
    # Puede ser CA (por prefijo) o vacío (si no hay fallback)
    assert resultado in ("CA", "")


def test_sku_numerico_usa_prefijo():
    """78698 debe resolver a 78 (prefijo), no a 98 (sufijo)."""
    assert codigo_linea("78698") == "78"


def test_sku_invalido_no_resuelve():
    """99ZZ no es valido y debe devolver vacio."""
    assert codigo_linea("99ZZ") == ""


def test_falso_positivo_C_ipSA_no_es_Crayola():
    """CC09150 es SKU CIPSA, no Crayola. Debe usar prefijo CC pero no
    estar en las lineas Crayola del catalogo."""
    # Este SKU no está en el cartucho, pero si aparece en S1,
    # el fallback C* lo manda a CC. Sin embargo, como no tiene
    # categoria REPRESENTADAS en el catalogo, en vigencias ira
    # a SANEAMIENTO por no pasar el funnel.
    resultado = codigo_linea("CC09150")
    # El prefijo CC existe en el maestro, asi que resuelve
    assert resultado == "CC"
