"""
Bootstrap del catalogo unico desde el cartucho de la DB de ventas.

Uso:
    python cartucho_import.py                    # cartucho mas reciente, 5 anos
    python cartucho_import.py --zip "C:\\...\\cartucho-20261012-172938.zip"
    python cartucho_import.py --anios 10 --force

Que hace (UNA sola vez por cartucho):
  1. Lee CARTUCHO.json sin extraer (allowlist, sha256, fecha_max).
  2. Extrae historial.db (3.8 GB) a temp y consulta las dimensiones.
  3. Escribe .cache/catalogo_unico.json (ligero) y purga el temp.

Despues, el reporte lee ese archivo en milisegundos: no hay lectura diaria
de la DB grande. Si llega un cartucho nuevo, se re-importa (se detecta por
sha256) o se corre este script con --force.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.cartucho import (
    CATALOGO_UNICO_PATH,
    CartuchoError,
    buscar_cartucho,
    importar_cartucho,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa el cartucho de la DB de ventas al catalogo unico.",
    )
    parser.add_argument(
        "--zip",
        help="Ruta del cartucho .zip (opcional: toma el mas reciente)",
    )
    parser.add_argument(
        "--directorio",
        help="Carpeta donde buscar cartuchos (default: export del sustentor)",
    )
    parser.add_argument(
        "--salida",
        help="Ruta del catalogo unico (default: .cache/catalogo_unico.json)",
    )
    parser.add_argument(
        "--anios",
        type=int,
        default=5,
        help="Ventana de actividad para articulos/vendedores/clientes (default: 5)",
    )
    parser.add_argument(
        "--temp",
        help="Carpeta temporal para extraer la DB (default: temp del sistema)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-importa aunque el sha256 sea el mismo",
    )
    args = parser.parse_args(argv)

    zip_path = Path(args.zip) if args.zip else buscar_cartucho(args.directorio)
    if zip_path is None:
        print("[ERROR] No encontre ningun cartucho.")
        print("        Busca en %APPDATA%\\g360-erp-nc-sustentor\\data\\export\\")
        print("        o pasa la ruta con --zip.")
        return 2
    if not zip_path.exists():
        print(f"[ERROR] No existe: {zip_path}")
        return 2

    destino = Path(args.salida) if args.salida else CATALOGO_UNICO_PATH
    print(f"[1/3] Cartucho: {zip_path}")
    try:
        cat = importar_cartucho(
            zip_path,
            destino=destino,
            anios=args.anios,
            forzar=args.force,
            temp_dir=args.temp,
        )
    except CartuchoError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except KeyboardInterrupt:
        print("\n[AVISO] Interrumpido.")
        return 130

    meta = cat.get("meta", {})
    ventana = meta.get("ventana", {})
    print(
        "[2/3] Ventana de actividad: "
        f"{ventana.get('desde')} .. {ventana.get('ancla')} "
        f"({ventana.get('anios')} anos)"
    )
    print("[3/3] Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
