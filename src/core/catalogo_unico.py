"""
Catalogo unico: maestro de referencia construido desde el cartucho de la DB.

Sustituye a Supabase como fuente de taxonomia y de validacion de maestros.
Es un archivo estatico y liviano (.cache/catalogo_unico.json) generado por
`cartucho_import.py` a partir de un cartucho (foto) de la DB de ventas.

Contenido:
    meta         sha256, fecha del cartucho, ventana de actividad, allowlist
    lineas       {codigo: {nombre, grupo, familia, ...}}
    alias_linea  {NOMBRE: codigo}   -> resuelve lineas por nombre o por id
    articulos    {sku: {nombre, linea, grupo, familia, ...}}
    alias_sku    {id_articulo: sku} -> permite buscar por cualquiera de los dos
    vendedores   {id: {nombre, n_ventas, ...}}
    clientes     {id: {nombre, doc, dep, prov, dist, ...}}

Degrada sin romper: si el catalogo no existe, `disponible` es False y los
metodos devuelven vacio (el pipeline cae al catalogo local / ERP).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from src.config.settings import DATA_DIR, LINEAS_VALIDAS_DEFAULT, LINEA_NOMBRES_AMBIGUOS
from src.core.lineas import linea_sufijo, normalizar_nombre, resolver_codigo_linea

CATALOGO_UNICO_PATH = DATA_DIR / "catalogo_unico.json"

# Nombres ambiguos normalizados (nunca resuelven codigo por si solos).
_AMBIGUOS = {str(n).strip().upper() for n in LINEA_NOMBRES_AMBIGUOS}


class CatalogoUnico:
    """Lector del catalogo unico (archivo JSON estatico, cacheado en memoria)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or CATALOGO_UNICO_PATH)
        self._data: dict | None = None
        self._lock = threading.Lock()
        self.unavailable = False
        self.error_msg = ""

    # ---- carga ----
    def cargar(self, forzar: bool = False) -> bool:
        """Carga el archivo si existe. Devuelve False si no esta disponible."""
        if self._data is not None and not forzar:
            return True
        with self._lock:
            if self._data is not None and not forzar:
                return True
            if not self.path.exists():
                self.unavailable = True
                self.error_msg = (
                    f"catalogo unico no encontrado ({self.path}). "
                    "Corre cartucho_import.py para generarlo."
                )
                return False
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.unavailable = True
                self.error_msg = f"catalogo unico ilegible: {exc}"
                return False
            self._data = data
            self.unavailable = False
            self.error_msg = ""
            return True

    @property
    def disponible(self) -> bool:
        return self._data is not None or self.cargar()

    # ---- secciones ----
    @property
    def meta(self) -> dict:
        return (self._data or {}).get("meta") or {}

    @property
    def articulos(self) -> dict:
        return (self._data or {}).get("articulos") or {}

    @property
    def lineas(self) -> dict:
        return (self._data or {}).get("lineas") or {}

    @property
    def alias_linea(self) -> dict:
        return (self._data or {}).get("alias_linea") or {}

    @property
    def alias_sku(self) -> dict:
        return (self._data or {}).get("alias_sku") or {}

    @property
    def clientes(self) -> dict:
        return (self._data or {}).get("clientes") or {}

    @property
    def alias_cliente(self) -> dict:
        """Nombre normalizado -> id_cliente (el ERP no comparte IDs con la DB)."""
        return (self._data or {}).get("alias_cliente") or {}

    @property
    def vendedores(self) -> dict:
        return (self._data or {}).get("vendedores") or {}

    @property
    def allowlist(self) -> list[str]:
        """Allowlist canonica (del manifiesto del cartucho).

        Cae a LINEAS_VALIDAS_DEFAULT si el catalogo no trae la suya.
        """
        cruda = self.meta.get("allowlist") or []
        vals = [str(v).strip().upper() for v in cruda if str(v).strip()]
        return vals or list(LINEAS_VALIDAS_DEFAULT)

    @property
    def origen(self) -> str:
        m = self.meta
        return f"{m.get('origen', '?')} ({m.get('generado_en', '?')})"

    # ---- lookups ----
    def articulo(self, sku: str | None) -> dict | None:
        """Articulo por SKU (o por id_articulo via alias)."""
        if not sku:
            return None
        arts = self.articulos
        s = str(sku).strip()
        if s in arts:
            return arts[s]
        alias = self.alias_sku
        destino = alias.get(s) or alias.get(s.upper())
        if destino:
            return arts.get(destino)
        return None

    def linea(self, codigo: str | None) -> dict | None:
        """Linea por codigo exacto (2 chars o el que use la DB)."""
        if not codigo:
            return None
        return self.lineas.get(str(codigo).strip().upper())

    def codigo_linea(self, valor: str | None) -> str:
        """Resuelve el codigo de linea a partir de un codigo o un nombre.

        Orden: codigo del maestro -> alias exacto por nombre -> sufijo de 2
        chars -> alias contenido en el texto. Usa las MISMAS reglas que el
        pipeline (`src/core/lineas.py`), con el maestro como diccionario.
        """
        if not valor:
            return ""
        txt = str(valor).strip().upper()
        if not txt:
            return ""
        lineas = self.lineas
        # 1. el codigo manda: "0178 - ARCHIVO" -> "78", "01MA" -> "MA"
        cod = resolver_codigo_linea(txt)
        if cod and cod in lineas:
            return cod
        # 2. alias exacto por nombre: "ARCHIVO" -> "78".
        #    Un nombre ambiguo (p.ej. "ACCESORIOS" = 79 y CD) NO resuelve: el
        #    codigo explicito manda y atribuir por un nombre compartido metia
        #    el SKU en la linea equivocada.
        alias = self.alias_linea
        if txt in alias and txt not in _AMBIGUOS:
            return alias[txt]
        # 2.5. prefijo de 2 chars: SKUs tipo "CA001" -> "CA", "CB007" -> "CB".
        #     Solo aplica cuando el valor empieza con 'C' (sub-marcas Crayola)
        #     para evitar que el prefijo de otras lineas (p.ej. "99"=VARIOS)
        #     capture valores como "99ZZ" que deberian resolver por sufijo "ZZ".
        if len(txt) >= 2 and txt.startswith("C"):
            pref = txt[:2].upper()
            if pref in lineas:
                return pref
        # 3. sufijo de 2 chars
        suf = linea_sufijo(txt)
        if suf and suf in lineas:
            return suf
        # 4. alias contenido en el texto (solo alias largos, para no ruido).
        #    Se saltan los nombres ambiguos para no atribuir a una linea por
        #    un nombre compartido ("ACCESORIOS" = 79 y CD).
        for nombre, c in alias.items():
            if nombre in _AMBIGUOS:
                continue
            if len(nombre) >= 4 and nombre in txt:
                return c
        return ""

    def es_linea_valida(self, valor: str | None) -> bool:
        """True si la linea (por codigo o por nombre) esta en la allowlist."""
        cod = self.codigo_linea(valor)
        if cod and cod in set(self.allowlist):
            return True
        # fallback: sufijo de 2 chars contra la allowlist
        txt = str(valor or "").strip().upper()
        if len(txt) >= 2:
            suf = txt[-2:]
            if suf in set(self.allowlist):
                return True
        return False

    def cliente(self, id_cliente: str | None) -> dict | None:
        if not id_cliente:
            return None
        return self.clientes.get(str(id_cliente).strip().upper())

    def cliente_por_nombre(self, nombre: str | None) -> dict | None:
        """Maestro de cliente por nombre normalizado.

        El ERP usa su propio codigo de cliente (distinto al id_cliente de la
        DB), asi que el cruce real es por nombre.
        """
        if not nombre:
            return None
        clave = normalizar_nombre(nombre)
        if not clave:
            return None
        alias = self.alias_cliente
        cid = alias.get(clave)
        if cid:
            return self.clientes.get(cid)
        # Fallback: prefijo (el ERP a veces trunca el nombre)
        if len(clave) >= 12:
            prefijo = clave[:30]
            for k, v in alias.items():
                if k.startswith(prefijo):
                    return self.clientes.get(v)
        return None

    def datos_cliente(self, id_cliente: str | None, nombre: str | None = None) -> dict | None:
        """Maestro del cliente: por id de DB, y si no, por nombre."""
        d = self.cliente(id_cliente)
        if d is None and nombre:
            d = self.cliente_por_nombre(nombre)
        return d

    def vendedor(self, id_vendedor: str | None) -> dict | None:
        if not id_vendedor:
            return None
        return self.vendedores.get(str(id_vendedor).strip().upper())

    def nombre_cliente(self, id_cliente: str | None) -> str:
        d = self.cliente(id_cliente) or {}
        return str(d.get("nombre") or "")

    def ubicacion_cliente(self, id_cliente: str | None, nombre: str | None = None) -> dict:
        """Departamento/provincia/distrito del cliente (para ruteo)."""
        d = self.datos_cliente(id_cliente, nombre) or {}
        return {
            "doc": str(d.get("doc") or ""),
            "dep": str(d.get("dep") or ""),
            "prov": str(d.get("prov") or ""),
            "dist": str(d.get("dist") or ""),
        }

    def nombre_vendedor(self, id_vendedor: str | None) -> str:
        d = self.vendedor(id_vendedor) or {}
        return str(d.get("nombre") or "")


# ---------------------------------------------------------------------------
# Instancia compartida
# ---------------------------------------------------------------------------
_CATALOGO: CatalogoUnico | None = None
_CATALOGO_LOCK = threading.Lock()


def get_catalogo(path: str | Path | None = None) -> CatalogoUnico:
    """Instancia compartida del catalogo unico (carga perezosa)."""
    global _CATALOGO
    with _CATALOGO_LOCK:
        if _CATALOGO is None or (path and Path(path) != _CATALOGO.path):
            _CATALOGO = CatalogoUnico(path)
        return _CATALOGO
