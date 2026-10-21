"""
CLI de reporte de acciones (sin interfaz grafica).

Lee el reporte de vigencias del ERP (xls/xlsx), lo enriquece con el catalogo y
el stock del API G360 (Render), y genera el libro de accion en el escritorio.

Uso:
    python reporte.py                          # auto-detecta el archivo mas reciente
    python reporte.py --familia CONTADO
    python reporte.py --linea 78 --categoria VINIFAN --dias 30
    python reporte.py --fuente "C:\\...\\vig.xls" --salida "C:\\...\\salida.xlsx"

Rutas por defecto:
    entrada  = el .xls/.xlsx mas reciente del escritorio con la firma del ERP
    salida   = escritorio/reaccion_<familia>_<AAAA-MM-DD>.xlsx
    cache    = .cache/ (fotos, stock, configuracion) — nunca se escribe en el escritorio

El interprete debe ser el del entorno del proyecto (uv/venv). El lanzador
`generar_reporte.vbs` apunta explicitamente a ese entorno para no depender
del `python` del PATH.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Firmas minimas para reconocer un archivo del ERP entre otros del escritorio.
_ERP_REQUIRED = (
    "ID_VENDEDOR",
    "ID_PEDIDO",
    "ID_ARTICULO",
    "CAN_PEDIDO",
    "CAN_DESPACHO",
    "PEDIDO_IMPORTE_ARITCULO",
)
_FAMILIAS = ["ANTICIPO", "CONTADO", "CANJE", "LETRA", "FACTURA"]


def escritorio() -> Path:
    """Carpeta del escritorio, tolerante a OneDrive."""
    from src.core.rutas import escritorio as _escritorio

    return _escritorio()


def detectar_fuente(carpeta: Path) -> Path | None:
    """El .xls/.xlsx mas reciente con las columnas que espera el pipeline."""
    import pandas as pd

    candidatos = sorted(
        list(carpeta.glob("*.xls")) + list(carpeta.glob("*.xlsx")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidatos:
        try:
            head = pd.read_excel(path, nrows=0, dtype=str)
        except Exception:
            continue
        cols = {str(c).strip().upper() for c in head.columns}
        if all(c in cols for c in _ERP_REQUIRED):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera el reporte de acciones de vigencias (sin UI).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fuente", help="Ruta al .xls/.xlsx del ERP (opcional: auto-detecta)")
    parser.add_argument("--salida", help="Ruta de salida .xlsx (opcional: escritorio)")
    parser.add_argument(
        "--familia",
        default="ANTICIPO",
        choices=_FAMILIAS,
        help="Condicion de pago a reportar (default: ANTICIPO)",
    )
    parser.add_argument(
        "--umbral",
        type=float,
        default=1200.0,
        help="Monto minimo por pedido para ir a despacho directo",
    )
    parser.add_argument(
        "--umbral-planilla",
        type=int,
        default=10,
        help="Dias sin aprobar planilla para escalar a cobranza",
    )
    parser.add_argument(
        "--dias", type=int, default=30, help="Recorte por antiguedad del pedido en dias (0 = todo)"
    )
    parser.add_argument(
        "--linea",
        action="append",
        help="Segmento por linea de producto (repetible): 78, PELOTAS, AD...",
    )
    parser.add_argument(
        "--categoria",
        action="append",
        help="Segmento por categoria (repetible): VINIBALL, VINIFAN...",
    )
    parser.add_argument(
        "--estado",
        action="append",
        help="Segmento por estado de linea (repetible): NUEVO, IMPORTADO...",
    )
    parser.add_argument(
        "--incluir-detalle", action="store_true", help="Agrega la hoja DETALLE con formulas vivas"
    )
    parser.add_argument(
        "--por-estado",
        action="store_true",
        help=(
            "Genera 4 libros independientes (uno por estado_linea: NUEVO, "
            "IMPORTADO, TRADICIONAL, NACIONAL) desde el mismo reporte."
        ),
    )
    parser.add_argument(
        "--sin-foto", action="store_true", help="No guarda ni compara la foto del dia"
    )
    parser.add_argument(
        "--sin-stock",
        action="store_true",
        help="Usa el stock cacheado y no refresca el API de Render",
    )
    parser.add_argument(
        "--catalogo-productos",
        help=(
            "Maestro de productos del ERP (PRODUCTOS.xls / 'codigos productos.xls'). "
            "Por defecto: se busca en el escritorio."
        ),
    )
    parser.add_argument(
        "--sin-catalogo-productos",
        action="store_true",
        help="No usa el maestro de productos del ERP (peso/EAN solo de Render)",
    )
    parser.add_argument(
        "--allowlist",
        help=(
            "Allowlist de lineas (archivo .json o lista '01,02,MA'). "
            "Por defecto: la del catalogo unico (cartucho)."
        ),
    )
    parser.add_argument(
        "--sin-allowlist",
        action="store_true",
        help="No aplica el filtro estricto de lineas (deja pasar todo)",
    )
    parser.add_argument(
        "--salir-escritorio",
        action="store_true",
        help="Abre el resultado en el explorador de Windows",
    )
    args = parser.parse_args(argv)

    from src.config.settings import DATA_DIR
    from src.core.exporters import export_reporte_acciones
    from src.core.ingest import Ingester

    # --- Entrada ---
    if args.fuente:
        fuente = Path(args.fuente)
        if not fuente.exists():
            print(f"[ERROR] No existe el archivo: {fuente}")
            return 2
    else:
        fuente = detectar_fuente(escritorio())
        if fuente is None:
            print(f"[ERROR] No encontre un reporte de vigencias en {escritorio()}")
            print("        Pasa la ruta con --fuente o verifica el archivo.")
            return 2
    print(f"[1/4] Leyendo {fuente.name} ...")

    # --- Allowlist (se resuelve antes: gobierna embudo y filtro) ---
    allowlist = None
    if args.sin_allowlist:
        print("[2b/4] Filtro de allowlist: DESACTIVADO (--sin-allowlist)")
    else:
        from src.core.allowlist import cargar_allowlist

        try:
            allowlist = cargar_allowlist(args.allowlist)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return 2

    # --- Pipeline ---
    ing = Ingester(lineas_validas=allowlist)
    try:
        df = ing.load_file(str(fuente))
    except Exception as exc:
        print(f"[ERROR] No pude leer el archivo: {exc}")
        return 2
    filas = len(df)
    df = ing.enrich_with_catalog(df)
    df = ing.enrich_with_db_lines(df)
    # Maestro de productos del ERP: peso, EAN y taxonomia por nombre.
    # Va ANTES de Render: Render pisa peso/EAN donde tiene dato y conserva
    # el del ERP donde no (el peso final es la union de ambas fuentes).
    if args.sin_catalogo_productos:
        print("[1b/4] Maestro de productos del ERP: desactivado")
    else:
        from src.core.catalogo_productos import detectar_catalogo_productos

        ruta_cat = (
            Path(args.catalogo_productos)
            if args.catalogo_productos
            else detectar_catalogo_productos(escritorio())
        )
        if ruta_cat and Path(ruta_cat).exists():
            df = ing.enrich_with_catalogo_productos(df, Path(ruta_cat))
            print(f"[1b/4] Maestro de productos del ERP: {ruta_cat.name}")
        else:
            print("[1b/4] Maestro de productos del ERP: no encontrado (peso/EAN solo de Render)")
    df = ing.compute_derived(df)
    if args.sin_stock:
        # El cache local YA tiene la foto de stock por SKU/almacen: se
        # aplica y se clasifica (VES/121/otros) para no perder los traslados.
        # Antes, este camino saltaba `enrich_with_stock_api` completo y
        # `stock_api_121` quedaba en 0 -> TRASLADO_121 salia vacia.
        df = ing._apply_stock_cache(df)
        print("[2/4] Saltando refresh de stock (usa cache).")
    else:
        print("[2/4] Consultando catalogo y stock de Render (puede tardar) ...")
        df = ing.enrich_with_stock_api(df)
    estado = "offline" if ing.api_unavailable else "online"
    print(f"      Stock API: {estado} | snapshot hace {ing.cache_age_hours()} h")
    # La categoria comercial es funcion de la linea: se deriva para los SKUs
    # que el maestro de Render no cubre (asi no quedan "sin catalogo").
    df = ing.enrich_categorias_por_linea(df)
    if ing._categorias_derivadas:
        print(f"      Categoria derivada por linea: {ing._categorias_derivadas:,} filas")
    # Linea siempre en codigo canonico (el nombre queda en linea_nombre).
    df = ing.normalizar_lineas(df)

    # --- Filtro estricto de lineas (allowlist) ---
    # Se aplica DESPUES de Render (linea definitiva) y ANTES del embudo.
    # Lo descartado se reporta en SANEAMIENTO: nada se pierde en silencio.
    rechazados = None
    resumen_allowlist = None
    if allowlist is not None:
        df, rechazados, resumen_allowlist = ing.aplicar_allowlist(df, allowlist)
        print(
            f"[2b/4] Allowlist ({len(allowlist)} lineas): "
            f"{resumen_allowlist['filas_aceptadas']} filas aceptadas, "
            f"{resumen_allowlist['filas_rechazadas']} descartadas"
        )
        if resumen_allowlist["motivos"]:
            print(f"      Motivos: {resumen_allowlist['motivos']}")
        if resumen_allowlist["filas_aceptadas"] == 0:
            print("[AVISO] El filtro de allowlist dejo 0 filas. Revisa la allowlist.")
            return 3

    # --- Segmentacion informada (antes de generar el libro) ---
    if args.linea or args.categoria or args.estado:
        from src.core.analytics import PedidosAnalytics

        probe = PedidosAnalytics(df)
        if args.dias and args.dias > 0:
            probe = probe.filtrar_dias(args.dias)
        seg = probe.filtrar_segmento(args.linea, args.categoria, args.estado)
        print(f"      Segmento aplicado: {len(seg.df)} de {len(probe.df)} filas")
        if len(seg.df) == 0:
            print("[AVISO] El segmento dejo 0 filas: revisa linea/categoria/estado.")

    # --- Salida ---
    from datetime import date

    fecha = date.today().isoformat()

    def _generar(dest: Path, subset=None, estados_seg=None):
        """Genera un libro. `subset` limita las filas; `estados_seg` segmenta."""
        try:
            return export_reporte_acciones(
                df if subset is None else subset,
                familia=args.familia,
                umbral=args.umbral,
                umbral_planilla=args.umbral_planilla,
                stock_age_hours=ing.cache_age_hours(),
                guardar_foto=not args.sin_foto,
                incluir_detalle=args.incluir_detalle,
                dias=args.dias,
                lineas=args.linea,
                categorias=args.categoria,
                estados=estados_seg if estados_seg is not None else args.estado,
                allowlist_rechazados=rechazados,
                allowlist_resumen=resumen_allowlist,
                output_path=str(dest),
            )
        except PermissionError:
            alt = DATA_DIR.parent / dest.name
            print(f"[AVISO] No pude escribir en {dest.parent}; guardo en {alt}")
            return export_reporte_acciones(
                df if subset is None else subset,
                familia=args.familia,
                umbral=args.umbral,
                umbral_planilla=args.umbral_planilla,
                stock_age_hours=ing.cache_age_hours(),
                guardar_foto=not args.sin_foto,
                incluir_detalle=args.incluir_detalle,
                dias=args.dias,
                lineas=args.linea,
                categorias=args.categoria,
                estados=estados_seg if estados_seg is not None else args.estado,
                allowlist_rechazados=rechazados,
                allowlist_resumen=resumen_allowlist,
                output_path=str(alt),
            )

    if args.por_estado:
        # 4 libros independientes, uno por estado_linea del ERP (guia SKU_BX).
        _ESTADOS = ["NUEVO", "IMPORTADO", "TRADICIONAL", "NACIONAL"]
        salidas = []
        if "estado_linea" not in df.columns:
            print("[AVISO] --por-estado: el reporte no trae estado_linea; se omite.")
        else:
            _est = df["estado_linea"].astype(str).str.strip().str.upper().replace({"NAN": ""})
            for est in _ESTADOS:
                sub = df[_est == est]
                dest = (
                    Path(args.salida)
                    if args.salida and len(_ESTADOS) == 1
                    else escritorio()
                    / f"reaccion_{args.familia.lower()}_{est.lower()}_{fecha}.xlsx"
                )
                if len(sub) == 0:
                    print(f"[3/4] {est}: sin filas, se omite.")
                    continue
                print(f"[3/4] Generando {dest.name} ({len(sub)} filas) ...")
                out = _generar(dest, subset=sub)
                salidas.append(out)
                print(f"      -> {out}")
        if not salidas:
            print("[ERROR] --por-estado no genero ningun archivo.")
            return 3
        print(f"[4/4] Listo: {len(salidas)} libros por estado_linea")
        if args.salir_escritorio:
            import subprocess

            try:
                subprocess.Popen(["explorer", str(salidas[0].parent)])
            except Exception:
                pass
        return 0

    if args.salida:
        salida = Path(args.salida)
    else:
        salida = escritorio() / f"reaccion_{args.familia.lower()}_{fecha}.xlsx"
    print(f"[3/4] Generando {salida.name} ...")
    out = _generar(salida)

    import os

    print(f"[4/4] Listo: {out}")
    print(f"      {filas} filas leidas -> {round(os.path.getsize(out) / 1024)} KB")
    if args.salir_escritorio:
        import subprocess

        try:
            subprocess.Popen(["explorer", str(out)])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
