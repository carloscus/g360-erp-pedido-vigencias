"""
Pipeline de ingesta de vigencias de pedidos CIPSA.

Responsabilidades:
- Leer archivos XLS/XLSX preservando los SKUs como texto (dtype=str).
- Consolidar multiples archivos en un unico DataFrame marcando la fuente.
- Enriquecer con el catalogo maestro (matching directo, sin padding).
- Enriquecer con el snapshot del API G360 y cache local por SKU/almacen.
- Calcular campos derivados: saldo, porcentajes, cajas, valor del saldo.
- Detectar SKUs sin catalogo y sin stock del API.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from src.config.settings import (
    API_TIMEOUT,
    CACHE_TTL,
    CATALOGO_RUTA,
    CONDICION_PROTOTIPO,
    DATA_DIR,
    ESTADOS_LINEA_VALIDOS,
    ESTADO_DESPACHABLE,
    LINEAS_VALIDAS_DEFAULT,
    LINEA_NOMBRE_A_CODIGO,
    LINEA_NOMBRES_AMBIGUOS,
    S1_API_KEY,
    S1_API_URL,
)
from src.core.analytics import normalize_cond_familia
from src.core.catalogo_unico import CatalogoUnico, get_catalogo
from src.core.lineas import linea_sufijo as _linea_sufijo
from src.core.lineas import resolver_codigo_linea as _resolver_codigo_linea

# Columnas del ERP que se consideran numericas al calcular derivados
_NUMERIC_COLS = [
    "CAN_PEDIDO",
    "CAN_DESPACHO",
    "PRE_ARTICULO",
    "PEDIDO_IMPORTE_ARITCULO",
    "POR_DESPACHO",
    "ORD_DESPACHO",
]


def linea_sufijo(val) -> str:
    """Sufijo de 2 chars para match de linea valida: 0101 -> 01, 01MA -> MA."""
    return _linea_sufijo(val)


def resolver_codigo_linea(val, name_to_code=None) -> str:
    """Resuelve el codigo corto (2 chars) de una linea desde cualquier formato.

    Acepta codigos puros ('0101' -> '01', '01MA' -> 'MA', 'MA' -> 'MA'),
    formatos con nombre ('0178 - ARCHIVO' -> '78', '01 - PELOTAS' -> '01',
    '01AD - ACCESORIOS' -> 'AD') y nombres de linea ('PELOTAS') resueltos
    contra `name_to_code` (mapa del reporte + catalogo + semilla estatica).
    """
    return _resolver_codigo_linea(val, name_to_code)


def _es_vacio(valor) -> bool:
    """True si el valor representa 'sin dato' (None, NaN, "" o "nan")."""
    if valor is None:
        return True
    if isinstance(valor, float) and pd.isna(valor):
        return True
    try:
        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass
    return not str(valor).strip() or str(valor).strip().lower() == "nan"


def es_linea_valida(linea_val, grupo_val=None, validas=None, name_to_code=None) -> bool:
    """True si el sufijo de linea (fallback grupo) esta en la lista valida.

    Mantiene el comportamiento historico (sufijo de 2 chars) y agrega la
    resolucion por nombre: 'PELOTAS' -> '01' cuando `name_to_code` o el
    formato "CODIGO - NOMBRE" permiten recuperar el codigo real.
    """
    validas_set = {
        str(v).strip().upper() for v in (validas if validas is not None else LINEAS_VALIDAS_DEFAULT)
    }
    cod = resolver_codigo_linea(linea_val, name_to_code) or linea_sufijo(linea_val)
    if cod and cod in validas_set:
        return True
    gcod = resolver_codigo_linea(grupo_val, name_to_code) or linea_sufijo(grupo_val)
    return bool(gcod and gcod in validas_set)


def _detect_engine(path: str) -> str:
    """Detecta el motor de lectura segun la extension del archivo.

    - .xls  -> xlrd (libro Excel 97-2003)
    - .xlsx -> openpyxl (libro Excel moderno)
    """
    lower = path.lower()
    if lower.endswith(".xls"):
        return "xlrd"
    if lower.endswith(".xlsx"):
        return "openpyxl"
    raise ValueError(f"Formato no soportado: {path}. Solo se aceptan XLS y XLSX.")


class Ingester:
    """Ingesta y enriquece los archivos de vigencias del ERP."""

    def __init__(
        self,
        catalog_path: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        lineas_validas: list[str] | None = None,
    ) -> None:
        self.catalog_path = str(catalog_path or CATALOGO_RUTA)
        self.api_url = api_url or S1_API_URL
        self.api_key = api_key or S1_API_KEY
        self._lineas_validas = list(lineas_validas) if lineas_validas else None
        self._catalogo: dict[str, dict] = {}
        self._catalogo_lock = threading.Lock()
        self.api_unavailable = False
        self.api_error_msg = ""
        self._stock_cache: dict[str, dict] | None = None
        self._render_catalog: dict[str, dict] | None = None
        # Maestro de referencia (catalogo unico del cartucho): fallback de
        # taxonomia y validacion de maestros cliente/vendedor. La verdad de
        # producto y stock es Render.
        self._catalogo_unico: CatalogoUnico | None = None
        self._db_unavailable = False
        self.db_error_msg = ""
        # Maestro de productos del ERP (PRODUCTOS.xls): peso, EAN, taxonomia
        # y flags de descontinuado. Se aplica antes de Render.
        self._cat_prod_error = ""
        self._cat_prod_fuente = ""
        # Mapa linea -> categoria comercial (se arma del snapshot de Render
        # y del catalogo local; se invalida cuando cambia el snapshot).
        self._cat_linea_cache: dict[str, str] | None = None
        self._estados_linea_invalidos = 0
        self._categorias_derivadas = 0

    # ---------------------------------------------------------------
    # Catalogo maestro
    # ---------------------------------------------------------------
    def _load_catalogo(self) -> dict[str, dict]:
        """Carga el catalogo maestro como dict {sku: producto} con SKU texto."""
        path = Path(self.catalog_path)
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            productos = data.get("productos", data if isinstance(data, list) else [])
            return {str(p.get("sku")): p for p in productos if p.get("sku") is not None}
        except Exception:
            return {}

    def ensure_catalogo(self) -> None:
        """Garantiza que el catalogo este cargado (idempotente)."""
        if not self._catalogo:
            with self._catalogo_lock:
                if not self._catalogo:
                    self._catalogo = self._load_catalogo()

    # ---------------------------------------------------------------
    # Lectura de archivos
    # ---------------------------------------------------------------
    def load_file(self, path: str) -> pd.DataFrame:
        """Lee un archivo XLS/XLSX con dtype=str y lo retorna como DataFrame.

        El dtype=str preserva los ceros a la izquierda de los SKUs
        (ej: 01240 no se convierte a 1240).
        """
        engine = _detect_engine(path)
        df = pd.read_excel(path, engine=engine, dtype=str)
        df["_fuente"] = Path(path).name
        return df

    def load_multiple(self, paths: list[str]) -> pd.DataFrame:
        """Consolida multiples archivos en un unico DataFrame maestro.

        Cada fila queda marcada con el nombre del archivo de origen (_fuente).
        Los archivos con columnas distintas se unen rellenando con null.
        """
        frames: list[pd.DataFrame] = []
        for p in paths:
            try:
                df = self.load_file(p)
                frames.append(df)
            except Exception as ex:
                raise ValueError(f"Error cargando {p}: {ex}") from ex
        if not frames:
            raise ValueError("Ningun archivo pudo ser cargado.")
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames, ignore_index=True, sort=False)

    # ---------------------------------------------------------------
    # Enrichment con catalogo
    # ---------------------------------------------------------------
    def enrich_with_catalog(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega datos del catalogo maestro por matching directo de SKU.

        Sin padding ni transformacion: el SKU tal como viene en el archivo se
        busca tal cual en el catalogo (01240 y 001240 son SKUs distintos).
        """
        self.ensure_catalogo()
        sku_col = self._find_sku_col(df)
        if sku_col is None:
            return df
        df["SKU"] = df[sku_col].astype(str).str.strip()
        cat = self._catalogo

        products = pd.DataFrame.from_dict(cat, orient="index")
        products.index = products.index.astype(str)
        products = products.reindex(df["SKU"])
        for source, target, default in [
            ("categoria", "categoria", ""),
            ("estado_linea", "estado_linea", ""),
            ("linea", "linea", ""),
            ("grupo", "grupo", ""),
            ("familia", "familia", ""),
            ("un_bx", "un_bx", 1),
            ("nombre", "nombre_catalogo", ""),
        ]:
            values = (
                products[source]
                if source in products
                else pd.Series(index=products.index, dtype=object)
            )
            df[target] = values.fillna(default).to_numpy()

        return df

    def cargar_catalogo_unico(self, forzar: bool = False) -> bool:
        """Carga el catalogo unico (cartucho). False si no esta disponible.

        El catalogo es estatico: se carga una vez por proceso y se relee
        solo si el archivo cambio (`forzar=True`).
        """
        if self._catalogo_unico is not None and not forzar:
            return True
        cat = get_catalogo()
        try:
            ok = cat.cargar(forzar=forzar)
        except Exception as exc:  # noqa: BLE001
            self._db_unavailable = True
            self.db_error_msg = f"Catalogo unico no disponible ({exc})"
            return False
        if ok:
            self._catalogo_unico = cat
            self._db_unavailable = False
            self.db_error_msg = ""
        else:
            self._db_unavailable = True
            self.db_error_msg = cat.error_msg
        return ok

    def enrich_with_db_lines(self, df: pd.DataFrame) -> pd.DataFrame:
        """Taxonomia desde el catalogo unico (cartucho de la DB de ventas).

        Prioridad actual: Render (verdad catalogo+stock) > catalogo unico >
        catalogo local > ERP. Rellena `linea`/`grupo`/`familia`/nombres SOLO
        donde falten; Render sobrescribe despues en `enrich_with_stock_api`.
        El rol de los maestros queda en `verify_clientes_vendedores`
        (consistencia ID<->NOM cliente/vendedor).

        Degrada offline: si el catalogo unico no esta, devuelve df sin cambios.
        """
        if not self.cargar_catalogo_unico():
            return df
        cat = self._catalogo_unico
        if not cat or "SKU" not in df.columns:
            return df

        rows = df["SKU"].map(lambda s: cat.articulo(s))
        # Mapeo: el catalogo local trae 'linea'/'grupo'; el catalogo unico
        # aporta la taxonomia oficial del maestro (linea/grupo/familia).
        # Rellena SOLO donde falta: el catalogo local ya aplicado gana.
        for target, source in [
            ("linea", "linea"),
            ("nom_linea", "linea_nombre"),
            ("grupo", "grupo"),
            ("nom_grupo", "grupo_nombre"),
            ("familia", "familia"),
            ("nom_familia", "familia_nombre"),
        ]:
            vals = rows.apply(
                lambda d, s=source: (d or {}).get(s, "") if isinstance(d, dict) else ""
            )
            if target not in df.columns:
                df[target] = vals.fillna("")
                continue
            vacio = df[target].astype(str).str.strip().eq("") | df[target].isna()
            df.loc[vacio, target] = vals[vacio]

        # El nombre oficial del maestro pisa al local, pero solo si lo tiene.
        vals = rows.apply(lambda d: (d or {}).get("nombre", "") if isinstance(d, dict) else "")
        if "nombre_catalogo" not in df.columns:
            df["nombre_catalogo"] = ""
        tiene = vals.astype(str).str.strip().ne("")
        df.loc[tiene, "nombre_catalogo"] = vals[tiene]

        return df

    # ---------------------------------------------------------------
    # Enrichment con stock API
    # ---------------------------------------------------------------
    def _apply_stock_cache(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica el CACHE local de stock (sin tocar la red).

        Es el camino de `--sin-stock`: el cache ya tiene la foto de stock
        por SKU/almacen, pero ese camino NO debe perder la clasificacion
        VES/121/otros. Antes, sin llamar a `enrich_with_stock_api` el
        `stock_api_121` quedaba en 0 para todo y la hoja TRASLADO_121
        salia vacia (ej: SKU 72014 con 121=100,224 y VES=0 no aparecia).

        Aplica el mismo pipeline que `enrich_with_stock_api` pero sin
        refrescar desde Render:
          1. `stock_api_disponible` desde el cache
          2. taxonomia desde el catalogo cacheado (Render)
          3. clasificacion VES/121/otros (`_classify_stock`)
          4. cobertura, relevancia y prototipo
        """
        if "SKU" not in df.columns:
            return df
        results = self._load_stock_cache(ignore_ttl=True)
        catalog = self._load_render_catalog()
        if not results:
            # Cache vacio o vencido: sin stock, pero se deja el pipeline
            # completo (cobertura 0) para que el reporte sea consistente.
            df["stock_api_disponible"] = df["SKU"].map(lambda s: {})
            df["sin_stock_api"] = True
        else:
            df["stock_api_disponible"] = df["SKU"].map(lambda s: results.get(s) or {})
            df["sin_stock_api"] = df["stock_api_disponible"].apply(
                lambda d: isinstance(d, dict) and not d
            )
            df = self._apply_render_catalog(df, catalog)
            # La categoria comercial es funcion de la linea.
            df = self.enrich_categorias_por_linea(df)
        # Clasificacion VES/121/otros + cobertura (mismo camino que la red).
        df = self._classify_stock(df)
        df = self._recompute_relevance(df)
        df = self._apply_prototipo(df)
        df = self.normalizar_lineas(df)
        return df

    def enrich_with_stock_api(
        self,
        df: pd.DataFrame,
        max_concurrent: int = 10,
    ) -> pd.DataFrame:
        """Fuente de verdad Render: catalogo + stock por SKU/almacen.

        - Snapshot completo primero (1 peticion); fallback por-SKU via
          ?search= para Render cold-start o snapshots pesados.
        - Cache local TTL para no repetir descargas dentro de la ventana vigente.
        - Agrega stock_api_disponible (dict {almacen: disponible}) y
          sin_stock_api (bool) por fila.
        - Enriquece taxonomia desde Render (verdad): categoria,
          estado_linea, linea/linea_id, grupo, un_bx, nombre_catalogo.
          Solo sobrescribe donde Render trae valor; el resto se conserva
          (DB local como fallback previo, ERP como ultimo recurso).
        - Re-clasifica VES/121/otros y cobertura usando SOLO el stock del API.
        - Si el API no responde, marca api_unavailable=True y deja el stock
          en 0 (no se usa el ERP como fallback).
        """
        if "SKU" not in df.columns:
            return df
        skus = df["SKU"].dropna().astype(str).unique().tolist()
        results = self._load_stock_cache()
        catalog = self._load_render_catalog()
        missing = [sku for sku in skus if sku not in results or sku not in catalog]
        if missing:
            fetched = self._fetch_stock_snapshot()
            if fetched is None:
                # Fallback: por-SKU via ?search= (tolerante a cold-start).
                fetched_fb = self._fetch_items_per_sku(missing, max_workers=max_concurrent)
                if fetched_fb is None:
                    self.api_unavailable = True
                else:
                    fetched = fetched_fb
            if fetched is None:
                self.api_unavailable = True
            else:
                self.api_unavailable = False
                self.api_error_msg = ""
                stock_map, catalog_map = fetched
                results.update(stock_map)
                catalog.update(catalog_map)
                self._save_stock_cache(results, catalog)
                self._stock_cache = results
                self._render_catalog = catalog
                # El mapa linea->categoria depende del snapshot: invalidar.
                self._cat_linea_cache = None

        df["stock_api_disponible"] = df["SKU"].map(lambda s: results.get(s) or {})
        df["sin_stock_api"] = df["stock_api_disponible"].apply(
            lambda d: isinstance(d, dict) and not d
        )
        df = self._apply_render_catalog(df, catalog)
        # La categoria comercial es funcion de la linea: los SKUs que el
        # maestro de Render no cubre se derivan de su linea (0 ambiguedades).
        df = self.enrich_categorias_por_linea(df)
        # El stock de Render es la fuente real: recalcular clasificacion
        # (VES/121/otros), cobertura y relevancia usando stock_api_disponible.
        df = self._classify_stock(df)
        df = self._recompute_relevance(df)
        df = self._apply_prototipo(df)
        # Normalizar la linea al codigo canonico (la columna venia mezclando
        # codigos de Render con nombres del catalogo local).
        df = self.normalizar_lineas(df)
        return df

    @staticmethod
    def _split_code_name(raw: str) -> tuple[str, str]:
        """Separa '01 - PELOTAS' -> ('01', 'PELOTAS'); 'PELOTAS' -> ('', 'PELOTAS')."""
        txt = str(raw or "").strip()
        if not txt:
            return "", ""
        if "-" in txt:
            code, _, name = txt.partition("-")
            return code.strip().upper(), name.strip().upper()
        if len(txt) <= 3:
            return txt.upper(), ""
        return "", txt.upper()

    @staticmethod
    def _catalog_from_item(item: dict) -> dict:
        """Extrae taxonomia Render de un item del snapshot (verdad catalogo)."""
        linea_id = str(item.get("linea_id", "") or "").strip().upper()
        linea_campo = str(item.get("linea", "") or "").strip()
        linea_code, linea_nombre = Ingester._split_code_name(linea_campo)
        # El catalogo de Render expone `linea` como "01 - PELOTAS" (y `linea`
        # pelado, sin etiqueta, cuando no hay nombre). Si el texto no trae
        # separador, `linea_code` ya es el codigo y `linea_nombre` queda vacio.
        grupo_code, grupo_nombre = Ingester._split_code_name(item.get("grupo", ""))
        nombre = (
            str(item.get("nombre_corto", "") or "").strip()
            or str(item.get("descripcion", "") or "").strip()
        )

        def _num(key) -> float:
            try:
                return float(item.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        un_bx = _num("un_bx")
        # El codigo de linea manda sobre el nombre: si el catalogo trae
        # linea="ACCESORIOS" (SKUs de la linea CD, que comparte nombre con la
        # 79) y linea_id="CD", el catalogo unico guarda la 79 por nombre y el
        # SKU terminaba atribuido a la linea equivocada.
        cod_linea = linea_id or linea_code
        nom_linea = ""
        if linea_nombre and linea_nombre != cod_linea:
            nom_linea = linea_nombre
        elif cod_linea and linea_code == cod_linea and linea_nombre:
            nom_linea = linea_nombre
        return {
            # `linea_id` es la referencia de codigo del catalogo (v3.3.0).
            "linea_id": cod_linea,
            "linea": cod_linea or linea_code,
            "linea_nombre": nom_linea,
            "grupo": grupo_code,
            "grupo_nombre": grupo_nombre,
            "categoria": str(item.get("categoria", "") or "").strip().upper(),
            "estado_linea": str(item.get("estado_linea", "") or "").strip().upper(),
            "un_bx": un_bx,
            "nombre_catalogo": nombre,
            # Metricas operativas: peso para capacidad de furgon y EAN para picking
            "peso_kg": _num("peso_kg"),
            "ean13": str(item.get("ean13", "") or "").strip(),
            "ean14": str(item.get("ean14", "") or "").strip(),
        }

    @staticmethod
    def _build_alias(catalog: dict[str, dict]) -> dict[str, str]:
        """Mapa NOMBRE->ID desde pares '01 - PELOTAS' del snapshot Render.

        DETERMINISTA y SIN COLISION: si un mismo nombre apunta a dos codigos
        distintos (caso real: "ACCESORIOS" es la linea 79 -tijeras- y tambien
        la CD -pinceles Crayola-) el nombre NO se mapea. Resolver por un
        nombre ambiguo atribuiria los SKUs a la linea equivocada, y el
        resultado dependia del orden de iteracion del diccionario (no
        determinista entre corridas). El CODIGO siempre manda; un nombre
        ambiguo solo se resuelve con su codigo explicito ("0179"/"01CD").
        """
        alias: dict[str, str] = {}
        ambiguos: set[str] = set()
        # Orden estable por SKU para que el resultado no dependa del dict.
        for sku in sorted(catalog or {}, key=str):
            entry = (catalog or {}).get(sku)
            if not isinstance(entry, dict):
                continue
            for code_key, name_key in [("linea", "linea_nombre"), ("grupo", "grupo_nombre")]:
                code = str(entry.get(code_key, "") or "").strip().upper()
                name = str(entry.get(name_key, "") or "").strip().upper()
                if not code or not name or code == name:
                    continue
                previo = alias.get(name)
                if previo is not None and previo != code:
                    # Nombre compartido por dos lineas: ambiguo -> se descarta.
                    ambiguos.add(name)
                elif name not in ambiguos:
                    alias[name] = code
        for name in ambiguos:
            alias.pop(name, None)
        # Ambiguos conocidos del negocio: nunca resolver por nombre.
        for name in LINEA_NOMBRES_AMBIGUOS:
            alias.pop(str(name).strip().upper(), None)
        return alias

    @staticmethod
    def _linea_nombre_de(catalog: dict[str, dict], codigo: str) -> str:
        """Nombre canonico de una linea segun el catalogo de Render.

        Solo nombres (no puede devolver un codigo): evita que una linea
        quede con `linea_nombre` = "CD" o "01" y que el nombre de una linea
        se use para re-resolver el codigo de OTRA (colision ACCESORIOS).
        """
        cod = str(codigo or "").strip().upper()
        if not cod:
            return ""
        for entry in (catalog or {}).values():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("linea_id", "") or "").strip().upper() != cod:
                continue
            nom = str(entry.get("linea_nombre", "") or "").strip().upper()
            if nom and nom != cod and not re.fullmatch(r"[0-9A-Z]{2}", nom):
                return nom
        return ""

    def _apply_render_catalog(self, df: pd.DataFrame, catalog: dict[str, dict]) -> pd.DataFrame:
        """Sobrescribe taxonomia con Render donde haya valor (verdad)."""
        if not catalog or "SKU" not in df.columns:
            return df
        mapped = df["SKU"].astype(str).map(catalog)
        # categoria / estado_linea: Render manda si trae valor
        for target, source in [
            ("categoria", "categoria"),
            ("estado_linea", "estado_linea"),
            ("nombre_catalogo", "nombre_catalogo"),
        ]:
            vals = mapped.apply(lambda d: (d or {}).get(source, "") if isinstance(d, dict) else "")
            has = vals.astype(str).str.strip().ne("") & vals.notna()
            if target not in df.columns:
                df[target] = ""
                has = vals.astype(str).str.strip().ne("") & vals.notna()
            df.loc[has, target] = vals[has].astype(str).str.strip()
        # estado_linea: solo valen los estados de la guia ERP (SKU_BX).
        # El API de stock, cuando el catalogo no trae estado, lo rellena con
        # el GRUPO del producto: eso mete "TAJADORES" / "RESALTADORES" como si
        # fueran estados y ensucia la segmentacion. El grupo tiene su columna.
        df = self._limpiar_estados_linea(df)
        # linea / grupo: Render manda (linea_id preferido)
        # Guardar la linea PREVIA a Render: deja saber si la linea original
        # venia como codigo o como nombre (trazabilidad de origen_linea).
        if "linea" in df.columns:
            df["_linea_pre"] = df["linea"].astype(str)
        for target, sources in [
            ("linea", ["linea_id", "linea"]),
            ("grupo", ["grupo"]),
        ]:

            def _pick(d):
                if not isinstance(d, dict):
                    return ""
                for s in sources:
                    v = str(d.get(s, "") or "").strip().upper()
                    if v:
                        return v
                return ""

            vals = mapped.apply(_pick)
            has = vals.ne("")
            if target not in df.columns:
                df[target] = ""
            df.loc[has, target] = vals[has]
            if target == "linea":
                # Trazabilidad: la linea la trajo el maestro de Render.
                df["_linea_de_render"] = has.values
                # El catalogo publica el nombre de linea en `linea_nombre`.
                # Render sobrescribia `linea` pero no el nombre, asi que el
                # nombre quedaba con el valor de OTRO maestro (o con un
                # codigo) y luego `normalizar_lineas` re-resolvia el codigo
                # por ese nombre: dos lineas distintas comparten nombre
                # (ACCESORIOS = 79 y CD) y la linea terminaba mal asignada.
                nom_render = df["linea"].map(lambda v: Ingester._linea_nombre_de(catalog, v))
                tiene_nom = nom_render.ne("")
                if "linea_nombre" not in df.columns:
                    df["linea_nombre"] = ""
                df.loc[tiene_nom, "linea_nombre"] = nom_render[tiene_nom]
        # un_bx: Render manda si > 0
        vals_bx = mapped.apply(
            lambda d: float((d or {}).get("un_bx", 0) or 0) if isinstance(d, dict) else 0.0
        )
        has_bx = vals_bx > 0
        if "un_bx" not in df.columns:
            df["un_bx"] = 1
        df.loc[has_bx, "un_bx"] = vals_bx[has_bx]
        # peso_kg (por unidad): Render manda si > 0. NO se usa el precio de
        # Render: el precio de verdad es el del ERP (importe / cantidad).
        vals_peso = mapped.apply(
            lambda d: float((d or {}).get("peso_kg", 0) or 0) if isinstance(d, dict) else 0.0
        )
        has_peso = vals_peso > 0
        if "peso_kg" not in df.columns:
            df["peso_kg"] = 0.0
        df.loc[has_peso, "peso_kg"] = vals_peso[has_peso]
        df["peso_estimada"] = ~(pd.to_numeric(df["peso_kg"], errors="coerce").fillna(0) > 0)
        # EAN para picking de almacen
        for target in ("ean13", "ean14"):
            vals = mapped.apply(
                lambda d, t=target: (
                    str((d or {}).get(t, "") or "").strip() if isinstance(d, dict) else ""
                )
            )
            if target not in df.columns:
                df[target] = ""
            df.loc[vals.ne(""), target] = vals[vals.ne("")]
        return df

    @property
    def db_unavailable(self) -> bool:
        """True si el catalogo unico (maestro) no esta disponible."""
        return self._db_unavailable

    def _mapa_categoria_linea(self) -> dict[str, str]:
        """Mapa linea (codigo) -> categoria comercial (VINIBALL/VINIFAN/...).

        Fuente primaria: el snapshot de Render (verdad de la clasificacion).
        Fuente secundaria: el catalogo local (master-data).
        Solo se aceptan lineas con categoria UNICA (0 ambiguedades medidas).
        """
        if self._cat_linea_cache is not None:
            return self._cat_linea_cache
        mapa: dict[str, str] = {}
        # Snapshot de Render: cada item trae linea y categoria.
        for v in (getattr(self, "_render_catalog", None) or {}).values():
            if not isinstance(v, dict):
                continue
            cat = str(v.get("categoria", "") or "").strip().upper()
            lin = str(v.get("linea", "") or "").strip().upper()
            if cat and lin and lin not in mapa:
                mapa[lin] = cat
        # Catalogo local (master-data): linea_codigo -> categoria.
        for v in (getattr(self, "_catalogo", None) or {}).values():
            if not isinstance(v, dict):
                continue
            cat = str(v.get("categoria", "") or "").strip().upper()
            lin = str(v.get("linea_codigo", "") or "").strip().upper()
            if cat and lin and lin not in mapa:
                mapa[lin] = cat
        self._cat_linea_cache = mapa
        return mapa

    def enrich_categorias_por_linea(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rellena `categoria` de los SKUs que el maestro de Render no cubre.

        La categoria comercial (VINIBALL / VINIFAN / REPRESENTADAS / ...) es
        FUNCION de la linea: medido sobre el snapshot de Render son 34 lineas
        con 34 categorias unicas y 0 ambiguedades (el catalogo local confirma
        19 de ellas sin contradecir). Asi, un SKU que tiene linea pero no
        entra en el maestro de Render igual queda clasificado, y deja de
        marcarse como "sin catalogo".
        """
        if "categoria" not in df.columns:
            df["categoria"] = ""
        else:
            # Si la columna es 100% NaN (dtype float) hay que castear a
            # object para poder asignar texto (ValueError en pandas 2.x).
            if pd.api.types.is_float_dtype(df["categoria"]):
                df["categoria"] = df["categoria"].astype(object)
        vacio = df["categoria"].astype(str).str.strip().eq("") | df["categoria"].isna()
        if not vacio.any():
            return df
        mapa = self._mapa_categoria_linea()
        if not mapa:
            return df
        from src.core.allowlist import codigo_linea

        codigos = df["linea"].map(lambda v: codigo_linea(v) if str(v or "").strip() else "")
        cats = codigos.map(mapa)
        mask = vacio & cats.astype(str).str.strip().ne("")
        df.loc[mask, "categoria"] = cats[mask]
        self._categorias_derivadas = int(mask.sum())
        return df

    def _limpiar_estados_linea(self, df: pd.DataFrame) -> pd.DataFrame:
        """Deja `estado_linea` solo con los estados de la guia ERP (SKU_BX).

        El API de stock, cuando el catalogo maestro no trae estado_linea de un
        SKU, lo rellena con el GRUPO del producto: asi "TAJADORES" /
        "RESALTADORES" / "BORRADOR" terminaban como estados y contaminaban la
        segmentacion por estado de linea de los pedidos (15,7% del detalle).

        El grupo tiene su propia columna. El valor original se conserva en
        `estado_linea_raw` para que el dato no se pierda en silencio.
        """
        if "estado_linea" not in df.columns:
            return df
        _est = df["estado_linea"].astype(str).str.strip().str.upper()
        _validos = {e.upper() for e in ESTADOS_LINEA_VALIDOS}
        _malos = ~_est.isin(_validos) & _est.ne("") & _est.ne("NAN")
        self._estados_linea_invalidos = int(_malos.sum())
        if "estado_linea_raw" not in df.columns:
            df["estado_linea_raw"] = ""
        df.loc[_malos, "estado_linea_raw"] = _est[_malos]
        df.loc[_malos, "estado_linea"] = ""
        return df

    def normalizar_lineas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza `linea` al CODIGO canonico de 2 chars.

        Antes la columna mezclaba representaciones: Render guarda el codigo
        ("78") pero el catalogo local guarda el NOMBRE ("ARCHIVO") y el
        catalogo unico solo rellena vacios. Resultado: la misma linea
        aparecia como "01" en un pedido y "PELOTAS" en otro, y filtrar por
        linea no funcionaba.

        Tras normalizar:
            linea       = codigo canonico ("78")  -> filtrable y agrupable
            linea_nombre= nombre legible ("ARCHIVO")
            origen_linea= como se resolvio (RENDER/CODIGO/ALIAS/VACIA)
        """
        if "linea" not in df.columns:
            return df
        from src.core.allowlist import codigo_linea

        uni = self._catalogo_unico
        if uni is not None and not uni.cargar():
            uni = None

        codigos: list[str] = []
        nombres: list[str] = []
        origenes: list[str] = []
        for _, r in df.iterrows():
            bruto = str(r.get("linea", "") or "").strip()
            # El valor original (antes de que Render la pise) dice si la linea
            # venia como codigo o como nombre.
            original = str(r.get("_linea_pre", "") or "").strip()
            if original.lower() == "nan":
                original = ""
            ref = original or bruto
            cod = codigo_linea(bruto) or (codigo_linea(original) if original else "")
            if not cod and not bruto:
                # linea vacia: se atribuye por el grupo
                cod = codigo_linea(r.get("grupo", ""))
            if not cod:
                codigos.append("")
                nombres.append("")
                origenes.append("VACIA" if not ref else "DESCONOCIDA")
                continue
            nom = str(r.get("linea_nombre", "") or "").strip().upper()
            # El valor original solo es un NOMBRE si no parece un codigo:
            # "CA" es un codigo de linea (Render luego lo cambio por "77").
            if not nom and ref and not re.fullmatch(r"[0-9A-Z]{2}", ref.upper()):
                nom = ref.upper()
            if not nom and uni is not None:
                nom = str((uni.lineas.get(cod) or {}).get("nombre") or "").upper()
            if not nom and uni is not None:
                nom = str(uni.alias_linea.get(cod) or "").upper()
            codigos.append(cod)
            nombres.append(nom)
            if bool(r.get("_linea_de_render", False)):
                origenes.append("RENDER")
            elif not ref:
                origenes.append("VACIA")
            elif ref.upper() == cod:
                origenes.append("CODIGO")
            else:
                origenes.append("ALIAS")

        df["linea"] = codigos
        df["linea_nombre"] = nombres
        df["linea_cod"] = codigos
        df["origen_linea"] = origenes
        return df

    def enrich_with_catalogo_productos(
        self, df: pd.DataFrame, path: str | Path | None = None
    ) -> pd.DataFrame:
        """Enriquece con el maestro de productos del ERP (PRODUCTOS.xls).

        Aporta peso_kg (CAN_KG_UM), EAN13/14, taxonomia por nombre
        (LINEA/GRUPO/FAMILIA/TIPO) y el flag de descontinuado.
        Se aplica ANTES de Render: Render sobrescribe peso/EAN donde tenga
        dato y conserva el del ERP donde no (asi el peso es la union).
        Degrada sin romper si el archivo no esta.
        """
        if "SKU" not in df.columns:
            return df
        from src.core.catalogo_productos import get_catalogo_productos

        cat = get_catalogo_productos(path)
        if not cat.cargar():
            self._cat_prod_error = cat.error_msg
            return df
        self._cat_prod_error = ""
        self._cat_prod_fuente = cat.origen

        rows = df["SKU"].map(lambda s: cat.producto(s))

        def _val(source: str, default=""):
            return rows.apply(
                lambda d, s=source: (d or {}).get(s, default) if isinstance(d, dict) else default
            )

        # peso: rellena donde no hay (Render despues pisa donde si tiene)
        peso = pd.to_numeric(_val("peso_kg", 0.0), errors="coerce").fillna(0.0)
        if "peso_kg" not in df.columns:
            df["peso_kg"] = 0.0
        falta_peso = pd.to_numeric(df["peso_kg"], errors="coerce").fillna(0).le(0)
        df.loc[falta_peso, "peso_kg"] = peso[falta_peso]

        # EAN
        for col, source in (("ean13", "ean13"), ("ean14", "ean14")):
            vals = _val(source, "").astype(str).str.strip()
            if col not in df.columns:
                df[col] = ""
            vacio = df[col].astype(str).str.strip().eq("")
            df.loc[vacio & vals.ne(""), col] = vals[vacio & vals.ne("")]

        # taxonomia por nombre (no pisa la existente; la linea se resuelve a codigo)
        uni = self._catalogo_unico
        cod_linea = _val("linea_nombre", "")
        if uni is not None and uni.cargar():
            cod_linea = cod_linea.map(lambda v: uni.codigo_linea(v) if v else "")
        for target, source, resolver in (
            ("linea", "linea_nombre", True),
            ("nom_linea", "linea_nombre", False),
            ("nom_grupo", "grupo_nombre", False),
            ("nom_familia", "familia_nombre", False),
            ("tipo", "tipo", False),
        ):
            vals = cod_linea if resolver else _val(source, "").astype(str)
            vals = vals.astype(str).str.strip()
            if target not in df.columns:
                df[target] = ""
            vacio = df[target].astype(str).str.strip().eq("") | df[target].isna()
            df.loc[vacio & vals.ne(""), target] = vals[vacio & vals.ne("")]

        # nombre oficial del maestro ERP
        nombre = _val("nombre", "").astype(str).str.strip()
        if "nombre_catalogo" not in df.columns:
            df["nombre_catalogo"] = ""
        vacio = df["nombre_catalogo"].astype(str).str.strip().eq("")
        df.loc[vacio & nombre.ne(""), "nombre_catalogo"] = nombre[vacio & nombre.ne("")]

        # ciclo de vida: descontinuado / inactivo
        df["producto_descontinuado"] = rows.apply(
            lambda d: bool(d.get("descontinuado", False)) if isinstance(d, dict) else False
        )
        df["producto_inactivo"] = rows.apply(
            lambda d: bool(d.get("inactivo", False)) if isinstance(d, dict) else False
        )
        return df

    def _allowlist_efectiva(self) -> list[str]:
        """Allowlist vigente: la explicita > la del catalogo unico > la default.

        La del catalogo unico (cartucho) es la canonica: 24 lineas core.
        """
        if self._lineas_validas:
            return [str(v).strip().upper() for v in self._lineas_validas]
        if self.cargar_catalogo_unico() and self._catalogo_unico:
            return list(self._catalogo_unico.allowlist)
        return list(LINEAS_VALIDAS_DEFAULT)

    def aplicar_allowlist(
        self,
        df: pd.DataFrame,
        allowlist: list[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        """Filtro estricto de lineas de producto (allowlist).

        Devuelve (aceptados, rechazados, resumen). Lo rechazado queda fuera
        del embudo de accion y se reporta en SANEAMIENTO. Ver
        `src/core/allowlist.py`.
        """
        from src.core.allowlist import aplicar_allowlist, cargar_allowlist

        al = allowlist if allowlist is not None else cargar_allowlist()
        return aplicar_allowlist(df, al)

    def verify_clientes_vendedores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Verificacion maestra cliente/vendedor (rol DB, offline-safe).

        No bloquea: marca es_cliente_consistente / es_vendedor_consistente.
        Un ID es consistente si mapea a un unico NOM no vacio en el lote.
        La DB (cuando haya dim_cliente/dim_vendedor) solo refuerza este flag.
        """
        out = df
        for id_col, nom_col, flag in [
            ("COD_CLIENTE", "NOM_CLIENTE", "es_cliente_consistente"),
            ("ID_VENDEDOR", "NOM_VENDEDOR", "es_vendedor_consistente"),
        ]:
            if id_col not in out.columns:
                out[flag] = False
                continue
            nom = (
                out[nom_col].astype(str).str.strip()
                if nom_col in out.columns
                else pd.Series("", index=out.index)
            )
            ids_ok = out[id_col].astype(str).str.strip().ne("") & nom.ne("")
            # IDs con mas de un nombre distinto en el lote = inconsistentes
            n_noms = (
                out.assign(_nom=nom)
                .groupby(out[id_col].astype(str).str.strip())["_nom"]
                .transform("nunique")
            )
            out[flag] = (ids_ok & (n_noms == 1)).fillna(False).astype(bool)
        return out

    def _fetch_stock_snapshot(self) -> tuple[dict[str, dict], dict[str, dict]] | None:
        """Descarga el snapshot completo en una sola peticion HTTP.

        Retorna (stock_map, catalog_map): stock {sku: {alm: disponible}},
        catalogo {sku: {linea_id, linea, grupo, categoria, estado_linea,
        un_bx, nombre_catalogo}}. Reintenta con timeout largo (Render
        cold-start puede tardar >60s en la primera peticion).
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{self.api_url}/stock",
                    params={"fuente": "todas"},
                    headers={"x-api-key": self.api_key, "Accept": "application/json"},
                    timeout=(10, 120),
                )
                if resp.status_code != 200:
                    self.api_error_msg = (
                        "API rechazo la peticion. Verifica la API key."
                        if resp.status_code == 403
                        else f"API de stock respondio HTTP {resp.status_code}."
                    )
                    return None
                data = resp.json()
                items = data.get("items", []) if isinstance(data, dict) else []
                stock_map: dict[str, dict] = {}
                catalog_map: dict[str, dict] = {}
                for item in items:
                    sku = str(item.get("sku", "")).strip()
                    if sku:
                        stock_map[sku] = {
                            str(alm.get("almacen")): alm.get("disponible", 0)
                            for alm in item.get("almacenes", [])
                            if alm.get("almacen")
                        }
                        catalog_map[sku] = self._catalog_from_item(item)
                self.api_error_msg = ""
                return stock_map, catalog_map
            except requests.RequestException as exc:
                last_err = exc
                time.sleep(5 * (attempt + 1))
        self.api_error_msg = f"No se pudo conectar al API de stock: {last_err}"
        return None

    def _fetch_items_per_sku(
        self, skus: list[str], max_workers: int = 8
    ) -> tuple[dict[str, dict], dict[str, dict]] | None:
        """Fallback por-SKU via ?search= (tolerante a cold-start/payloads).

        Retorna (stock_map, catalog_map) o None si nada pudo recuperarse.
        """
        from concurrent.futures import ThreadPoolExecutor

        stock_map: dict[str, dict] = {}
        catalog_map: dict[str, dict] = {}
        failures = 0

        def one(sku: str) -> tuple[str, dict | None]:
            try:
                resp = requests.get(
                    f"{self.api_url}/stock",
                    params={"search": sku},
                    headers={"x-api-key": self.api_key, "Accept": "application/json"},
                    timeout=(10, 60),
                )
                if resp.status_code != 200:
                    return sku, None
                data = resp.json()
                items = data.get("items", []) if isinstance(data, dict) else []
                for item in items:
                    if str(item.get("sku", "")).strip() == str(sku).strip():
                        return sku, item
                return sku, (items[0] if items else None)
            except requests.RequestException:
                return sku, None

        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            for sku, item in pool.map(one, skus):
                if not item:
                    failures += 1
                    continue
                stock_map[sku] = {
                    str(alm.get("almacen")): alm.get("disponible", 0)
                    for alm in item.get("almacenes", [])
                    if alm.get("almacen")
                }
                catalog_map[sku] = self._catalog_from_item(item)
        if not stock_map and not catalog_map:
            self.api_error_msg = f"Fallback por-SKU fallo ({failures}/{len(skus)} sin respuesta)."
            return None
        return stock_map, catalog_map

    def cache_age_hours(self) -> float | None:
        """Antiguedad en horas del snapshot de stock cacheado (None si no hay).

        Permite avisar en el reporte cuando la guia de traslado se apoya en
        stock viejo (TTL por defecto 15 min).
        """
        try:
            with open(DATA_DIR / "stock_cache.json", encoding="utf-8") as f:
                payload = json.load(f)
            ts = float(payload.get("ts", 0))
            if ts <= 0:
                return None
            return round((time.time() - ts) / 3600.0, 2)
        except (OSError, ValueError, TypeError):
            return None

    def _load_stock_cache(self, ignore_ttl: bool = False) -> dict[str, dict]:
        """Cache local de stock. `ignore_ttl=True` lo usa aunque este viejo.

        El camino `--sin-stock` (reporte offline) necesita el snapshot
        cacheado aunque haya pasado el TTL: es la unica foto de stock
        disponible y el reporte avisa de su antiguedad en el PANEL.
        """
        # Un cache ya cargado en memoria manda: `ignore_ttl` solo decide si
        # se acepta el de DISCO cuando esta vencido.
        if self._stock_cache is not None:
            return self._stock_cache
        try:
            with open(DATA_DIR / "stock_cache.json", encoding="utf-8") as f:
                payload = json.load(f)
            vigente = time.time() - float(payload.get("ts", 0)) <= CACHE_TTL
            if vigente or ignore_ttl:
                self._stock_cache = payload.get("stock", {})
                self._render_catalog = payload.get("catalog", {}) or {}
            else:
                self._stock_cache = {}
                self._render_catalog = {}
        except (OSError, ValueError, TypeError):
            self._stock_cache = {}
            self._render_catalog = {}
        return self._stock_cache

    def _load_render_catalog(self) -> dict[str, dict]:
        if getattr(self, "_render_catalog", None) is not None:
            return self._render_catalog
        self._load_stock_cache()
        return getattr(self, "_render_catalog", {}) or {}

    @staticmethod
    def _save_stock_cache(
        stock: dict[str, dict],
        catalog: dict[str, dict] | None = None,
        alias: dict[str, str] | None = None,
    ) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if alias is None:
                alias = Ingester._build_alias(catalog or {})
            with open(DATA_DIR / "stock_cache.json", "w", encoding="utf-8") as f:
                json.dump(
                    {"ts": time.time(), "stock": stock, "catalog": catalog or {}, "alias": alias},
                    f,
                    ensure_ascii=False,
                )
        except OSError:
            pass

    # ---------------------------------------------------------------
    # Trazabilidad (registro de archivos procesados en SQLite)
    # ---------------------------------------------------------------
    def registrar_importaciones(
        self,
        paths: list[str],
        df: pd.DataFrame | None = None,
        api_state: str = "offline",
        resultado: str = "ok",
        mensaje: str | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        """Registra cada archivo en `importaciones` (SQLite acotado).

        Aditivo y seguro: nunca eleva excepciones ni afecta el flujo de
        ingesta. Permite detectar re-procesos por hash y trazar el historial
        de cargas y su resultado.
        """
        try:
            from src.core.db import PedidosDB, hash_archivo

            db = PedidosDB(db_path).ensure_schema()
            per_file = {}
            if df is not None and "_fuente" in df.columns and len(df):
                per_file = df["_fuente"].value_counts().to_dict()
            for p in paths:
                name = Path(p).name
                filas = int(per_file.get(name, len(df) if df is not None else 0))
                db.registrar_importacion(
                    filename=name,
                    file_hash=hash_archivo(p),
                    filas=filas,
                    api_state=api_state,
                    resultado=resultado,
                    mensaje=mensaje,
                )
        except Exception as ex:
            _log.warning("[Ingester] registrar_importaciones fallo (no bloquea): %s", ex)

    # ---------------------------------------------------------------
    # Campos derivados
    # ---------------------------------------------------------------
    def compute_derived(
        self, df: pd.DataFrame, fecha_corte: date | datetime | None = None
    ) -> pd.DataFrame:
        """Calcula saldo, cobertura, vigencia y precio unitario.

        Reglas de negocio CIPSA:
        - VES (Centro Logistico) = stock disponible real para despachar
        - 121 (Prod. Terminados) = inspeccion QC, NO disponible
        - Auxiliares (40, 106, 129...) = solo informativo
        - Precio unitario = PEDIDO_IMPORTE_ARITCULO / CAN_PEDIDO
        - Vigencia negativa = pedido vencido
        """
        for col in _NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        # Familia normalizada de condicion de pago (chips operativos)
        if "CONDICION_PAGO" in df.columns:
            df["cond_familia"] = df["CONDICION_PAGO"].apply(normalize_cond_familia)
        elif "cond_familia" not in df.columns:
            df["cond_familia"] = "OTRO"
        # Asegurar un_bx numerico con default 1
        if "un_bx" not in df.columns:
            df["un_bx"] = 1
        df["un_bx"] = pd.to_numeric(df["un_bx"], errors="coerce").fillna(1).replace(0, 1)

        pedido = df.get("CAN_PEDIDO", pd.Series(0, index=df.index)).fillna(0)
        despacho = df.get("CAN_DESPACHO", pd.Series(0, index=df.index)).fillna(0)
        safe_pedido = pedido.replace(0, 1)

        # --- Importe y Precio Unitario ---
        if "PEDIDO_IMPORTE_ARITCULO" in df.columns:
            importe_linea = pd.to_numeric(df["PEDIDO_IMPORTE_ARITCULO"], errors="coerce").fillna(0)
        else:
            importe_linea = pd.to_numeric(df.get("PRE_ARTICULO", 0), errors="coerce").fillna(0)

        # Precio unitario real (granular).
        # Es el precio DEFINITIVO de la venta: sale del reporte de vigencias.
        # El `precio` del catalogo (API / master-data) es solo referencial
        # (precio de lista) y NO se cruza con este dato.
        df["precio_unitario"] = (importe_linea / safe_pedido).round(2)

        # --- Control de coherencia del precio (C) ---
        # El ERP debe cumplir: PEDIDO_IMPORTE_ARITCULO = (PRE_ARTICULO/VIGENCIA)*CAN_PEDIDO
        # Solo es verificable en las lineas con VIGENCIA > 0 (si no, PRE_ARTICULO
        # es 0 y no hay precio que contrastar).
        # Tolerancia RELATIVA: con VIGENCIA muy chico la division amplifica
        # el redondeo del ERP (VIGENCIA=0.01 llega a mover S/ 65 sobre S/ 6.362).
        if (
            "PEDIDO_IMPORTE_ARITCULO" in df.columns
            and "PRE_ARTICULO" in df.columns
            and "VIGENCIA" in df.columns
        ):
            _pre = pd.to_numeric(df["PRE_ARTICULO"], errors="coerce")
            _vig = pd.to_numeric(df["VIGENCIA"], errors="coerce")
            _calc = (_pre / _vig.replace(0, pd.NA)) * pedido
            _desv = (_calc - importe_linea).abs()
            _tol = (importe_linea.abs() * 0.02).clip(lower=0.05)
            _verificable = _vig.gt(0) & _pre.gt(0) & _desv.notna()
            df["precio_verificable"] = _verificable
            df["precio_desvio"] = _desv.fillna(0.0).round(2)
            df["precio_coherente"] = (~_verificable) | (_desv <= _tol)
        else:
            df["precio_verificable"] = False
            df["precio_desvio"] = 0.0
            df["precio_coherente"] = True

        # --- Saldo y Porcentajes ---
        df["saldo"] = (pedido - despacho).round(2)
        df["por_atendido"] = (despacho / safe_pedido * 100).round(2)
        df["por_pendiente"] = ((pedido - despacho) / safe_pedido * 100).round(2)
        df["cajas"] = (df["saldo"] / df["un_bx"]).round(2)
        df["valor_pedido"] = importe_linea.round(2)
        df["valor_saldo"] = ((df["saldo"] / safe_pedido) * importe_linea).round(2)
        df["valor_atendido"] = ((despacho / safe_pedido) * importe_linea).round(2)
        # % atendido en soles (monto), analogo al por_atendido en cantidad
        safe_valor_pedido = df["valor_pedido"].replace(0, 1)
        df["por_atendido_valor"] = (
            ((df["valor_atendido"] / safe_valor_pedido) * 100).clip(0, 100).round(2)
        )
        df.loc[df["valor_pedido"] == 0, "por_atendido_valor"] = 0.0

        # --- Stock del API con diferenciacion por almacen ---
        # El API retorna: {sku: {almacen: cantidad}}
        # Necesitamos separar: VES (venta), 121 (inspeccion), otros
        df = self._classify_stock(df)

        # --- Vigencia ---
        if "VIGENCIA" in df.columns:
            df["vigencia"] = pd.to_numeric(df["VIGENCIA"], errors="coerce").fillna(0).astype(int)
        if "POR_VIGENCIA" in df.columns:
            df["por_vigencia"] = pd.to_numeric(df["POR_VIGENCIA"], errors="coerce").fillna(0)
        if "POR_DESPACHO" in df.columns:
            df["por_despacho"] = pd.to_numeric(df["POR_DESPACHO"], errors="coerce").fillna(0)

        # --- Antiguedad y Estado de Vigencia ---
        if "PEDIDO_FECHA" in df.columns:
            pedido_fecha = pd.to_datetime(df["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
            corte = pd.Timestamp(fecha_corte or datetime.now().date())
            delta = (corte - pedido_fecha).dt.days
            df["dias_desde_pedido"] = delta.clip(lower=0).fillna(0).astype(int)
            df["antiguedad_pedido"] = pd.cut(
                delta,
                bins=[-float("inf"), -1, 7, 15, 30, 60, float("inf")],
                labels=["FUTURA", "0-7 dias", "8-15 dias", "16-30 dias", "31-60 dias", ">60 dias"],
            ).astype(str)

            # Estado de vigencia basado en dias transcurridos vs vigencia
            if "vigencia" in df.columns:
                vigencia_positiva = df["vigencia"].replace(0, 1)  # evitar division por cero
                df["por_vigencia_consumida"] = (
                    df["dias_desde_pedido"] / vigencia_positiva * 100
                ).round(1)
                df["estado_vigencia"] = df.apply(
                    lambda r: (
                        "COMPLETADO"
                        if r["saldo"] <= 0
                        else (
                            "SIN VIGENCIA"
                            if r["vigencia"] <= 0
                            else (
                                "VENCIDO"
                                if r["por_vigencia_consumida"] > 100
                                else (
                                    "POR VENCER" if r["por_vigencia_consumida"] > 75 else "VIGENTE"
                                )
                            )
                        )
                    ),
                    axis=1,
                )

        # --- Cobertura, Faltante, Relevancia y Bloqueado ---
        df = self._recompute_relevance(df)
        df = self.verify_clientes_vendedores(df)

        df = self._apply_prototipo(df)
        # Blindaje del dato: el estado de linea solo puede ser uno de la guia.
        df = self._limpiar_estados_linea(df)

        return df

    def _nombre_a_codigo(self, df: pd.DataFrame) -> dict[str, str]:
        """Mapa nombre de linea -> codigo corto (semilla + snapshot + reporte).

        Orden: semilla estatica de settings, pares del snapshot Render
        ("01 - PELOTAS"), `linea_codigo` del catalogo local y pares
        "CODIGO - NOMBRE" del propio archivo de vigencias. Offline-safe.
        Permite rescatar filas cuya linea llega como nombre puro ("PELOTAS").
        """
        mapa = {
            str(k).strip().upper(): str(v).strip().upper() for k, v in LINEA_NOMBRE_A_CODIGO.items()
        }
        mapa.update(self._build_alias(getattr(self, "_render_catalog", None) or {}))
        for p in (getattr(self, "_catalogo", None) or {}).values():
            cod = str(p.get("linea_codigo", "") or "").strip().upper()
            nombre = str(p.get("linea", "") or "").strip().upper()
            if cod and nombre:
                mapa.setdefault(nombre, cod)
        if "linea" in df.columns:
            for val in df["linea"].dropna().astype(str).str.strip().str.upper().unique():
                m = re.match(r"^(01[0-9A-Z]{2,}|[0-9A-Z]{2})\s*-\s*(.+)$", val)
                if m:
                    cod = resolver_codigo_linea(val)
                    if cod:
                        mapa.setdefault(m.group(2).strip().upper(), cod)
        # Un nombre de linea ambiguo (designa a mas de una linea, p.ej.
        # "ACCESORIOS" = 79 y CD) NO debe resolver un codigo por si solo:
        # metia el SKU en la linea equivocada. Se resuelve solo por su codigo.
        for nombre in LINEA_NOMBRES_AMBIGUOS:
            mapa.pop(str(nombre).strip().upper(), None)
        return mapa

    def _apply_prototipo(self, df: pd.DataFrame) -> pd.DataFrame:
        """Linea valida (sufijo) + Val Atencion / Val Pendiente.

        Prototipo VBA: solo ANTICIPO EN LETRAS + APROBADO despachable.
        Granular fila-SKU: se conserva el pedido si tiene >=1 linea valida.
        Reutilizable tras Render (que puede completar linea/grupo y stock).
        Defensivo: si aun no hay derivados (saldo/valor_saldo), los deriva
        de CAN_PEDIDO/CAN_DESPACHO/importe o desactiva el flag sin romper.
        """
        # --- Linea valida (sufijo 2 chars) + Val Atencion / Val Pendiente ---
        # Prototipo VBA: solo ANTICIPO EN LETRAS + APROBADO despachable.
        # Granular fila-SKU: se conserva el pedido si tiene >=1 linea valida.
        validas = self._allowlist_efectiva()
        name_to_code = self._nombre_a_codigo(df)
        from src.core.allowlist import codigo_y_validez

        if "linea" in df.columns or "grupo" in df.columns:
            # Regla UNICA (estricta): la linea manda y debe estar autorizada.
            # El grupo solo se usa cuando la linea viene vacia.
            _codigos: list[str] = []
            _validas: list[bool] = []
            _rescatadas = 0
            for _, r in df.iterrows():
                c, ok = codigo_y_validez(
                    r.get("linea", ""), r.get("grupo", ""), validas, name_to_code
                )
                _codigos.append(c)
                _validas.append(ok)
                # Rescatada: la linea venia como nombre y se resolvio por
                # maestro/semilla (no era un codigo parseable).
                if c and not resolver_codigo_linea(r.get("linea", "")):
                    _rescatadas += 1
            df["linea_cod"] = _codigos
            df["es_linea_valida"] = _validas
            self._linea_rescatadas = _rescatadas
        else:
            df["linea_cod"] = ""
            df["es_linea_valida"] = False
        old_valid = None
        # Diagnostico: cuantas filas quedan fuera de la allowlist.
        self._linea_rechazadas = int((~df["es_linea_valida"].astype(bool)).sum())
        # Origen de la linea (trazabilidad para REVISAR_LINEA).
        raw = (
            df["linea"].astype(str).str.strip().str.upper()
            if "linea" in df.columns
            else pd.Series("", index=df.index)
        )
        cod = (
            df["linea_cod"].astype(str)
            if "linea_cod" in df.columns
            else pd.Series("", index=df.index)
        )
        df["origen_linea"] = "DESCONOCIDA"
        df.loc[raw.eq(""), "origen_linea"] = "VACIA"
        df.loc[raw.ne("") & cod.eq(""), "origen_linea"] = "DESCONOCIDA"
        df.loc[raw.ne("") & cod.ne("") & (raw == cod), "origen_linea"] = "CODIGO"
        df.loc[raw.ne("") & cod.ne("") & (raw != cod), "origen_linea"] = "ALIAS"
        if "linea_id" in df.columns:
            has_id = df["linea_id"].astype(str).str.strip().ne("")
            df.loc[has_id & cod.ne(""), "origen_linea"] = "RENDER"
        cond_ok = (
            df["CONDICION_PAGO"].astype(str).str.strip().str.upper() == CONDICION_PROTOTIPO
            if "CONDICION_PAGO" in df.columns
            else pd.Series(False, index=df.index)
        )
        estado_ok = (
            df["PEDIDO_ESTADO"].astype(str).str.strip().str.upper() == ESTADO_DESPACHABLE
            if "PEDIDO_ESTADO" in df.columns
            else pd.Series(False, index=df.index)
        )
        if "saldo" not in df.columns:
            if "CAN_PEDIDO" in df.columns:
                ped = pd.to_numeric(df.get("CAN_PEDIDO", 0), errors="coerce").fillna(0)
                des = pd.to_numeric(df.get("CAN_DESPACHO", 0), errors="coerce").fillna(0)
                df["saldo"] = (ped - des).round(2)
            else:
                df["es_prototipo"] = False
                df["val_atencion"] = 0.0
                df["val_pendiente"] = 0.0
                return df
        if "valor_saldo" not in df.columns:
            if "PEDIDO_IMPORTE_ARITCULO" in df.columns or "PRE_ARTICULO" in df.columns:
                ped = pd.to_numeric(df.get("CAN_PEDIDO", 0), errors="coerce").fillna(0)
                safe = ped.replace(0, 1)
                if "PEDIDO_IMPORTE_ARITCULO" in df.columns:
                    imp = pd.to_numeric(df["PEDIDO_IMPORTE_ARITCULO"], errors="coerce").fillna(0)
                else:
                    imp = pd.to_numeric(df.get("PRE_ARTICULO", 0), errors="coerce").fillna(0)
                sal = pd.to_numeric(df["saldo"], errors="coerce").fillna(0)
                df["valor_saldo"] = ((sal / safe) * imp).round(2)
            else:
                df["valor_saldo"] = 0.0
        if "stock_real" not in df.columns:
            df["stock_real"] = 0.0
        df["es_prototipo"] = (
            (pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0)
            & df["es_linea_valida"]
            & cond_ok
            & estado_ok
        )
        df["val_atencion"] = df.apply(
            lambda r: (
                round(float(r.get("valor_saldo", 0) or 0), 2)
                if (
                    bool(r.get("es_prototipo", False))
                    and float(r.get("stock_real", 0) or 0) >= float(r.get("saldo", 0) or 0)
                )
                else 0.0
            ),
            axis=1,
        )
        df["val_pendiente"] = df.apply(
            lambda r: (
                round(float(r.get("valor_saldo", 0) or 0), 2)
                if (
                    bool(r.get("es_prototipo", False))
                    and not (float(r.get("stock_real", 0) or 0) >= float(r.get("saldo", 0) or 0))
                )
                else 0.0
            ),
            axis=1,
        )
        # --- Planilla anticipo: dias pendiente (proxy PEDIDO_FECHA) + bucket ---
        # El ERP no trae fecha de planilla; se usa dias_desde_pedido como proxy.
        if "dias_desde_pedido" not in df.columns and "PEDIDO_FECHA" in df.columns:
            _pf = pd.to_datetime(df["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
            _delta = (pd.Timestamp(datetime.now().date()) - _pf).dt.days
            df["dias_desde_pedido"] = _delta.clip(lower=0).fillna(0).astype(int)
        _es_ing = (
            df["NOM_ESTADO_PLANILLA_ANTICIPO"].astype(str).str.strip().str.upper() == "INGRESADO"
            if "NOM_ESTADO_PLANILLA_ANTICIPO" in df.columns
            else pd.Series(False, index=df.index)
        )
        _dias = (
            pd.to_numeric(df["dias_desde_pedido"], errors="coerce").fillna(0).astype(int)
            if "dias_desde_pedido" in df.columns
            else pd.Series(0, index=df.index, dtype=int)
        )
        df["dias_planilla"] = (_dias.where(_es_ing, 0)).astype(int)
        df["planilla_bucket"] = pd.cut(
            df["dias_planilla"],
            bins=[-1, 0, 5, 10, 20, float("inf")],
            labels=["APROBADA", "0-5", "6-10", "11-20", ">20"],
        ).astype(str)
        # --- Cajas estimadas: un_bx=1 suele ser default sin catalogo ---
        df["cajas_estimada"] = (
            pd.to_numeric(df.get("un_bx", 1), errors="coerce").fillna(1) == 1
        ).astype(bool)

        return df

    def _classify_stock(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clasifica el stock por tipo de almacen (VES/121/otros).

        Fuente unica: stock_api_disponible (API de stock en Render).
        El stock del ERP (STK_DISPONIBLE) NO se usa: no es confiable si hubo
        cambios posteriores al reporte. Sin API, el stock es 0 (ysi llega el
        snapshot se re-clasifica con datos reales).
        """
        has_api_stock = "stock_api_disponible" in df.columns

        if has_api_stock:
            # Extraer stock por tipo de almacen desde el API
            def _extract_stock_por_tipo(stock_dict):
                if not isinstance(stock_dict, dict):
                    return 0, 0, 0
                ves = 0
                inspeccion = 0
                otros = 0
                for almacen, cantidad in stock_dict.items():
                    alm_str = str(almacen).upper()
                    cant = float(cantidad) if pd.notna(cantidad) else 0
                    if "VES" in alm_str or alm_str in ("40", "TERMINADOS"):
                        ves += cant
                    elif "121" in alm_str or "INSPECC" in alm_str or "QC" in alm_str:
                        inspeccion += cant
                    else:
                        otros += cant
                return ves, inspeccion, otros

            stock_tipos = df["stock_api_disponible"].apply(_extract_stock_por_tipo)
            df["stock_api_ves"] = stock_tipos.apply(lambda x: x[0])
            df["stock_api_121"] = stock_tipos.apply(lambda x: x[1])
            df["stock_api_otros"] = stock_tipos.apply(lambda x: x[2])
            df["stock_api_total"] = (
                df["stock_api_ves"] + df["stock_api_121"] + df["stock_api_otros"]
            )

            # Stock real para cobertura = solo VES (almacen de venta)
            df["stock_real"] = df["stock_api_ves"]
            df["stock_origen"] = "API"
        else:
            df["stock_real"] = 0
            df["stock_api_ves"] = 0
            df["stock_api_121"] = 0
            df["stock_api_otros"] = 0
            df["stock_api_total"] = 0
            df["stock_origen"] = "SIN API"
        return df

    def _recompute_relevance(self, df: pd.DataFrame) -> pd.DataFrame:
        """Recalcula cobertura, faltante y relevancia (despachable hoy).

        RELEVANTE = con categoria + stock VES > 0 + saldo > 0.
        BLOQUEADO = con saldo pendiente que no se puede despachar hoy.
        """
        if "saldo" not in df.columns:
            return df

        if "stock_real" in df.columns:
            df["cobertura"] = df.apply(
                lambda r: (
                    "Cubierto"
                    if r["stock_real"] >= r["saldo"]
                    else ("Parcial" if r["stock_real"] > 0 else "Sin Stock")
                ),
                axis=1,
            )
            df["faltante"] = (df["saldo"] - df["stock_real"]).clip(lower=0).round(2)
        else:
            df["cobertura"] = "Sin Stock"
            df["faltante"] = df["saldo"]

        categoria = df.get("categoria", pd.Series("", index=df.index)).astype(str).str.strip()
        stock_real = df.get("stock_real", pd.Series(0, index=df.index)).fillna(0)
        saldo = df["saldo"].fillna(0)

        df["es_relevante"] = categoria.ne("") & categoria.ne("nan") & stock_real.gt(0) & saldo.gt(0)
        df["es_bloqueado"] = df["es_relevante"].ne(True) & saldo.gt(0)
        return df

    # ---------------------------------------------------------------
    # Deteccion de incompletos
    # ---------------------------------------------------------------
    def detect_unmatched(self, df: pd.DataFrame) -> pd.DataFrame:
        """Identifica SKUs sin catalogo y sin stock del API.

        Retorna un DataFrame con columnas: SKU, nombre, categoria,
        sin_catalogo (bool), sin_stock_api (bool).

        OJO: un valor NaN es "sin dato" (no es un valor truthy). Antes se
        usaba `not bool(valor)`, que con NaN daba False y dejaba el flag
        `sin_catalogo` siempre apagado.
        """
        if "SKU" not in df.columns:
            return pd.DataFrame()
        rows = []
        for sku, group in df.groupby("SKU"):
            cat_val = group["categoria"].iloc[0] if "categoria" in group else None
            sin_cat = _es_vacio(cat_val)
            sin_stock = bool(group["sin_stock_api"].iloc[0]) if "sin_stock_api" in group else False
            rows.append(
                {
                    "SKU": sku,
                    "nombre": group["NOM_ARTICULO"].iloc[0]
                    if "NOM_ARTICULO" in group
                    else group["nombre_catalogo"].iloc[0]
                    if "nombre_catalogo" in group
                    else "",
                    "categoria": "" if sin_cat else cat_val,
                    "sin_catalogo": sin_cat,
                    "sin_stock_api": sin_stock,
                }
            )
        out = pd.DataFrame(rows)
        if out.empty:
            return out
        return out[out["sin_catalogo"] | out["sin_stock_api"]].reset_index(drop=True)

    # ---------------------------------------------------------------
    # Utilidades
    # ---------------------------------------------------------------
    @staticmethod
    def _find_sku_col(df: pd.DataFrame) -> str | None:
        """Localiza la columna de SKU (ID_ARTICULO) en el DataFrame."""
        for col in ["ID_ARTICULO", "SKU"]:
            if col in df.columns:
                return col
        return None
