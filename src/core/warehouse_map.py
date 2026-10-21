"""
Mapeo de almacenes ERP -> API G360.

El ERP exporta nombres como "CENTRO LOGISTICO VES", "CLVES CIPTECH", etc.
La API usa codigos estables: "VES", "40", "129", "121", etc.

Este modulo define el mapeo por defecto y permite configuracion adicional.
"""

from __future__ import annotations

# Mapeo base: nombre ERP (NOM_ALMACEN) -> codigo API
_MAPA_ALMACENES: dict[str, str] = {
    "CENTRO LOGISTICO VES": "VES",
    "CLVES CIPTECH": "40",
    " CIPTECH": "129",
    "PROD. TERMINADOS": "121",
}

# Codigos de almacenes que deben incluirse en el reporte por defecto
ALMACENES_VENTA_POR_DEFECTO: list[str] = ["VES", "40", "129", "121"]

# Roles operativos de cada almacen
ROLES_ALMACEN: dict[str, str] = {
    "VES": "principal",
    "121": "liberacion",
    "40": "apoyo",
    "129": "apoyo",
}


def obtener_codigo_almacen(
    nom_almacen_erp: str | None,
    mapa_personalizado: dict[str, str] | None = None,
) -> str | None:
    """Convierte un nombre de almacén ERP a su código API.

    Args:
        nom_almacen_erp: Valor de la columna NOM_ALMACEN del ERP.
        mapa_personalizado: Mapeo adicional del usuario.

    Returns:
        Código del almacén en el API o None si no se encuentra.
    """
    if nom_almacen_erp is None:
        return None

    nom = str(nom_almacen_erp).strip()

    if mapa_personalizado:
        for key, code in mapa_personalizado.items():
            if key.strip().lower() == nom.lower():
                return code

    return _MAPA_ALMACENES.get(nom)


def obtener_almacenes_vigentes() -> list[str]:
    """Retorna los codigos de almacenes de venta por defecto."""
    return ALMACENES_VENTA_POR_DEFECTO[:]


def validar_mapeo(df_erp) -> dict[str, str]:
    """Retorna los nombres ERP que no tienen mapeo definido.

    Args:
        df_erp: DataFrame ERP cargado.

    Returns:
        Dict con los NOM_ALMACEN únicos que no están en el mapeo.
    """
    if "NOM_ALMACEN" not in df_erp.columns:
        return {}

    nombres_erp = df_erp["NOM_ALMACEN"].dropna().unique().tolist()
    sin_mapeo = []

    for nom in nombres_erp:
        if obtener_codigo_almacen(nom) is None:
            sin_mapeo.append(str(nom).strip())

    return {nom: "SIN_MAPEO" for nom in sorted(set(sin_mapeo))}
