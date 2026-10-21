"""
Fusiona el maestro de productos del ERP (PRODUCTOS.xls) al catalogo unico.

El cartucho (DB de ventas) y el maestro de productos del ERP son fuentes
distintas y complementarias:

    cartucho      -> lineas (53), alias nombre->codigo, clientes, vendedores
    PRODUCTOS.xls -> peso_kg (CAN_KG_UM), EAN, taxonomia por nombre, flags de
                     descontinuado (3.449 SKUs con peso vs 1.171 en Render)

La fusion deja `.cache/catalogo_unico.json` como maestro autocontenido: el
reporte no depende de tener el archivo del ERP a mano.

Uso:
    python catalogo_import.py                          # busca en el escritorio
    python catalogo_import.py --productos "C:\\...\\codigos productos.xls"
    python catalogo_import.py --fuerzar
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.core.catalogo_productos import CatalogoProductos, detectar_catalogo_productos
from src.core.catalogo_unico import CATALOGO_UNICO_PATH, CatalogoUnico


def importar_catalogo_productos(
    path: str | Path,
    destino: str | Path | None = None,
    forzar: bool = False,
    log=print,
) -> dict:
    """Fusiona el maestro de productos del ERP en el catalogo unico.

    Idempotente: vuelve a fusionar sin duplicar. Solo agrega o completa
    datos; nunca pisa la taxonomia del cartucho.
    """
    destino = Path(destino or CATALOGO_UNICO_PATH)
    cat = CatalogoProductos(Path(path))
    if not cat.cargar():
        raise FileNotFoundError(cat.error_msg or f"no existe: {path}")

    if destino.exists():
        base = json.loads(destino.read_text(encoding="utf-8"))
    else:
        base = {
            "meta": {},
            "lineas": {},
            "alias_linea": {},
            "articulos": {},
            "alias_sku": {},
            "vendedores": {},
            "clientes": {},
            "alias_cliente": {},
        }
    base.setdefault("articulos", {})
    base.setdefault("meta", {})

    # Resolucion nombre->codigo con el maestro ya cargado.
    uni = CatalogoUnico(destino)
    uni.cargar()

    agregados = 0
    actualizados = 0
    con_peso = 0
    descontinuados = 0
    for sku, p in cat.productos.items():
        art = base["articulos"].get(sku)
        nuevo = art is None
        if nuevo:
            art = {"id_articulo": sku}
            base["articulos"][sku] = art
            agregados += 1
        else:
            actualizados += 1

        cod = uni.codigo_linea(p.get("linea_nombre") or "") if p.get("linea_nombre") else ""
        if cod and not art.get("linea"):
            art["linea"] = cod
        if p.get("linea_nombre") and not art.get("linea_nombre"):
            art["linea_nombre"] = p["linea_nombre"]
        if p.get("grupo_nombre") and not art.get("grupo_nombre"):
            art["grupo_nombre"] = p["grupo_nombre"]
        if p.get("familia_nombre") and not art.get("familia_nombre"):
            art["familia_nombre"] = p["familia_nombre"]
        if p.get("nombre") and not art.get("nombre"):
            art["nombre"] = p["nombre"]
        if p.get("peso_kg"):
            art["peso_kg"] = p["peso_kg"]
            con_peso += 1
        if p.get("ean13") and not art.get("ean13"):
            art["ean13"] = p["ean13"]
        if p.get("ean14") and not art.get("ean14"):
            art["ean14"] = p["ean14"]
        if p.get("descontinuado"):
            art["descontinuado"] = True
            descontinuados += 1
        if p.get("inactivo"):
            art["inactivo"] = True

    base["meta"]["productos_erp"] = {
        "archivo": cat.origen,
        "importado_en": datetime.now().isoformat(timespec="seconds"),
        "articulos": len(cat.productos),
        "agregados": agregados,
        "actualizados": actualizados,
        "con_peso": con_peso,
        "descontinuados": descontinuados,
    }
    base.setdefault("conteos", {})
    base["conteos"]["articulos"] = len(base["articulos"])
    base["conteos"]["articulos_con_peso"] = sum(
        1 for a in base["articulos"].values() if float(a.get("peso_kg") or 0) > 0
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    kb = destino.stat().st_size / 1024
    log(f"[catalogo] Maestro ERP fusionado: {cat.origen}")
    log(
        f"[catalogo] articulos={len(cat.productos)} "
        f"(nuevos={agregados}, actualizados={actualizados}) | peso={con_peso} "
        f"| descontinuados={descontinuados}"
    )
    log(
        f"[catalogo] Catalogo unico: {destino} ({kb:.0f} KB) | "
        f"articulos totales={len(base['articulos'])}"
    )
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fusiona el maestro de productos del ERP al catalogo unico.",
    )
    parser.add_argument("--productos", help="Ruta de PRODUCTOS.xls (opcional: escritorio)")
    parser.add_argument("--salida", help="Ruta del catalogo unico (default: .cache)")
    parser.add_argument("--fuerzar", action="store_true", help="Re-fusiona aunque no cambie")
    args = parser.parse_args(argv)

    if args.productos:
        ruta = Path(args.productos)
    else:
        from reporte import escritorio

        ruta = detectar_catalogo_productos(escritorio())
    if ruta is None or not Path(ruta).exists():
        print("[ERROR] No encontre el maestro de productos del ERP.")
        print("        Pasa la ruta con --productos o dejalo en el escritorio.")
        return 2

    destino = Path(args.salida) if args.salida else CATALOGO_UNICO_PATH
    try:
        importar_catalogo_productos(ruta, destino=destino, forzar=args.fuerzar)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
