"""
Punto de entrada de g360-erp-pedido-vigencias.

Lanza la aplicacion Flet desktop para el analisis de vigencias de pedidos CIPSA.
Configura el logger rotativo (run_log.txt, max 2MB, 3 backups) antes de arrancar la UI.
Verifica dependencias criticas y maneja errores de inicializacion con un dialogo
amigable que incluye enlace al log.
"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- Logger rotativo (max 2MB, 3 backups) ---
_LOG_PATH = Path(__file__).resolve().parent / "run_log.txt"
_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger("g360.pedido_vigencias")
if not logger.handlers:
    _handler = RotatingFileHandler(
        _LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Consola tambien (para ver logs en tiempo real durante desarrollo)
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
logger.addHandler(_console)


# --- Constantes de version ---
APP_NAME = "Vigencias de Pedidos - CIPSA"
APP_VERSION = "1.1.0"
MIN_FLET_VERSION = (0, 28, 0)


def _check_dependencies() -> list[str]:
    """Verifica que las dependencias criticas esten instaladas.

    Retorna lista de errores (vacia si todo OK).
    """
    errors: list[str] = []
    required_modules = [
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),
        ("xlrd", "xlrd"),
        ("requests", "requests"),
    ]

    for module_name, pip_name in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            errors.append(f"Falta dependencia: {pip_name} (pip install {pip_name})")

    # Version minima de flet (page.open/SnackBar y window API requieren >= 0.28)
    try:
        import importlib.metadata as _md

        flet_version = _md.version("flet")
        parts = [p for p in flet_version.split(".")[:3] if p.isdigit()]
        if parts and tuple(map(int, parts)) < MIN_FLET_VERSION:
            errors.append(
                f"flet {flet_version} es antiguo "
                f"(se requiere >= {'.'.join(map(str, MIN_FLET_VERSION))}): "
                f"pip install -U 'flet[desktop]'"
            )
    except Exception:
        pass  # sin metadata no se bloquea el arranque

    return errors


def _show_error_page(page, title: str, message: str, log_path: Path) -> None:
    """Muestra una pagina de error amigable con enlace al log."""
    try:
        import flet as ft
    except ImportError:
        print(f"[FATAL] {title}: {message}")
        return

    def _open_log(_):
        page.launch_url("file://" + str(log_path))

    page.add(
        ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=64, color=ft.Colors.RED_400),
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.RED_400, text_align=ft.TextAlign.CENTER),
                ft.Container(height=8),
                ft.Text(message, size=14, color=ft.Colors.GREY_300,
                        text_align=ft.TextAlign.CENTER),
                ft.Container(height=16),
                ft.TextButton(
                    "Ver log para mas informacion",
                    icon=ft.Icons.DESCRIPTION,
                    on_click=_open_log,
                ),
            ], alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4),
            alignment=ft.alignment.center,
            expand=True,
            padding=40,
        )
    )
    page.update()


def main(page) -> None:
    """Callback de inicio de Flet: verifica dependencias y lanza la app.

    Args:
        page: Objeto Page de Flet proporcionado por el framework.
    """
    import flet as ft

    logger.info("=" * 60)
    logger.info("%s v%s", APP_NAME, APP_VERSION)
    logger.info("=" * 60)

    # --- Verificar dependencias ---
    dep_errors = _check_dependencies()
    if dep_errors:
        error_msg = "Dependencias faltantes:\n" + "\n".join(f"  - {e}" for e in dep_errors)
        logger.error(error_msg)
        _show_error_page(page, "Error de Inicializacion", error_msg, _LOG_PATH)
        return

    # --- Lanzar aplicacion ---
    try:
        from src.app import PedidoVigenciasApp

        PedidoVigenciasApp(page)
        logger.info("Aplicacion cargada correctamente (v%s)", APP_VERSION)
    except Exception as ex:
        error_detail = traceback.format_exc()
        logger.error(f"[FATAL] Error al iniciar la aplicacion: {ex}\n{error_detail}")
        _show_error_page(
            page,
            "Error al iniciar la aplicacion",
            f"Detalle: {ex}",
            _LOG_PATH,
        )


if __name__ == "__main__":
    import flet as ft
    logger.info("Lanzando aplicacion Flet desktop...")
    try:
        ft.app(main, view=ft.AppView.FLET_APP)
    except Exception as ex:
        logger.error(f"[FATAL] Error fatal: {ex}\n{traceback.format_exc()}")
        sys.exit(1)
