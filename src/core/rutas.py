"""
Rutas del sistema (escritorio, cache) compartidas por la UI y la CLI.
"""

from __future__ import annotations

from pathlib import Path


def escritorio() -> Path:
    """Carpeta del escritorio del usuario (tolerante a OneDrive).

    Usa la API de Windows (CSIDL_DESKTOPDIRECTORY) para no fallar cuando el
    escritorio esta redirigido a OneDrive; si falla, cae a las rutas
    conventionales.
    """
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_DESKTOPDIRECTORY = 0x10
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf):
            return Path(buf.value)
    except Exception:
        pass
    alt = Path.home() / "Desktop"
    if alt.exists():
        return alt
    return Path.home() / "Escritorio"
