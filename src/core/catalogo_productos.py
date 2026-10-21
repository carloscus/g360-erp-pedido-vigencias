"""
Catalogo de productos del ERP (PRODUCTOS.xls / "codigos productos.xls").

Fuente: appweb.cipsa.com.pe -> PRODUCTOS.xls, descargado mensual/bimestral.
Es la misma fuente que usa `g360-master-data` para generar
`catalogo_productos.json`, pero este trae el maestro COMPLETO (12k SKUs), no
solo los que estan en la guia SKU_BX (~2.5k).

Aporta al reporte:
    peso_kg    <- CAN_KG_UM   (3.449 SKUs; el set de Render es subconjunto)
    ean13/14   <- COD_EAN / COD_EAN_14
    taxonomia  <- LINEA / GRUPO / TIPO / FAMILIA (por NOMBRE)
    flags      <- FLG_INACTIVO / FLG_DESCONTINUADO

Prioridad: Render manda (verdad del dia); este archivo rellena lo que Render
no trae. Degrada sin romper si el archivo no esta.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pandas as pd

# Nombres habituales del archivo en el escritorio.
PATRONES_NOMBRE = ("codigos productos", "productos", "codigo productos")

# Columnas del maestro del ERP.
COL_CODIGO = "CODIGO"
COL_NOMBRE = "NOMBRE"
COL_EAN = "COD_EAN"
COL_EAN14 = "COD_EAN_14"
COL_KG = "CAN_KG_UM"
COL_LINEA = "LINEA"
COL_GRUPO = "GRUPO"
COL_TIPO = "TIPO"
COL_FAMILIA = "FAMILIA"
COL_INACTIVO = "FLG_INACTIVO"
COL_DESCONTINUADO = "FLG_DESCONTINUADO"


def _es_verdadero(valor) -> bool:
    """Interpreta los checks de Excel: 'Checked' / 'Verdadero' / True."""
    if valor is None:
        return False
    if isinstance(valor, bool):
        return valor
    txt = str(valor).strip().lower()
    return txt in {"checked", "verdadero", "true", "si", "sí", "1", "x"}


def detectar_catalogo_productos(carpeta: str | Path) -> Path | None:
    """El archivo de catalogo de productos mas reciente de la carpeta."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return None
    candidatos = []
    for ext in ("*.xls", "*.xlsx"):
        for p in carpeta.glob(ext):
            n = p.stem.strip().lower()
            if any(pat in n for pat in PATRONES_NOMBRE):
                candidatos.append(p)
    if not candidatos:
        return None
    return sorted(candidatos, key=lambda p: p.stat().st_mtime, reverse=True)[0]


class CatalogoProductos:
    """Lector del maestro de productos del ERP (cacheado en memoria)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._data: dict[str, dict] | None = None
        self._lock = threading.Lock()
        self.unavailable = False
        self.error_msg = ""
        self.fuente = ""

    # ---- carga ----
    def cargar(self, forzar: bool = False) -> bool:
        """Carga el maestro si el archivo esta disponible."""
        if self._data is not None and not forzar:
            return True
        with self._lock:
            if self._data is not None and not forzar:
                return True
            if not self.path or not self.path.exists():
                self.unavailable = True
                self.error_msg = "catalogo de productos del ERP no encontrado" + (
                    f" ({self.path})" if self.path else ""
                )
                return False
            try:
                df = self._leer(self.path)
            except Exception as exc:  # noqa: BLE001
                self.unavailable = True
                self.error_msg = f"catalogo de productos ilegible: {exc}"
                return False
            self._data = self._indexar(df)
            self.fuente = self.path.name
            self.unavailable = False
            self.error_msg = ""
            return True

    @staticmethod
    def _leer(path: Path) -> pd.DataFrame:
        lower = str(path).lower()
        if lower.endswith(".xls"):
            return pd.read_excel(path, dtype=str, engine="xlrd")
        return pd.read_excel(path, dtype=str, engine="openpyxl")

    @staticmethod
    def _indexar(df: pd.DataFrame) -> dict[str, dict]:
        if df.empty or COL_CODIGO not in df.columns:
            return {}
        cols = {str(c).strip().upper(): c for c in df.columns}

        def col(nombre: str) -> str | None:
            return cols.get(nombre)

        c_cod = col(COL_CODIGO)
        c_nom = col(COL_NOMBRE)
        c_ean = col(COL_EAN)
        c_ean14 = col(COL_EAN14)
        c_kg = col(COL_KG)
        c_lin = col(COL_LINEA)
        c_grp = col(COL_GRUPO)
        c_tip = col(COL_TIPO)
        c_fam = col(COL_FAMILIA)
        c_ina = col(COL_INACTIVO)
        c_des = col(COL_DESCONTINUADO)

        out: dict[str, dict] = {}
        for rec in df.to_dict("records"):
            sku = str(rec.get(c_cod, "") or "").strip()
            if not sku:
                continue
            kg = rec.get(c_kg) if c_kg else None
            try:
                kg = float(kg) if kg is not None else 0.0
            except (TypeError, ValueError):
                kg = 0.0
            out[sku] = {
                "nombre": str(rec.get(c_nom, "") or "").strip() if c_nom else "",
                "linea_nombre": str(rec.get(c_lin, "") or "").strip().upper() if c_lin else "",
                "grupo_nombre": str(rec.get(c_grp, "") or "").strip().upper() if c_grp else "",
                "tipo": str(rec.get(c_tip, "") or "").strip().upper() if c_tip else "",
                "familia_nombre": str(rec.get(c_fam, "") or "").strip().upper() if c_fam else "",
                "peso_kg": kg if kg > 0 else 0.0,
                "ean13": str(rec.get(c_ean, "") or "").strip() if c_ean else "",
                "ean14": str(rec.get(c_ean14, "") or "").strip() if c_ean14 else "",
                "descontinuado": _es_verdadero(rec.get(c_des)) if c_des else False,
                "inactivo": _es_verdadero(rec.get(c_ina)) if c_ina else False,
            }
        return out

    # ---- lookups ----
    @property
    def productos(self) -> dict:
        return self._data or {}

    def producto(self, sku: str | None) -> dict | None:
        if not sku:
            return None
        return self.productos.get(str(sku).strip())

    @property
    def origen(self) -> str:
        return self.fuente


# ---------------------------------------------------------------------------
# Instancia compartida
# ---------------------------------------------------------------------------
_CATALOGO: CatalogoProductos | None = None
_CATALOGO_LOCK = threading.Lock()


def get_catalogo_productos(path: str | Path | None = None) -> CatalogoProductos:
    global _CATALOGO
    with _CATALOGO_LOCK:
        if _CATALOGO is None or (path and Path(path) != _CATALOGO.path):
            _CATALOGO = CatalogoProductos(path)
        return _CATALOGO
