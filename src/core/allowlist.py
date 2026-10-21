"""
Filtro estricto por allowlist de lineas de producto.

Regla operativa: solo pasa lo que pertenece a una linea autorizada. Todo lo
demas se descarta en memoria y queda registrado para auditoria (hoja
SANEAMIENTO, tipo=FUERA_DE_ALLOWLIST) — nada se pierde en silencio.

Resolucion de la linea (estricta, en este orden):
    1. codigo del valor crudo ("0178 - ARCHIVO" -> "78", "20" -> "20")
    2. maestro por nombre ("ARCHIVO" -> "78")

REGLA ESTRICTA: solo cuenta la linea. El grupo NO rescata (una linea
industrial con grupo valido se rechaza igual) y una linea vacia se rechaza
(los "codigos vacios" quedan fuera del embudo).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.config.settings import LINEAS_VALIDAS_DEFAULT
from src.core.lineas import linea_sufijo, resolver_codigo_linea

# Motivos de rechazo (van a la columna motivo_rechazo y a SANEAMIENTO).
MOTIVO_FUERA = "LINEA_FUERA_DE_ALLOWLIST"
MOTIVO_SIN_LINEA = "SIN_LINEA_RESOLUBLE"
MOTIVO_LINEA_VACIA = "LINEA_VACIA"


def cargar_allowlist(desde: str | None = None) -> list[str]:
    """Resuelve la allowlist activa.

    - `desde` = path a un .json -> {"allowlist": [...]} o una lista JSON.
    - `desde` = "01,02,MA" -> lista separada por comas.
    - `desde` = None -> allowlist del catalogo unico (cartucho); si no hay
      catalogo, LINEAS_VALIDAS_DEFAULT.
    """
    if desde:
        texto = str(desde).strip()
        p = Path(texto)
        if p.suffix.lower() == ".json" and p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"allowlist ilegible ({p}): {exc}") from exc
            cruda = data.get("allowlist") if isinstance(data, dict) else data
            vals = [str(v).strip().upper() for v in (cruda or []) if str(v).strip()]
            if vals:
                return sorted(set(vals))
            raise ValueError(f"la allowlist de {p} esta vacia")
        if p.suffix.lower() == ".json":
            raise ValueError(f"no existe el archivo de allowlist: {p}")
        vals = [v.strip().upper() for v in texto.split(",") if v.strip()]
        if vals:
            return sorted(set(vals))
        raise ValueError(f"allowlist invalida: {desde!r}")

    from src.core.catalogo_unico import get_catalogo

    cat = get_catalogo()
    if cat.cargar():
        return sorted(set(cat.allowlist))
    return sorted(set(LINEAS_VALIDAS_DEFAULT))


def codigo_linea(valor: str | None, name_to_code: dict | None = None) -> str:
    """Codigo de linea deducido de un valor crudo ("" si no se puede).

    Orden: codigo parseable ("0178 - ARCHIVO" -> "78", "20" -> "20") ->
    maestro por nombre ("ARCHIVO" -> "78") -> semilla estatica.

    Un NOMBRE ambiguo ("ACCESORIOS" = 79 y CD) no resuelve por si solo: el
    codigo explicito siempre manda y un nombre compartido atribuiria el SKU
    a la linea equivocada.
    """
    if not valor:
        return ""
    txt = str(valor).strip().upper()
    from src.config.settings import LINEA_NOMBRES_AMBIGUOS

    if txt in {str(n).strip().upper() for n in LINEA_NOMBRES_AMBIGUOS}:
        # Nombre ambiguo: no resolver sin codigo explicito.
        return ""
    from src.core.catalogo_unico import get_catalogo

    cat = get_catalogo()
    loaded = cat.cargar()
    lineas = cat.lineas if loaded else {}

    # 1. resolver codigo; pero si el resultado no esta en el maestro,
    #    no lo devolvemos (p.ej. "011019" -> "1019" que no existe).
    cod = resolver_codigo_linea(txt)
    if cod and cod in lineas:
        return cod
    # 2. alias exacto por nombre: "ARCHIVO" -> "78".
    alias = cat.alias_linea
    if txt in alias and txt not in {str(n).strip().upper() for n in LINEA_NOMBRES_AMBIGUOS}:
        return alias[txt]
    # 3. prefijo de 2 chars: "CA001" -> "CA", "011019" -> "01", "78698" -> "78".
    #    Solo aplica cuando:
    #    - El valor empieza con 'C' (Crayola, sin ambiguedad)
    #    - O el resolver devolvio algo que NO esta en el maestro
    #      (ej: "011019" -> "1019" que no existe; prefijo "01" SI existe)
    #    - O el resolver devolvio vacio y el sufijo tampoco existe
    #      (ej: "78698" -> resolver da ""; sufijo "98" SI existe en maestro
    #       PERO el prefijo "78" TAMBIEN existe y es el correcto)
    #    NO aplica para "99ZZ": resolver da "" y sufijo "ZZ" no existe,
    #    pero el prefijo "99" SI existe en maestro. Ahi el valor es invalido.
    #    Regla: prefijo SOLO si el valor es todo digitos (SKU numerico).
    if len(txt) >= 3 and loaded:
        pref = txt[:2].upper()
        if pref in lineas:
            if txt.startswith("C"):
                return pref
            if txt.isdigit():
                # SKU numerico puro: prefijo siempre gana (ej: 78698->78, 011019->01)
                return pref
            if cod and cod not in lineas:
                # Resolver dio resultado invalido: usar prefijo (ej: CA087)
                return pref
    # 4. sufijo de 2 chars
    from src.core.lineas import linea_sufijo

    suf = linea_sufijo(txt)
    if suf and suf in lineas:
        return suf
    if name_to_code:
        cod = str(name_to_code.get(txt, "") or "").upper()
        if cod:
            return cod
    return ""


def codigo_y_validez(
    linea: str | None,
    grupo: str | None = None,
    permitidos=None,
    name_to_code: dict | None = None,
) -> tuple[str, bool]:
    """Codigo de la linea y si esta autorizada ("" y False si no se puede).

    REGLA ESTRICTA: solo cuenta la LINEA. El grupo no rescata (una linea
    industrial con grupo valido se rechaza igual) y una linea vacia se
    rechaza (los "codigos vacios" quedan fuera del embudo).
    """
    permitidos = set(permitidos or LINEAS_VALIDAS_DEFAULT)
    cod = codigo_linea(linea, name_to_code)
    return cod, bool(cod and cod in permitidos)


def aplicar_allowlist(
    df: pd.DataFrame,
    allowlist: list[str] | None = None,
    resolver=None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Separa el df en (aceptados, rechazados, resumen).

    Aceptados: filas cuya linea resuelve a un codigo de la allowlist.
    Rechazados: filas fuera de la allowlist, sin linea o con linea vacia.
    """
    permitidos = set(allowlist or LINEAS_VALIDAS_DEFAULT)
    resolver = resolver or codigo_linea

    if df is None or len(df) == 0:
        return (
            (df if df is not None else pd.DataFrame()),
            pd.DataFrame(),
            {
                "filas_total": 0,
                "filas_aceptadas": 0,
                "filas_rechazadas": 0,
                "motivos": {},
                "allowlist": sorted(permitidos),
                "pedidos_rechazados": 0,
            },
        )

    trabajo = df.copy()
    codigos: list[str] = []
    for _, r in trabajo.iterrows():
        # REGLA ESTRICTA: solo la linea decide (el grupo no rescata).
        codigos.append(resolver(r.get("linea", "")) or "")

    trabajo["_cod_linea"] = codigos
    trabajo["_linea_cruda"] = trabajo.get("linea", pd.Series("", index=trabajo.index)).astype(str)

    valida = trabajo["_cod_linea"].isin(permitidos)
    sin_codigo = trabajo["_cod_linea"].eq("")
    vacia = trabajo["_linea_cruda"].str.strip().eq("")

    trabajo["motivo_rechazo"] = ""
    trabajo.loc[~valida & sin_codigo & vacia, "motivo_rechazo"] = MOTIVO_LINEA_VACIA
    trabajo.loc[~valida & sin_codigo & ~vacia, "motivo_rechazo"] = MOTIVO_SIN_LINEA
    trabajo.loc[~valida & ~sin_codigo, "motivo_rechazo"] = MOTIVO_FUERA

    aceptados = trabajo[valida].drop(columns=["_cod_linea", "_linea_cruda"])
    rechazados = trabajo[~valida].drop(columns=["_cod_linea", "_linea_cruda"])

    motivos = rechazados["motivo_rechazo"].value_counts().to_dict() if len(rechazados) else {}
    resumen = {
        "filas_total": int(len(trabajo)),
        "filas_aceptadas": int(len(aceptados)),
        "filas_rechazadas": int(len(rechazados)),
        "motivos": {str(k): int(v) for k, v in motivos.items()},
        "allowlist": sorted(permitidos),
        "pedidos_rechazados": int(
            rechazados["ID_PEDIDO"].nunique()
            if len(rechazados) and "ID_PEDIDO" in rechazados.columns
            else 0
        ),
    }
    return aceptados, rechazados, resumen
