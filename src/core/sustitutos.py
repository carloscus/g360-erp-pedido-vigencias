"""Motor de sustitucion de SKUs descontinuados (4 niveles de certeza).

Motivacion: cuando un SKU pedido esta descontinuado y no hay stock, hay que
proponer un reemplazo. El ERP NO trae campo de equivalencia, pero el EAN si
identifica el mismo producto fisico en distintas versiones.

Niveles (el primero que aplica gana):

  NIVEL 1  EAN identico                -> CERTEZA        origen=EAN
  NIVEL 2  linea + grupo + un_bx + jaccard(nombre)>=0.6
                                       -> HOMOLOGO_DIRECTO origen=HEURISTICA
  NIVEL 3  linea + grupo + un_bx       -> MISMO_SEGMENTO origen=HEURISTICA
  NIVEL 4  sin candidato               -> REQUIERE_CRITERIO origen=-

El manual (`sustitutos.csv`) SIEMPRE pisa la heuristica (origen=CURADO).

Validado contra los 3 pares del usuario (02176/02196, 02210/02217,
08032/78456): los tres comparten EAN13 y los resuelve el NIVEL 1.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

# Pesos del score heuristico (solo NIVEL 2/3).
PESO_NOMBRE = 0.45
PESO_PRECIO = 0.30
PESO_STOCK = 0.15

UMBRAL_JACCARD = 0.60

NIVELES = {
    1: "CERTEZA",
    2: "HOMOLOGO_DIRECTO",
    3: "MISMO_SEGMENTO",
    4: "REQUIERE_CRITERIO",
}


def _norm(s) -> str:
    txt = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]", " ", txt.upper())


def _tokens(s) -> set[str]:
    return {w for w in _norm(s).split() if len(w) > 3}


def jaccard(a, b) -> float:
    """Similitud de tokens entre dos nombres (0..1)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _num(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if f != f else f  # NaN check
    except (TypeError, ValueError):
        return default


def _ean_limpio(valor) -> str:
    """Normaliza un EAN: descarta vacios, ceros, 'nan'/'none' y floats.

    El maestro del ERP entrega el EAN como texto pero a veces como numero
    flotante (7754807110280.0) o el literal 'nan'. Sin normalizar, todos los
    SKUs sin EAN colisionan en la clave 'nan' y el NIVEL 1 daria falsos
    positivos (agruparia productos distintos como si fueran el mismo).
    """
    ean = str(valor or "").strip()
    if not ean:
        return ""
    bajo = ean.lower()
    if bajo in ("nan", "none", "nat", "0", "0.0"):
        return ""
    # float tipo '7754807110280.0' -> entero sin decimales
    if re.fullmatch(r"\d+\.0+", ean):
        ean = ean.split(".")[0]
    # solo digitos (un EAN no tiene letras)
    if not ean.isdigit():
        return ""
    return ean


def indice_ean(productos: dict) -> dict[str, list[str]]:
    """Indice inverso EAN -> [SKUs] desde el maestro de productos del ERP.

    Solo considera EAN13 (13 digitos). Se ignora el EAN14: en el maestro es el
    mismo codigo con un '1' antepuesto y duplicaria cada grupo con ruido.
    Un EAN compartido por varios SKUs es la senal dura de que son el mismo
    producto fisico.
    """
    idx: dict[str, list[str]] = {}
    for sku, p in (productos or {}).items():
        ean = _ean_limpio(p.get("ean13"))
        if len(ean) != 13:
            continue
        idx.setdefault(ean, [])
        if str(sku) not in idx[ean]:
            idx[ean].append(str(sku))
    return idx


def cargar_sustitutos_csv(path: str | Path | None) -> dict[str, dict]:
    """Lee el CSV curado manual: sku_origen, sku_reemplazo, motivo, aprobado_por.

    Devuelve {sku_origen: {sku, motivo, aprobado_por}}. Tolerante a faltantes.
    """
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            origen = str(row.get("sku_origen", "") or "").strip()
            destino = str(row.get("sku_reemplazo", "") or "").strip()
            if not origen or not destino:
                continue
            out[origen] = {
                "sku": destino,
                "motivo": str(row.get("motivo", "") or "").strip(),
                "aprobado_por": str(row.get("aprobado_por", "") or "").strip(),
            }
    return out


class MotorSustitutos:
    """Sugiere reemplazos para SKUs descontinuados o sin stock.

    `universo` es el DataFrame de candidatos (columnas: SKU, NOM_ARTICULO,
    linea, grupo, un_bx, precio_unitario, stock_real, producto_descontinuado).
    """

    def __init__(
        self,
        universo,
        productos: dict | None = None,
        curados: dict | None = None,
    ) -> None:
        self.curados = curados or {}
        self._idx_ean = indice_ean(productos or {})
        self._ean_de: dict[str, set[str]] = {}
        for ean, skus in self._idx_ean.items():
            for sku in skus:
                self._ean_de.setdefault(sku, set()).add(ean)
        self._uni = universo if universo is not None else None
        self._filas = {}
        if self._uni is not None and len(self._uni):
            for _, r in self._uni.iterrows():
                self._filas[str(r.get("SKU", "")).strip()] = r

    # -- API -----------------------------------------------------------------
    def sugerir(self, sku: str, contexto: dict | None = None) -> dict:
        """Devuelve la mejor sugerencia para `sku`.

        Salida (siempre las mismas llaves):
          sustituto_sugerido, nivel_confianza, score_sustituto, razon_sustituto,
          sustituto_origen, sustituto_stock
        """
        sku = str(sku or "").strip()
        vacio = {
            "sustituto_sugerido": "",
            "nivel_confianza": "REQUIERE_CRITERIO",
            "score_sustituto": 0.0,
            "razon_sustituto": "sin candidato",
            "sustituto_origen": "",
            "sustituto_stock": 0.0,
        }
        if not sku:
            return vacio

        # Manual SIEMPRE gana.
        cur = self.curados.get(sku)
        if cur:
            return {
                "sustituto_sugerido": cur["sku"],
                "nivel_confianza": "CURADO",
                "score_sustituto": 1.0,
                "razon_sustituto": cur.get("motivo", "curado manual"),
                "sustituto_origen": "CURADO",
                "sustituto_stock": self._stock_de(cur["sku"]),
            }

        origen = self._filas.get(sku)

        # NIVEL 1: EAN identico (otro SKU con el mismo EAN).
        ean_match = self._por_ean(sku)
        if ean_match:
            cand = self._mejor_candidato(ean_match, sku)
            if cand:
                return {
                    "sustituto_sugerido": cand["sku"],
                    "nivel_confianza": NIVELES[1],
                    "score_sustituto": 1.0,
                    "razon_sustituto": f"mismo EAN {cand['ean']}",
                    "sustituto_origen": "EAN",
                    "sustituto_stock": cand["stock"],
                }

        if origen is None:
            return vacio

        # NIVELES 2 y 3 sobre el resto del universo.
        cands = self._candidatos_heuristicos(sku, origen)
        if not cands:
            return vacio
        mejor = cands[0]
        nivel = 2 if mejor["jaccard"] >= UMBRAL_JACCARD else 3
        return {
            "sustituto_sugerido": mejor["sku"],
            "nivel_confianza": NIVELES[nivel],
            "score_sustituto": round(mejor["score"], 3),
            "razon_sustituto": (
                f"lin={mejor['linea']} grp={mejor['grupo']} "
                f"nombre={mejor['jaccard']:.2f} dprecio={mejor['dprecio']:.2f}"
            ),
            "sustituto_origen": "HEURISTICA",
            "sustituto_stock": mejor["stock"],
        }

    # -- internos ------------------------------------------------------------
    def _stock_de(self, sku: str) -> float:
        r = self._filas.get(str(sku).strip())
        return _num(r.get("stock_real") if r is not None else 0)

    def _por_ean(self, sku: str) -> list[str]:
        eans = self._ean_de.get(sku, set())
        out: list[str] = []
        for ean in eans:
            for otro in self._idx_ean.get(ean, []):
                if otro != sku:
                    out.append(otro)
        return out

    def _ean_comun(self, a: str, b: str) -> str:
        comunes = self._ean_de.get(a, set()) & self._ean_de.get(b, set())
        if comunes:
            return next(iter(comunes))
        # Busqueda tolerante (el SKU puede venir con cero a la izquierda o float).
        ca = {str(a).strip(), str(a).strip().lstrip("0"), str(a).strip().zfill(5)}
        cb = {str(b).strip(), str(b).strip().lstrip("0"), str(b).strip().zfill(5)}
        for x in ca:
            for y in cb:
                c = self._ean_de.get(x, set()) & self._ean_de.get(y, set())
                if c:
                    return next(iter(c))
        return ""

    def _mejor_candidato(self, skus: list[str], sku_origen: str) -> dict | None:
        """Entre los SKUs con mismo EAN, prefiere el no descontinuado con stock."""
        mejor = None
        for s in skus:
            r = self._filas.get(s)
            stock = _num(r.get("stock_real") if r is not None else 0)
            desc = bool(r.get("producto_descontinuado", False)) if r is not None else True
            clave = (not desc, stock)
            if mejor is None or clave > mejor["clave"]:
                mejor = {
                    "sku": s,
                    "stock": stock,
                    "clave": clave,
                    "ean": self._ean_comun(s, str(sku_origen)),
                }
        return mejor

    def _candidatos_heuristicos(self, sku: str, origen) -> list[dict]:
        linea = str(origen.get("linea", "") or "").strip().upper()
        grupo = str(origen.get("grupo", "") or "").strip().upper()
        un_bx = _num(origen.get("un_bx"))
        precio = _num(origen.get("precio_unitario"))
        nombre = origen.get("NOM_ARTICULO", "")
        out: list[dict] = []
        for otro, r in self._filas.items():
            if otro == sku:
                continue
            if str(r.get("linea", "") or "").strip().upper() != linea:
                continue
            if str(r.get("grupo", "") or "").strip().upper() != grupo:
                continue
            if _num(r.get("un_bx")) != un_bx:
                continue
            if bool(r.get("producto_descontinuado", False)):
                continue
            stock = _num(r.get("stock_real"))
            if stock <= 0:
                continue
            jac = jaccard(nombre, r.get("NOM_ARTICULO", ""))
            p2 = _num(r.get("precio_unitario"))
            dprecio = 0.0 if not precio else max(0.0, 1 - abs(p2 - precio) / precio)
            score = PESO_NOMBRE * jac + PESO_PRECIO * dprecio + PESO_STOCK * min(stock / 100, 1)
            out.append(
                {
                    "sku": otro,
                    "score": score,
                    "jaccard": jac,
                    "dprecio": dprecio,
                    "stock": stock,
                    "linea": linea,
                    "grupo": grupo,
                }
            )
        out.sort(key=lambda d: d["score"], reverse=True)
        return out


def enriquecer_con_sustitutos(
    df,
    universo=None,
    productos: dict | None = None,
    curados: dict | None = None,
) -> "object":
    """Agrega las columnas de sustituto al DataFrame (solo filas descontinuadas).

    No toca las filas vigentes: `sustituto_sugerido` queda vacio y el nivel
    "" para no ensuciar. Devuelve el mismo DataFrame (mutado por copia).
    """
    import pandas as pd

    if df is None or len(df) == 0:
        return df
    base = universo if universo is not None else df
    motor = MotorSustitutos(base, productos=productos, curados=curados)
    cols = {
        "sustituto_sugerido": "",
        "nivel_confianza": "",
        "score_sustituto": 0.0,
        "razon_sustituto": "",
        "sustituto_origen": "",
        "sustituto_stock": 0.0,
    }
    df = df.copy()
    for c, v in cols.items():
        if c not in df.columns:
            df[c] = v
    desc = df.get("producto_descontinuado")
    if desc is None:
        return df
    mask = desc.fillna(False).astype(bool)
    for idx in df.index[mask]:
        sku = str(df.at[idx, "SKU"] if "SKU" in df.columns else "").strip()
        s = motor.sugerir(sku)
        for c, v in s.items():
            df.at[idx, c] = v
    return df
