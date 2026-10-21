"""Build portable con PyInstaller (opcional).

Genera un ejecutable autocontenido de la app:
    python build_portable.py

El ejecutable se crea en dist/g360-erp-pedido-vigencias.exe.
Requiere: pip install pyinstaller
"""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", "g360-erp-pedido-vigencias",
        "--windowed",
        "--collect-all", "flet",
        "--add-data", "assets;assets",
        "main.py",
    ]
    print("Ejecutando PyInstaller...")
    subprocess.run(cmd, check=True)
    print("Build portable completado: dist/g360-erp-pedido-vigencias.exe")


if __name__ == "__main__":
    main()
