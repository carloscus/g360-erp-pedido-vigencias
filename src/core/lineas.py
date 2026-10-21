"""
Reglas compartidas de linea de producto y normalizacion de nombres.

Vive aparte para que el catalogo unico y el pipeline de ingesta usen EXACTAMENTE
la misma logica (una sola fuente de verdad para elMatching de lineas).
"""

from __future__ import annotations

import re

# Valores que representan "sin dato" en las exports del ERP.
_VACIOS = ("", "NAN", "NONE", "NAT")

# Formas juridicas finales que se ignoran al comparar nombres de cliente.
_RE_FORMA_JURIDICA = re.compile(
    r"[,\s]*(?:"
    r"S\.?\s?A\.?\s?C?\.?"
    r"|E\.?\s?I\.?\s?R\.?\s?L?\.?"
    r"|S\.?\s?R\.?\s?L?\.?"
    r")\s*$",
    re.IGNORECASE,
)


def linea_sufijo(val) -> str:
    """Sufijo de 2 chars para match de linea valida: 0101 -> 01, 01MA -> MA."""
    txt = str(val or "").strip().upper()
    if txt in _VACIOS:
        return ""
    return txt[-2:]


def resolver_codigo_linea(val, name_to_code=None) -> str:
    """Resuelve el codigo corto (2 chars) de una linea desde cualquier formato.

    Acepta codigos puros ('0101' -> '01', '01MA' -> 'MA', 'MA' -> 'MA'),
    formatos con nombre ('0178 - ARCHIVO' -> '78', '01 - PELOTAS' -> '01',
    '01AD - ACCESORIOS' -> 'AD') y nombres de linea ('PELOTAS') resueltos
    contra `name_to_code` (mapa del reporte + catalogo + semilla estatica).
    """
    txt = str(val or "").strip().upper()
    if txt in _VACIOS:
        return ""
    if "-" in txt:
        head = txt.split("-")[0].strip()
        if len(head) == 2:
            return head
        if re.fullmatch(r"01[0-9A-Z]+", head):
            return head[2:]
        return ""
    if re.fullmatch(r"[0-9A-Z]{2}", txt):
        return txt
    if re.fullmatch(r"01[0-9A-Z]+", txt):
        return txt[2:]
    if name_to_code:
        return str(name_to_code.get(txt, "") or "").upper()
    return ""


def normalizar_nombre(nombre: str | None) -> str:
    """Normaliza un nombre de cliente para comparar ERP vs maestro.

    Mayusculas, sin acentos, sin puntuacion ni formas juridicas finales
    (S.A. / S.A.C. / E.I.R.L. / S.R.L.).
    """
    if not nombre:
        return ""
    txt = str(nombre).upper().strip()
    txt = _RE_FORMA_JURIDICA.sub("", txt)
    for a, b in (
        ("Á", "A"),
        ("É", "E"),
        ("Í", "I"),
        ("Ó", "O"),
        ("Ú", "U"),
        ("Ü", "U"),
        ("Ñ", "N"),
    ):
        txt = txt.replace(a, b)
    txt = "".join(c if c.isalnum() or c.isspace() else " " for c in txt)
    return " ".join(txt.split())
