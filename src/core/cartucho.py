"""
Importador del "cartucho" (foto estatica de la DB de ventas) a un catalogo unico.

El cartucho es un ZIP autocontenido con:
    historial.db          SQLite con las dimensiones (dim_articulo, dim_linea,
                          dim_cliente, dim_vendedor) y el historico de ventas.
    estado_sustentor.db   Sidecar (oc_alias, day_state).
    CARTUCHO.json         Manifiesto: sha256, allowlist, fechas, conteos.
    config_sanitizado.json Allowlist como documentacion (viene vacio).

Problema que resuelve: `historial.db` pesa ~3.8 GB y SQLite no puede leer
dentro de un ZIP. Este modulo hace UN bootstrap:

    cartucho.zip --> (extrae a temp, consulta read-only, purga)
                 --> .cache/catalogo_unico.json   (~ligero, lectura diaria en ms)

El catalogo unico es estatico: no se re-importa salvo que llegue un cartucho
nuevo (se detecta comparando el sha256 del manifiesto).

Solo libreria estandar (zipfile + sqlite3).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config.settings import DATA_DIR
from src.core.lineas import normalizar_nombre

# --- Contrato del cartucho (ver g360-nc-sustentor-portable/src/core/cartucho.py)
MANIFIESTO = "CARTUCHO.json"
DB_HISTORIAL = "historial.db"

# Carpeta por defecto donde el sustentor deja los cartuchos exportados.
RUTA_CARTUCHOS = Path.home() / "AppData/Roaming/g360-erp-nc-sustentor/data/export"

# Destino del catalogo unico.
CATALOGO_UNICO_PATH = DATA_DIR / "catalogo_unico.json"

# Columnas leidas de cada dimension.
_COLS_ARTICULO = (
    "id_articulo",
    "original_sku",
    "nom_articulo",
    "id_linea",
    "nom_linea",
    "id_grupo",
    "nom_grupo",
    "id_familia",
    "nom_familia",
    "n_ventas",
    "ultima_venta",
)
_COLS_LINEA = (
    "id_linea",
    "nom_linea",
    "id_grupo",
    "nom_grupo",
    "id_familia",
    "nom_familia",
    "n_ventas",
    "total_soles",
)
_COLS_CLIENTE = (
    "id_cliente",
    "nom_cliente",
    "doc_cliente",
    "departamento",
    "provincia",
    "distrito",
    "n_ventas",
    "total_soles",
    "ultima_compra",
)
_COLS_VENDEDOR = (
    "id_vendedor",
    "nom_vendedor",
    "n_ventas",
    "total_soles",
    "n_clientes",
    "ultima_venta",
)


class CartuchoError(RuntimeError):
    """Error de contrato o de lectura del cartucho."""


# ---------------------------------------------------------------------------
# Localizacion y manifiesto
# ---------------------------------------------------------------------------
def buscar_cartucho(directorio: str | Path | None = None) -> Path | None:
    """El cartucho *.zip mas reciente de la carpeta de export del sustentor."""
    carpeta = Path(directorio) if directorio else RUTA_CARTUCHOS
    if not carpeta.is_dir():
        return None
    candidatos = sorted(
        carpeta.glob("cartucho-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidatos[0] if candidatos else None


def leer_manifiesto(origen: str | Path) -> dict:
    """Lee CARTUCHO.json sin extraer la DB (solo el manifiesto).

    Acepta un .zip o una carpeta que contenga el manifiesto.
    """
    origen = Path(origen)
    if origen.is_dir():
        ruta = origen / MANIFIESTO
        if not ruta.exists():
            raise CartuchoError(f"no es un cartucho (falta {MANIFIESTO}): {origen}")
        return json.loads(ruta.read_text(encoding="utf-8"))
    if not origen.exists():
        raise CartuchoError(f"no existe: {origen}")
    with zipfile.ZipFile(origen) as zf:
        if MANIFIESTO not in zf.namelist():
            raise CartuchoError(f"no es un cartucho (falta {MANIFIESTO}): {origen}")
        return json.loads(zf.read(MANIFIESTO).decode("utf-8"))


def allowlist_del_manifiesto(manifiesto: dict) -> list[str]:
    """Allowlist declarada en el manifiesto (mismo criterio que el portable)."""
    crudo = (manifiesto.get("config") or {}).get("allowlist") or []
    return [str(x).strip().upper() for x in crudo if str(x).strip()]


# ---------------------------------------------------------------------------
# Extraccion temporal
# ---------------------------------------------------------------------------
def extraer_historial(zip_path: str | Path, temp_dir: str | Path | None = None) -> Path:
    """Extrae historial.db a una carpeta temporal y devuelve su ruta.

    El llamador es responsable de borrar la carpeta (usa `tempfile.mkdtemp`).
    """
    zip_path = Path(zip_path)
    base = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    destino_dir = Path(tempfile.mkdtemp(prefix="cartucho-", dir=str(base)))
    destino = destino_dir / DB_HISTORIAL
    with zipfile.ZipFile(zip_path) as zf:
        if DB_HISTORIAL not in zf.namelist():
            raise CartuchoError(f"el cartucho no trae {DB_HISTORIAL}")
        info = zf.getinfo(DB_HISTORIAL)
        with zf.open(DB_HISTORIAL) as src, open(destino, "wb") as out:
            shutil.copyfileobj(src, out, length=8 * 1024 * 1024)
    return destino, destino_dir


# ---------------------------------------------------------------------------
# Consulta de las dimensiones
# ---------------------------------------------------------------------------
def _consulta(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Consulta read-only sobre el SQLite extraido."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    try:
        con.row_factory = sqlite3.Row
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _texto(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def construir_catalogo(db_path: str | Path, desde: str) -> dict:
    """Arma el catalogo unico desde las dimensiones de la DB.

    `desde` es la fecha ISO minima de actividad (ventas del cliente/vendedor).
    Las lineas se toman COMPLETAS: son el esqueleto del catalogo y el origen
    del alias nombre->id.
    """
    db_path = Path(db_path)

    # --- lineas (completo) ---
    filas = _consulta(
        db_path,
        f"SELECT {', '.join(_COLS_LINEA)} FROM dim_linea",
    )
    lineas: dict[str, dict] = {}
    alias: dict[str, str] = {}
    for r in filas:
        cod = _texto(r["id_linea"]).upper()
        if not cod:
            continue
        nombre = _texto(r["nom_linea"]).upper()
        lineas[cod] = {
            "nombre": nombre,
            "grupo": _texto(r["id_grupo"]).upper(),
            "grupo_nombre": _texto(r["nom_grupo"]).upper(),
            "familia": _texto(r["id_familia"]).upper(),
            "familia_nombre": _texto(r["nom_familia"]).upper(),
            "n_ventas": int(r["n_ventas"] or 0),
            "total_soles": round(float(r["total_soles"] or 0), 2),
        }
        if nombre:
            alias.setdefault(nombre, cod)
            # "ARCHIVO" -> "ARCHIVO" y variantes con prefijo de grupo
            alias.setdefault(nombre.replace(" - ", " "), cod)
        # el codigo tambien es un alias valido de si mismo
        alias.setdefault(cod, cod)

    # --- articulos (con actividad en la ventana) ---
    filas = _consulta(
        db_path,
        f"SELECT {', '.join(_COLS_ARTICULO)} FROM dim_articulo "
        f"WHERE COALESCE(ultima_venta, '') >= ?",
        (desde,),
    )
    articulos: dict[str, dict] = {}
    alias_sku: dict[str, str] = {}
    n_articulos_total = 0
    for r in filas:
        n_articulos_total += 1
        id_art = _texto(r["id_articulo"])
        sku = _texto(r["original_sku"]) or id_art
        if not sku:
            continue
        # Si dos id_articulo comparten original_sku, gana el mas vendido.
        previo = articulos.get(sku)
        if previo is not None:
            if int(r["n_ventas"] or 0) <= int(previo.get("n_ventas", 0)):
                continue
        articulos[sku] = {
            "id_articulo": id_art,
            "nombre": _texto(r["nom_articulo"]),
            "linea": _texto(r["id_linea"]).upper(),
            "linea_nombre": _texto(r["nom_linea"]).upper(),
            "grupo": _texto(r["id_grupo"]).upper(),
            "grupo_nombre": _texto(r["nom_grupo"]).upper(),
            "familia": _texto(r["id_familia"]).upper(),
            "familia_nombre": _texto(r["nom_familia"]).upper(),
            "n_ventas": int(r["n_ventas"] or 0),
            "ultima_venta": _texto(r["ultima_venta"]),
        }
        if id_art and id_art != sku:
            alias_sku[id_art] = sku

    # --- vendedores (con actividad en la ventana) ---
    filas = _consulta(
        db_path,
        f"SELECT {', '.join(_COLS_VENDEDOR)} FROM dim_vendedor "
        f"WHERE COALESCE(ultima_venta, '') >= ?",
        (desde,),
    )
    vendedores: dict[str, dict] = {}
    for r in filas:
        vid = _texto(r["id_vendedor"]).upper()
        if not vid:
            continue
        vendedores[vid] = {
            "nombre": _texto(r["nom_vendedor"]),
            "n_ventas": int(r["n_ventas"] or 0),
            "total_soles": round(float(r["total_soles"] or 0), 2),
            "n_clientes": int(r["n_clientes"] or 0),
            "ultima_venta": _texto(r["ultima_venta"]),
        }

    # --- clientes (con actividad en la ventana) ---
    filas = _consulta(
        db_path,
        f"SELECT {', '.join(_COLS_CLIENTE)} FROM dim_cliente "
        f"WHERE COALESCE(ultima_compra, '') >= ?",
        (desde,),
    )
    clientes: dict[str, dict] = {}
    alias_cliente: dict[str, str] = {}
    for r in filas:
        cid = _texto(r["id_cliente"]).upper()
        if not cid:
            continue
        nombre = _texto(r["nom_cliente"])
        clientes[cid] = {
            "nombre": nombre,
            "doc": _texto(r["doc_cliente"]),
            "dep": _texto(r["departamento"]).upper(),
            "prov": _texto(r["provincia"]).upper(),
            "dist": _texto(r["distrito"]).upper(),
            "n_ventas": int(r["n_ventas"] or 0),
            "total_soles": round(float(r["total_soles"] or 0), 2),
            "ultima_compra": _texto(r["ultima_compra"]),
        }
        # El ERP usa su propio codigo de cliente: el cruce real es por nombre.
        clave = normalizar_nombre(nombre)
        if clave:
            alias_cliente.setdefault(clave, cid)

    return {
        "lineas": lineas,
        "alias_linea": alias,
        "articulos": articulos,
        "alias_sku": alias_sku,
        "vendedores": vendedores,
        "clientes": clientes,
        "alias_cliente": alias_cliente,
        "conteos": {
            "lineas": len(lineas),
            "alias_linea": len(alias),
            "articulos": len(articulos),
            "articulos_ventana": n_articulos_total,
            "alias_sku": len(alias_sku),
            "vendedores": len(vendedores),
            "clientes": len(clientes),
            "alias_cliente": len(alias_cliente),
        },
    }


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def _ancla_ventana(manifiesto: dict, anios: int) -> tuple[str, str]:
    """(fecha_ancla, fecha_desde) en ISO.

    El ancla es `fecha_max` del manifiesto (no "hoy") para que el catalogo sea
    REPRODUCIBLE desde el mismo cartucho aunque pase el tiempo.
    """
    db = manifiesto.get("db") or {}
    ancla = str(db.get("fecha_max") or "")[:10]
    if not ancla:
        ancla = date.today().isoformat()
    try:
        d = datetime.strptime(ancla, "%Y-%m-%d").date()
    except ValueError:
        d = date.today()
    return ancla, (d - timedelta(days=365 * int(anios))).isoformat()


def importar_cartucho(
    zip_path: str | Path,
    destino: str | Path | None = None,
    anios: int = 5,
    forzar: bool = False,
    temp_dir: str | Path | None = None,
    log=print,
) -> dict:
    """Importa un cartucho al catalogo unico. Idempotente por sha256.

    Si el destino ya tiene un catalogo generado del MISMO cartucho (mismo
    sha256) y no se fuerza, no vuelve a extraer la DB de 3.8 GB.
    """
    zip_path = Path(zip_path)
    destino = Path(destino or CATALOGO_UNICO_PATH)
    manifiesto = leer_manifiesto(zip_path)
    db_meta = manifiesto.get("db") or {}
    sha = str(db_meta.get("sha256") or "")
    ancla, desde = _ancla_ventana(manifiesto, anios)
    allowlist = allowlist_del_manifiesto(manifiesto)

    if destino.exists() and not forzar:
        try:
            previo = json.loads(destino.read_text(encoding="utf-8"))
            if (previo.get("meta") or {}).get("sha256") == sha and sha:
                log(
                    f"[cartucho] Ya esta importado (sha {sha[:12]}...). Usa --force para rehacerlo."
                )
                return previo
        except (OSError, ValueError):
            pass

    log(f"[cartucho] Importando {zip_path.name}")
    log(f"[cartucho] Ventana: {desde} .. {ancla} ({anios} anios)")
    t0 = time.time()
    db_path, temp_dir_path = extraer_historial(zip_path, temp_dir)
    log(
        f"[cartucho] DB extraida ({db_path.stat().st_size / 1024**3:.2f} GB) "
        f"en {time.time() - t0:.0f}s"
    )
    try:
        cat = construir_catalogo(db_path, desde)
    finally:
        shutil.rmtree(temp_dir_path, ignore_errors=True)
        log(f"[cartucho] Temp purgado ({time.time() - t0:.0f}s)")

    conteos = cat["conteos"]
    cat["meta"] = {
        "origen": zip_path.name,
        "sha256": sha,
        "generado_en": str(db_meta.get("generado_en") or manifiesto.get("generado_en") or ""),
        "importado_en": datetime.now().isoformat(timespec="seconds"),
        "contrato_version": manifiesto.get("contrato_version"),
        "ventana": {"anios": int(anios), "ancla": ancla, "desde": desde},
        "allowlist": allowlist,
        "nota_allowlist": "documentacion, no se aplica",
        "conteos": conteos,
        "conteos_manifiesto": db_meta.get("tablas", {}),
    }

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(cat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kb = destino.stat().st_size / 1024
    log(f"[cartucho] Catalogo escrito: {destino} ({kb:.0f} KB)")
    log(
        f"[cartucho] lineas={conteos['lineas']} "
        f"articulos={conteos['articulos']}/{conteos['articulos_ventana']} "
        f"vendedores={conteos['vendedores']} clientes={conteos['clientes']}"
    )
    log(f"[cartucho] allowlist ({len(allowlist)}): {' '.join(allowlist)}")
    return cat


def catalogo_actual(destino: str | Path | None = None) -> dict | None:
    """Carga el catalogo unico si existe (None si todavia no se importo)."""
    ruta = Path(destino or CATALOGO_UNICO_PATH)
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
