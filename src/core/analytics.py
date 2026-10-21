"""
Motor de analisis de vigencias de pedidos CIPSA.

Calcula KPIs globales, segmentaciones (categoria, estado de linea, cliente,
vendedor, almacen, condicion de pago), alertas QC y responde queries de
lenguaje natural basadas en keywords (regex, sin IA).
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from src.core.prioridad import (
    es_complemento,
    etiqueta_prioridad,
    pedido_raiz,
    prioridad_comercial,
    requiere_tramite,
)

# Expresiones de condicion de pago normalizadas (clave -> patron regex)
COND_PAGO_PATTERNS = {
    "CONTADO": r"contado",
    "ANTICIPO EN LETRAS": r"anticipo.*letras|letras.*anticipo",
    "ANTICIPO": r"anticipo",
    "LETRA": r"letra",
    "CANJE": r"canje",
    "FACTURA": r"factura",
    "DESCUENTO PLANILLA": r"planilla",
    "MUESTRA": r"muestra",
}

# Familias normalizadas de condicion de pago (para chips y rankings).
# Orden importa: ANTICIPO "EN LETRAS" -> ANTICIPO, CANJE "CON LETRA" -> CANJE.
COND_FAMILIA_ORDER = [
    "CONTADO",
    "ANTICIPO",
    "CANJE",
    "LETRA",
    "FACTURA",
    "PLANILLA",
    "MUESTRA",
    "OTRO",
]


def normalize_cond_familia(val) -> str:
    """Reduce una condicion de pago del ERP a una familia para chips/rankings.

    Ejemplos: "CONTADO" -> CONTADO, "ANTICIPO EN LETRAS" -> ANTICIPO,
    "CANJE CON LETRA" -> CANJE, "LETRA 45, 60, 75 DIAS" -> LETRA,
    "FACTURA 60 DIAS" -> FACTURA, "DESCUENTO PLANILLA" -> PLANILLA.
    """
    txt = str(val or "").strip().upper()
    if not txt or txt in ("NAN", "NONE", "NAT"):
        return "OTRO"
    for familia, keyword in [
        ("CONTADO", "CONTADO"),
        ("ANTICIPO", "ANTICIPO"),
        ("CANJE", "CANJE"),
        ("LETRA", "LETRA"),
        ("FACTURA", "FACTURA"),
        ("PLANILLA", "PLANILLA"),
        ("MUESTRA", "MUESTRA"),
    ]:
        if keyword in txt:
            return familia
    return "OTRO"


# Palabras gramaticales sin valor de busqueda (tokens del query natural).
QUERY_STOPWORDS = {
    "cuantos",
    "cuanta",
    "cuantas",
    "cuanto",
    "tengo",
    "tenemos",
    "hay",
    "puedo",
    "pueden",
    "podria",
    "podrian",
    "podemos",
    "son",
    "cual",
    "cuales",
    "muestrame",
    "quiero",
    "ver",
    "del",
    "para",
    "con",
    "por",
    "los",
    "las",
    "el",
    "la",
    "de",
    "a",
    "no",
    "en",
    "atender",
    "atender",
    "cajas",
    "cuantas",
    "debo",
    "debemos",
    "pedido",
    "pedidos",
}


def summarize_df(
    df: pd.DataFrame | None,
    stock_col: str = "stock_api_ves",
    saldo_col: str = "saldo",
) -> dict:
    """Resumen agregado de cobertura para un set de lineas.

    Solo considera pendientes (saldo > 0). "Atendible 100%" = una linea cuyo
    stock disponible (VES) alcanza todo su saldo.
    """
    empty = {
        "lineas_total": 0,
        "pendientes": 0,
        "unidades": 0.0,
        "cajas": 0,
        "valor": 0.0,
        "pedidos": 0,
        "clientes": 0,
        "vendedores": 0,
        "atendibles": 0,
        "unidades_atendibles": 0.0,
        "valor_atendible": 0.0,
        "usar_stock": False,
        "atendibles_pct": 0.0,
    }
    if df is None or len(df) == 0 or saldo_col not in df.columns:
        return empty

    pend = df[df[saldo_col] > 0]
    out = dict(empty)
    out["lineas_total"] = len(df)
    out["pendientes"] = len(pend)
    if len(pend) == 0:
        return out
    out["unidades"] = float(pend[saldo_col].sum())
    out["cajas"] = int(pend["cajas"].sum()) if "cajas" in pend else 0
    out["valor"] = float(pend["valor_saldo"].sum()) if "valor_saldo" in pend else 0.0
    out["pedidos"] = (
        int(pend["ID_PEDIDO"].nunique())
        if "ID_PEDIDO" in pend
        else int(pend["NRO_DOCUMENTO"].nunique())
        if "NRO_DOCUMENTO" in pend
        else 0
    )
    out["clientes"] = int(pend["COD_CLIENTE"].nunique()) if "COD_CLIENTE" in pend else 0
    out["vendedores"] = int(pend["ID_VENDEDOR"].nunique()) if "ID_VENDEDOR" in pend else 0

    stock = stock_col if stock_col in pend.columns else None
    if stock is None and "STK_DISPONIBLE" in pend.columns:
        stock = "STK_DISPONIBLE"
    if stock is None:
        return out
    out["usar_stock"] = True
    seria_atendible = pd.to_numeric(pend[stock], errors="coerce").fillna(0) >= pend[saldo_col]
    atend = pend[seria_atendible]
    out["atendibles"] = len(atend)
    out["unidades_atendibles"] = float(atend[saldo_col].sum())
    out["valor_atendible"] = float(atend["valor_saldo"].sum()) if "valor_saldo" in pend else 0.0
    out["atendibles_pct"] = round(100.0 * len(atend) / len(pend), 1)
    return out


class PedidosAnalytics:
    """Analiza un DataFrame de vigencias ya enriquecido y con campos derivados."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.copy()
        # Normalizacion numerica defensiva (por si faltan campos derivados)
        self._ensure_numeric(
            ["CAN_PEDIDO", "CAN_DESPACHO", "PRE_ARTICULO", "saldo", "cajas", "valor_saldo"]
        )
        self._priority_cache: dict[tuple[str, int], pd.DataFrame] = {}
        self._qc_cache: dict[int, pd.DataFrame] = {}

    # ---------------------------------------------------------------
    # Utilidades internas
    # ---------------------------------------------------------------
    @staticmethod
    def _ensure_numeric(columns: list[str]) -> None:
        pass

    def _get_col(self, *names: str) -> str | None:
        """Retorna la primera columna existente entre los nombres dados."""
        for n in names:
            if n in self.df.columns:
                return n
        return None

    def _cat_col(self) -> str:
        return self._get_col("categoria", "CATEGORIA") or "categoria"

    def _estado_col(self) -> str:
        return self._get_col("estado_linea", "ESTADO_LINEA") or "estado_linea"

    def _almacen_col(self) -> str:
        return self._get_col("NOM_ALMACEN") or "NOM_ALMACEN"

    def _cliente_col(self) -> str:
        return self._get_col("COD_CLIENTE") or "COD_CLIENTE"

    def _cliente_nom_col(self) -> str:
        return self._get_col("NOM_CLIENTE") or "NOM_CLIENTE"

    def _vendedor_col(self) -> str:
        return self._get_col("ID_VENDEDOR") or "ID_VENDEDOR"

    def _vendedor_nom_col(self) -> str:
        return self._get_col("NOM_VENDEDOR") or "NOM_VENDEDOR"

    def _cond_col(self) -> str:
        return self._get_col("CONDICION_PAGO") or "CONDICION_PAGO"

    def _cond_familia_col(self) -> str | None:
        return self._get_col("cond_familia")

    def _sku_col(self) -> str:
        return self._get_col("SKU", "ID_ARTICULO") or "SKU"

    def _nombre_col(self) -> str:
        return self._get_col("NOM_ARTICULO", "nombre_catalogo") or "NOM_ARTICULO"

    # ---------------------------------------------------------------
    # KPIs globales
    # ---------------------------------------------------------------
    def get_kpis(self) -> dict:
        """Retorna KPIs globales del DataFrame con calculos CIPSA.

        Incluye: saldo, vigencia, stock, precio unitario, cobertura, faltante.
        """
        pedido = self._sum("CAN_PEDIDO")
        despacho = self._sum("CAN_DESPACHO")
        saldo = self._sum("saldo") if "saldo" in self.df else pedido - despacho
        cajas = self._sum("cajas") if "cajas" in self.df else None
        valor = self._sum("valor_saldo") if "valor_saldo" in self.df else None
        valor_atendido = self._sum("valor_atendido") if "valor_atendido" in self.df else None

        kpis = {
            "total_items": len(self.df),
            "total_pedido": round(pedido, 2),
            "total_despachado": round(despacho, 2),
            "saldo_total": round(saldo, 2),
            "cajas_total": round(cajas, 2) if cajas is not None else None,
            "valor_total": round(valor, 2) if valor is not None else None,
            "valor_atendido": round(valor_atendido, 2) if valor_atendido is not None else None,
            "n_clientes": int(self.df[self._cliente_col()].nunique())
            if self._cliente_col() in self.df
            else 0,
            "n_vendedores": int(self.df[self._vendedor_col()].nunique())
            if self._vendedor_col() in self.df
            else 0,
            "n_almacenes": int(self.df[self._almacen_col()].nunique())
            if self._almacen_col() in self.df
            else 0,
        }

        # Columnas derivadas opcionales
        if "vigencia" in self.df:
            kpis["vigencia_promedio"] = round(float(self.df["vigencia"].mean()), 1)
        if "stock_api_total" in self.df:
            kpis["stock_total"] = round(float(self.df["stock_api_total"].sum()), 0)
        if "stock_api_ves" in self.df:
            kpis["stock_ves"] = round(float(self.df["stock_api_ves"].sum()), 0)
        if "stock_api_121" in self.df:
            kpis["stock_121"] = round(float(self.df["stock_api_121"].sum()), 0)
        if "stock_api_otros" in self.df:
            kpis["stock_otros"] = round(float(self.df["stock_api_otros"].sum()), 0)
        if "precio_unitario" in self.df:
            kpis["precio_promedio"] = round(float(self.df["precio_unitario"].mean()), 2)
        if "faltante" in self.df:
            kpis["faltante_total"] = round(float(self.df["faltante"].sum()), 0)
        if "cobertura" in self.df:
            kpis["cubiertos"] = int((self.df["cobertura"] == "Cubierto").sum())
            kpis["sin_stock"] = int((self.df["cobertura"] == "Sin Stock").sum())
        if "estado_vigencia" in self.df:
            kpis["vencidos"] = int((self.df["estado_vigencia"] == "VENCIDO").sum())
            kpis["por_vencer"] = int((self.df["estado_vigencia"] == "POR VENCER").sum())

        return kpis

    def _sum(self, col: str) -> float:
        if col not in self.df.columns:
            return 0.0
        return float(pd.to_numeric(self.df[col], errors="coerce").fillna(0).sum())

    def get_priority_summary(self, dimension: str = "cliente", top: int = 8) -> pd.DataFrame:
        """Ranking compacto para decidir que se debe entregar primero."""
        cache_key = (dimension, top)
        if cache_key in self._priority_cache:
            return self._priority_cache[cache_key].copy()
        column_map = {
            "cliente": ["COD_CLIENTE", "NOM_CLIENTE"],
            "pedido": ["ID_PEDIDO", "NRO_DOCUMENTO", "ID_DOCUMENTO"],
            "vendedor": ["ID_VENDEDOR", "NOM_VENDEDOR"],
            "almacen": ["NOM_ALMACEN"],
            "linea": ["linea", "estado_linea"],
            "categoria": ["categoria"],
        }
        columns = [c for c in column_map.get(dimension, []) if c in self.df.columns]
        if not columns:
            return pd.DataFrame()
        group = self.df.groupby(columns, dropna=False, sort=False)
        out = group.size().rename("items").to_frame()
        for source, label in [
            ("CAN_PEDIDO", "pedido"),
            ("CAN_DESPACHO", "despachado"),
            ("saldo", "saldo"),
            ("cajas", "cajas"),
            ("valor_saldo", "valor"),
        ]:
            if source in self.df:
                out[label] = group[source].sum()
        out = out.reset_index()
        if "dias_desde_pedido" in self.df:
            out["dias"] = group["dias_desde_pedido"].max().to_numpy()
        pedido = pd.to_numeric(out.get("pedido", 0), errors="coerce").fillna(0)
        saldo = pd.to_numeric(out.get("saldo", 0), errors="coerce").fillna(0)
        out["pct_pendiente"] = (saldo / pedido.replace(0, 1) * 100).round(1)
        result = (
            out.sort_values(["saldo", "valor"], ascending=False).head(top).reset_index(drop=True)
        )
        self._priority_cache[cache_key] = result
        return result.copy()

    def get_by_linea(self, top: int | None = None) -> pd.DataFrame:
        return self.get_priority_summary("linea", top or len(self.df))

    def get_by_pedido(self, top: int | None = None) -> pd.DataFrame:
        return self.get_priority_summary("pedido", top or len(self.df))

    # ---------------------------------------------------------------
    # Segmentaciones
    # ---------------------------------------------------------------
    def get_by_category(self) -> pd.DataFrame:
        """Agrupa por categoria con items, pedido, despachado, saldo, valor, cajas."""
        col = self._cat_col()
        if col not in self.df.columns:
            return pd.DataFrame()
        g = self.df.groupby(col, dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in self.df else 0,
                "desp": g["CAN_DESPACHO"].sum() if "CAN_DESPACHO" in self.df else 0,
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
                "cajas": g["cajas"].sum() if "cajas" in self.df else 0,
            }
        )
        out.index.name = col
        return out.reset_index()

    def get_by_estado_linea(self, categoria: str | None = None) -> pd.DataFrame:
        """Desglosa por estado_linea (NUEVO/TRADICIONAL/IMPORTADO/vacio)."""
        col = self._estado_col()
        df = self.df
        if categoria:
            cat_col = self._cat_col()
            if cat_col in df.columns:
                df = df[df[cat_col] == categoria]
        if col not in df.columns:
            return pd.DataFrame()
        g = df.groupby(col, dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in df else 0,
                "saldo": g["saldo"].sum() if "saldo" in df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in df else 0,
                "cajas": g["cajas"].sum() if "cajas" in df else 0,
            }
        )
        out.index.name = col
        out = out.reset_index()
        out = out.sort_values("saldo", ascending=False).reset_index(drop=True)
        return out

    def get_by_cliente(self, top: int | None = None) -> pd.DataFrame:
        """Ranking de clientes por saldo (units) y valor S/."""
        cid, cn = self._cliente_col(), self._cliente_nom_col()
        g = self.df.groupby([cid, cn], dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
                "cajas": g["cajas"].sum() if "cajas" in self.df else 0,
            }
        ).reset_index()
        out = out.sort_values("saldo", ascending=False)
        if top:
            out = out.head(top)
        return out.reset_index(drop=True)

    def get_by_vendedor(self) -> pd.DataFrame:
        """Resumen por vendedor con vigencias totales y disponible cubierto por VES.

        Disponible cubierto = min(stock_VES, saldo) — solo VES es despachable.
        Stock 121 (QC inspección) y otros (129, auxiliares) se muestran como info
        adicional pero NO entran en la cobertura real.
        """
        vid, vn = self._vendedor_col(), self._vendedor_nom_col()
        g = self.df.groupby([vid, vn], dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in self.df else 0,
                "desp": g["CAN_DESPACHO"].sum() if "CAN_DESPACHO" in self.df else 0,
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
                "cajas": g["cajas"].sum() if "cajas" in self.df else 0,
            }
        ).reset_index()
        # Stock por tipo de almacen (agrupado por vendedor, primer valor por SKU)
        if "stock_api_ves" in self.df.columns and vid in out.columns:
            ves = self.df.groupby(vid)["stock_api_ves"].first()
            out["stock_VES"] = (
                out[vid].astype(str).map({str(k): float(v) for k, v in ves.items()}).fillna(0)
            )
        else:
            out["stock_VES"] = 0
        if "stock_api_121" in self.df.columns and vid in out.columns:
            s121 = self.df.groupby(vid)["stock_api_121"].first()
            out["stock_121"] = (
                out[vid].astype(str).map({str(k): float(v) for k, v in s121.items()}).fillna(0)
            )
        else:
            out["stock_121"] = 0
        if "stock_api_otros" in self.df.columns and vid in out.columns:
            sotros = self.df.groupby(vid)["stock_api_otros"].first()
            out["stock_otros"] = (
                out[vid].astype(str).map({str(k): float(v) for k, v in sotros.items()}).fillna(0)
            )
        else:
            out["stock_otros"] = 0
        # Disponible cubierto = min(VES, saldo) — VES es unico stock despachable
        out["disp_cub_VES"] = out.apply(
            lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
        )
        out["stock_total_info"] = out["stock_VES"] + out["stock_121"] + out["stock_otros"]
        return out.sort_values("saldo", ascending=False).reset_index(drop=True)

    def get_clientes_by_vendedor(self, vendedor_id) -> pd.DataFrame:
        """Clientes de un vendedor especifico con vigencias y disponible cubierto VES.

        Retorna columnas: COD_CLIENTE, NOM_CLIENTE, items, pedido, despacho,
        saldo, cajas, valor, stock_VES, stock_121, stock_otros, disp_cub_VES
        (min(stock_VES, saldo)).
        """
        vid = self._vendedor_col()
        cid, cn = self._cliente_col(), self._cliente_nom_col()
        if vid not in self.df.columns:
            return pd.DataFrame()
        sub = self.df[self.df[vid].astype(str) == str(vendedor_id)]
        if sub.empty:
            return pd.DataFrame()
        g = sub.groupby([cid, cn], dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in sub else 0,
                "despacho": g["CAN_DESPACHO"].sum() if "CAN_DESPACHO" in sub else 0,
                "saldo": g["saldo"].sum() if "saldo" in sub else 0,
                "cajas": g["cajas"].sum() if "cajas" in sub else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in sub else 0,
            }
        ).reset_index()
        # Stock por tipo de almacen (primer valor por SKU dentro del cliente)
        if "stock_api_ves" in sub.columns and cid in sub.columns:
            ves = sub.groupby(cid)["stock_api_ves"].first()
            out["stock_VES"] = (
                out[cid].astype(str).map({str(k): float(v) for k, v in ves.items()}).fillna(0)
            )
        else:
            out["stock_VES"] = 0
        if "stock_api_121" in sub.columns and cid in sub.columns:
            s121 = sub.groupby(cid)["stock_api_121"].first()
            out["stock_121"] = (
                out[cid].astype(str).map({str(k): float(v) for k, v in s121.items()}).fillna(0)
            )
        else:
            out["stock_121"] = 0
        if "stock_api_otros" in sub.columns and cid in sub.columns:
            sotros = sub.groupby(cid)["stock_api_otros"].first()
            out["stock_otros"] = (
                out[cid].astype(str).map({str(k): float(v) for k, v in sotros.items()}).fillna(0)
            )
        else:
            out["stock_otros"] = 0
        # Disponible cubierto = min(VES, saldo)
        out["disp_cub_VES"] = out.apply(
            lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
        )
        out["stock_total_info"] = out["stock_VES"] + out["stock_121"] + out["stock_otros"]
        return out.sort_values("saldo", ascending=False).reset_index(drop=True)

    def get_vendedores_by_cliente(self, cliente_id) -> pd.DataFrame:
        """Vendedores que han atendido a un cliente especifico."""
        vid, vn = self._vendedor_col(), self._vendedor_nom_col()
        cid = self._cliente_col()
        if cid not in self.df.columns or vid not in self.df.columns:
            return pd.DataFrame()
        sub = self.df[self.df[cid].astype(str) == str(cliente_id)]
        if sub.empty:
            return pd.DataFrame()
        g = sub.groupby([vid, vn], dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in sub else 0,
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
            }
        ).reset_index()
        return out.sort_values("saldo", ascending=False).reset_index(drop=True)

    def get_pedidos_by_cliente(self, cliente_id) -> pd.DataFrame:
        """Pedidos de un cliente agrupados por ID_PEDIDO (clave operativa).

        Retorna columnas: ID_PEDIDO, NRO_DOCUMENTO (OC), NOM_CLIENTE, items,
        pedido, despacho, saldo, cajas, por_atendido, estado, valor,
        stock_VES, stock_121, stock_otros, disp_cub_VES.
        """
        cid = self._cliente_col()
        cn = self._cliente_nom_col()
        if cid not in self.df.columns:
            return pd.DataFrame()
        sub = self.df[self.df[cid].astype(str) == str(cliente_id)]
        if sub.empty:
            return pd.DataFrame()
        id_col = (
            "ID_PEDIDO"
            if "ID_PEDIDO" in sub.columns
            else ("NRO_DOCUMENTO" if "NRO_DOCUMENTO" in sub.columns else None)
        )
        if id_col is None:
            return pd.DataFrame()
        g = sub.groupby(id_col, dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in sub else 0,
                "despacho": g["CAN_DESPACHO"].sum() if "CAN_DESPACHO" in sub else 0,
                "saldo": g["saldo"].sum() if "saldo" in sub else 0,
                "cajas": g["cajas"].sum() if "cajas" in sub else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in sub else 0,
                "valor_pedido": g["valor_pedido"].sum() if "valor_pedido" in sub else 0,
                "valor_atendido": g["valor_atendido"].sum() if "valor_atendido" in sub else 0,
            }
        ).reset_index()
        out["por_atendido"] = (
            pd.to_numeric(out["despacho"], errors="coerce").fillna(0)
            / pd.to_numeric(out["pedido"], errors="coerce").replace(0, 1)
            * 100
        ).round(1)
        if "valor_pedido" in out.columns and "valor_atendido" in out.columns:
            out["por_atendido_valor"] = (
                pd.to_numeric(out["valor_atendido"], errors="coerce").fillna(0)
                / pd.to_numeric(out["valor_pedido"], errors="coerce").replace(0, 1)
                * 100
            ).round(1)
            out.loc[out["valor_pedido"] == 0, "por_atendido_valor"] = 0.0
        else:
            out["por_atendido_valor"] = 0.0
        if "estado_linea" in sub.columns:
            valido = sub["estado_linea"].fillna("").astype(str).str.strip().ne("")
            out["lineas_validas"] = (
                valido.groupby(sub[id_col])
                .sum()
                .reindex(out[id_col], fill_value=0)
                .astype(int)
                .values
            )
        else:
            out["lineas_validas"] = out["items"]

        def _estado(r):
            pct = float(r.get("por_atendido", 0))
            if pct >= 100.0:
                return "100%"
            if pct > 0.0:
                return "PARCIAL"
            return "PENDIENTE"

        out["estado"] = out.apply(_estado, axis=1)
        if cn in sub.columns:
            out[cn] = sub[cn].iloc[0]
        if "NRO_DOCUMENTO" in sub.columns and id_col != "NRO_DOCUMENTO":
            doc_first = sub.groupby(id_col, dropna=False)["NRO_DOCUMENTO"].first()
            out["NRO_DOCUMENTO"] = out[id_col].map(doc_first)
        if "PEDIDO_ESTADO" in sub.columns and "PEDIDO_ESTADO" not in out:
            st_first = sub.groupby(id_col, dropna=False)["PEDIDO_ESTADO"].first()
            out["PEDIDO_ESTADO"] = out[id_col].map(st_first)
        if "CONDICION_PAGO" in sub.columns:
            cond_first = sub.groupby(id_col, dropna=False)["CONDICION_PAGO"].first()
            out["CONDICION_PAGO"] = out[id_col].map(cond_first)
        # Stock por tipo de almacen por pedido (primer valor por ID_PEDIDO)
        if "stock_api_ves" in sub.columns and id_col in sub.columns:
            ves = sub.groupby(id_col)["stock_api_ves"].first()
            out["stock_VES"] = (
                out[id_col].astype(str).map({str(k): float(v) for k, v in ves.items()}).fillna(0)
            )
        else:
            out["stock_VES"] = 0
        if "stock_api_121" in sub.columns and id_col in sub.columns:
            s121 = sub.groupby(id_col)["stock_api_121"].first()
            out["stock_121"] = (
                out[id_col].astype(str).map({str(k): float(v) for k, v in s121.items()}).fillna(0)
            )
        else:
            out["stock_121"] = 0
        if "stock_api_otros" in sub.columns and id_col in sub.columns:
            sotros = sub.groupby(id_col)["stock_api_otros"].first()
            out["stock_otros"] = (
                out[id_col].astype(str).map({str(k): float(v) for k, v in sotros.items()}).fillna(0)
            )
        else:
            out["stock_otros"] = 0
        out["disp_cub_VES"] = out.apply(
            lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
        )
        out["stock_total_info"] = out["stock_VES"] + out["stock_121"] + out["stock_otros"]
        return out.sort_values("saldo", ascending=False).reset_index(drop=True)

    def get_skus_by_pedido(self, pedido_doc) -> pd.DataFrame:
        """SKUs de un pedido con vigencias y disponible cubierto VES.

        Retorna columnas: SKU, NOM_ARTICULO, saldo, stock_VES, stock_121,
        stock_otros, disp_cub_VES, stock_total_info.
        """
        doc_col = "NRO_DOCUMENTO" if "NRO_DOCUMENTO" in self.df.columns else None
        if doc_col is None:
            return pd.DataFrame()
        sub = self.df[self.df[doc_col].astype(str) == str(pedido_doc)].copy()
        if sub.empty:
            return pd.DataFrame()
        sku_col = self._sku_col()
        nom_col = self._nombre_col()
        group_cols = [sku_col]
        if nom_col in sub.columns and nom_col != sku_col:
            group_cols.append(nom_col)
        agg = {"saldo": ("saldo", "sum") if "saldo" in sub.columns else ("CAN_PEDIDO", "sum")}
        if "cajas" in sub.columns:
            agg["cajas"] = ("cajas", "sum")
        grouped = sub.groupby(group_cols, dropna=False).agg(**agg).reset_index()
        # Stock por SKU — mismo SKU en todo el pedido, tomar primer valor
        if "stock_api_ves" in sub.columns and sku_col in sub.columns:
            ves = sub.groupby(sku_col)["stock_api_ves"].first()
            grouped["stock_VES"] = (
                grouped[sku_col]
                .astype(str)
                .map({str(k): float(v) for k, v in ves.items()})
                .fillna(0)
            )
        else:
            grouped["stock_VES"] = 0
        if "stock_api_121" in sub.columns and sku_col in sub.columns:
            s121 = sub.groupby(sku_col)["stock_api_121"].first()
            grouped["stock_121"] = (
                grouped[sku_col]
                .astype(str)
                .map({str(k): float(v) for k, v in s121.items()})
                .fillna(0)
            )
        else:
            grouped["stock_121"] = 0
        if "stock_api_otros" in sub.columns and sku_col in sub.columns:
            sotros = sub.groupby(sku_col)["stock_api_otros"].first()
            grouped["stock_otros"] = (
                grouped[sku_col]
                .astype(str)
                .map({str(k): float(v) for k, v in sotros.items()})
                .fillna(0)
            )
        else:
            grouped["stock_otros"] = 0
        grouped["disp_cub_VES"] = grouped.apply(
            lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
        )
        grouped["stock_total_info"] = (
            grouped["stock_VES"] + grouped["stock_121"] + grouped["stock_otros"]
        )
        grouped = grouped.sort_values("saldo", ascending=False).reset_index(drop=True)
        return grouped

    def get_lineas_por_pedido(self) -> pd.DataFrame:
        """Agregado por Pedido x SKU con estado de despacho.

        Muestra por cada combinacion Pedido-SKU:
        - Vendedor, Cliente, SKU, Producto
        - Pedido total, Despachado, Pendiente (saldo)
        - Porcentaje atendido (%)
        - Estado: '100%' | 'PARCIAL' | 'PENDIENTE'
        - Stock VES, Stock 121, Disp. Cubierto (VES-only)
        """
        doc_col = "NRO_DOCUMENTO" if "NRO_DOCUMENTO" in self.df.columns else None
        sku_col = self._sku_col()
        if doc_col is None or sku_col is None:
            return pd.DataFrame()
        sub = self.df.copy()
        group_cols = [doc_col, sku_col]
        nom_col = self._nombre_col()
        if nom_col in sub.columns and nom_col != sku_col:
            group_cols.append(nom_col)
        # Traer vendedores y clientes (primera fila por grupo)
        extra = {}
        for col, label in [
            ("ID_VENDEDOR", "ID_VENDEDOR"),
            ("NOM_VENDEDOR", "NOM_VENDEDOR"),
            ("COD_CLIENTE", "COD_CLIENTE"),
            ("NOM_CLIENTE", "NOM_CLIENTE"),
        ]:
            if col in sub.columns:
                extra[col] = (col, "first")
        agg = {
            "pedido": ("CAN_PEDIDO", "sum") if "CAN_PEDIDO" in sub.columns else (doc_col, "size"),
            "despacho": ("CAN_DESPACHO", "sum")
            if "CAN_DESPACHO" in sub.columns
            else (doc_col, "size"),
            "saldo": ("saldo", "sum") if "saldo" in sub.columns else ("CAN_PEDIDO", lambda x: 0),
            "cajas": ("cajas", "sum") if "cajas" in sub.columns else (doc_col, lambda x: 0),
            "valor": ("valor_saldo", "sum")
            if "valor_saldo" in sub.columns
            else (doc_col, lambda x: 0),
        }
        agg.update(extra)
        grouped = sub.groupby(group_cols, dropna=False).agg(**agg).reset_index()
        # Porcentaje atendido
        grouped["por_atendido"] = (
            pd.to_numeric(grouped["despacho"], errors="coerce").fillna(0)
            / pd.to_numeric(grouped["pedido"], errors="coerce").replace(0, 1)
            * 100
        ).round(1)

        # Estado de cobertura
        def _estado(row):
            pct = float(row.get("por_atendido", 0))
            if pct >= 100.0:
                return "100%"
            if pct > 0.0:
                return "PARCIAL"
            return "PENDIENTE"

        grouped["estado"] = grouped.apply(_estado, axis=1)
        # Stock por tipo de almacen (agrupado por DOC+SKU)
        for stock_col, out_col in [
            ("stock_api_ves", "stock_VES"),
            ("stock_api_121", "stock_121"),
            ("stock_api_otros", "stock_otros"),
        ]:
            if stock_col in sub.columns:
                g = sub.groupby(group_cols)[stock_col].first()
                grouped[out_col] = grouped.apply(
                    lambda r: float(g.get(tuple(r[[*group_cols]]), 0)), axis=1
                )
            else:
                grouped[out_col] = 0
        # Disponible cubierto = min(VES, saldo)
        grouped["disp_cub_VES"] = grouped.apply(
            lambda r: float(min(max(r["stock_VES"], 0), max(r["saldo"], 0))), axis=1
        )
        grouped["valor_saldo"] = grouped["valor"]
        grouped = grouped.sort_values("saldo", ascending=False).reset_index(drop=True)
        return grouped

    def get_lineas_filtradas(
        self,
        vendedor_id=None,
        cliente_id=None,
        sku=None,
    ) -> pd.DataFrame:
        """Devuelve las lineas de pedido filtradas por los criterios dados.

        Cada llamada sin filtro devuelve el dataset completo.
        Usado para el drill-down: Vendedor -> Cliente -> Linea.
        """
        df = self.df
        if vendedor_id is not None and self._vendedor_col() in df.columns:
            df = df[df[self._vendedor_col()].astype(str) == str(vendedor_id)]
        if cliente_id is not None and self._cliente_col() in df.columns:
            df = df[df[self._cliente_col()].astype(str) == str(cliente_id)]
        if sku is not None and self._sku_col() in df.columns:
            df = df[df[self._sku_col()].astype(str) == str(sku)]
        return df.reset_index(drop=True)

    def get_by_almacen(self) -> pd.DataFrame:
        """Resumen por almacen: items, pedido, saldo, cajas y valor.

        Degradacion elegante: retorna DataFrame vacio si no hay columna de almacen.
        """
        col = self._almacen_col()
        if col not in self.df.columns:
            return pd.DataFrame(
                columns=["NOM_ALMACEN", "items", "pedido", "saldo", "cajas", "valor"]
            )
        agg = {
            "items": ("CAN_PEDIDO", "size"),
            "pedido": ("CAN_PEDIDO", "sum"),
            "saldo": ("saldo", "sum") if "saldo" in self.df else ("CAN_PEDIDO", "sum"),
            "cajas": ("cajas", "sum") if "cajas" in self.df else ("CAN_PEDIDO", lambda x: 0),
            "valor": ("valor_saldo", "sum")
            if "valor_saldo" in self.df
            else ("CAN_PEDIDO", lambda x: 0),
        }
        return (
            self.df.groupby(col, dropna=False)
            .agg(**agg)
            .reset_index()
            .rename(columns={col: "NOM_ALMACEN"})
            .sort_values("saldo", ascending=False)
            .reset_index(drop=True)
        )

    def get_stock_por_almacen(self) -> pd.DataFrame:
        """Distribucion de stock por almacen en columnas (para analisis de traslados).

        Muestra por cada SKU:
        - stock en VES (disponible para venta)
        - stock en 121 (inspeccion QC)
        - stock en otros almacenes
        - cobertura y necesidad de traslado
        """
        sku_col = self._sku_col()
        nom_col = self._nombre_col()

        group_cols = [sku_col]
        agg = {
            "saldo": ("saldo", "sum"),
        }
        if nom_col in self.df.columns:
            agg["nombre"] = (nom_col, "first")

        # Determinar qué columnas de stock usar
        if "stock_api_ves" in self.df.columns:
            agg["stock_VES"] = ("stock_api_ves", "sum")
            agg["stock_121"] = ("stock_api_121", "sum")
            agg["stock_otros"] = ("stock_api_otros", "sum")
            agg["stock_total"] = ("stock_api_total", "sum")
        elif "stock_real" in self.df.columns:
            agg["stock_VES"] = ("stock_real", "sum")
            agg["stock_121"] = ("stock_real", lambda x: 0)
            agg["stock_otros"] = ("stock_real", lambda x: 0)
            agg["stock_total"] = ("stock_real", "sum")
        else:
            agg["stock_VES"] = ("saldo", lambda x: 0)
            agg["stock_121"] = ("saldo", lambda x: 0)
            agg["stock_otros"] = ("saldo", lambda x: 0)
            agg["stock_total"] = ("saldo", lambda x: 0)

        result = self.df.groupby(group_cols, dropna=False).agg(**agg).reset_index()

        # Calcular cobertura y necesidad de traslado
        result["cobertura"] = result.apply(
            lambda r: (
                "Cubierto"
                if r["stock_VES"] >= r["saldo"]
                else ("Parcial" if r["stock_VES"] > 0 else "Sin Stock")
            ),
            axis=1,
        )
        result["necesita_traslado"] = result.apply(
            lambda r: (
                "SI"
                if r["cobertura"] == "Sin Stock" and (r["stock_121"] > 0 or r["stock_otros"] > 0)
                else (
                    "PARCIAL"
                    if r["cobertura"] == "Parcial" and (r["stock_121"] > 0 or r["stock_otros"] > 0)
                    else "NO"
                )
            ),
            axis=1,
        )
        result["faltante"] = (result["saldo"] - result["stock_VES"]).clip(lower=0)

        return result.sort_values("faltante", ascending=False).reset_index(drop=True)

    def get_by_condition_payment(self) -> pd.DataFrame:
        """Agrupa por CONDICION_PAGO mostrando items, unidades y valor."""
        cond = self._cond_col()
        if cond not in self.df.columns:
            return pd.DataFrame()
        g = self.df.groupby(cond, dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in self.df else 0,
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
            }
        ).reset_index()
        return out.sort_values("valor", ascending=False).reset_index(drop=True)

    # ---------------------------------------------------------------
    # Alertas QC
    # ---------------------------------------------------------------
    def get_qc_alerts(self, threshold: int = 5000) -> pd.DataFrame:
        """SKUs con saldo > threshold en el almacen VES.

        Son candidatos a solicitud de liberacion desde QC (almacen 121).
        Solo alerta: no ejecuta traslados.
        """
        if threshold in self._qc_cache:
            return self._qc_cache[threshold].copy()
        df = self.df
        alm_col = self._almacen_col()
        if alm_col not in df.columns:
            return pd.DataFrame()
        ves = df[df[alm_col].astype(str).str.upper().str.contains("VES", na=False)]
        if "saldo" not in ves:
            return pd.DataFrame()
        alerts = ves[ves["saldo"] > threshold].copy()
        alerts = alerts.sort_values("saldo", ascending=False)
        cols = {
            "SKU": self._sku_col(),
            "nombre": self._nombre_col(),
            "categoria": self._cat_col(),
        }
        subset = []
        for src in cols.values():
            if src in alerts.columns:
                subset.append(src)
        if not subset:
            subset = ["saldo", "cajas"]
        out = alerts[subset + [c for c in ["saldo", "cajas"] if c in alerts.columns]].copy()
        out = out.drop_duplicates(subset=subset).reset_index(drop=True)
        self._qc_cache[threshold] = out
        return out.copy()

    # ---------------------------------------------------------------
    # Query natural (keywords)
    # ---------------------------------------------------------------
    def query_natural(self, text: str) -> tuple[pd.DataFrame, str]:
        """Busca por cliente, pedido, SKU, vendedor, almacen, linea y categoria."""
        text = (text or "").strip()
        if not text:
            return self.df, "Vista completa"
        lower = text.lower()
        mask = pd.Series(True, index=self.df.index)
        filters: list[str] = []

        # Frase "no aprobadas / sin aprobar" -> estado distinto de APROBADO
        es_no_aprobado = bool(
            re.search(
                r"no\s+(?:est[aá]n\s+)?aprobad|sin\s+aprobar|pendiente\s+de\s+aprob",
                lower,
                re.IGNORECASE,
            )
        )
        if es_no_aprobado and "PEDIDO_ESTADO" in self.df:
            mask &= ~(self.df["PEDIDO_ESTADO"].astype(str).str.strip().str.upper() == "APROBADO")
            filters.append("estado!=APROBADO")

        def exact_filter(pattern: str, column_names: list[str], label: str) -> None:
            nonlocal mask
            match = re.search(pattern, lower)
            if not match:
                return
            token = match.group(1).strip()
            columns = [c for c in column_names if c in self.df.columns]
            if not columns:
                return
            local = pd.Series(False, index=self.df.index)
            for col in columns:
                local |= (
                    self.df[col].astype(str).str.contains(token, case=False, na=False, regex=False)
                )
            mask &= local
            filters.append(f"{label}={token}" if token.isdigit() else f"{label}~'{token}'")

        exact_filter(
            r"(?:cliente|clie)[:\s]+([^,;]+?)(?=\s+(?:pedido|oc|vendedor|almacen|linea|categoria)\b|$)",
            ["COD_CLIENTE", "NOM_CLIENTE"],
            "cliente",
        )
        exact_filter(
            r"(?:pedido|documento)[:\s]+([A-Za-z0-9_-]+)",
            ["ID_PEDIDO", "NRO_DOCUMENTO", "ID_DOCUMENTO"],
            "pedido",
        )
        exact_filter(r"(?:oc|orden de compra)[:\s]+([A-Za-z0-9_-]+)", ["PEDIDO_ORD_COMPRA"], "OC")
        exact_filter(r"(?:estado pedido|estado)[:\s]+([A-Za-z0-9_-]+)", ["PEDIDO_ESTADO"], "estado")
        exact_filter(
            r"(?:planilla|estado planilla|anticipo)[:\s]+([^,;]+?)(?=\s+(?:cliente|pedido|oc|vendedor)\b|$)",
            ["NOM_ESTADO_PLANILLA_ANTICIPO", "ID_PLANILLA_ANTICIPO"],
            "planilla",
        )
        exact_filter(
            r"(?:vendedor)[:\s]+([^,;]+?)(?=\s+(?:cliente|pedido|almacen|linea|categoria)\b|$)",
            ["ID_VENDEDOR", "NOM_VENDEDOR"],
            "vendedor",
        )
        exact_filter(r"(?:almacen|almacén)[:\s]+([A-Za-z0-9_-]+)", ["NOM_ALMACEN"], "almacen")
        exact_filter(
            r"(?:linea|línea)[:\s]+([^,;]+?)(?=\s+(?:cliente|pedido|vendedor|almacen|categoria)\b|$)",
            ["linea", "estado_linea"],
            "linea",
        )

        if "CONDICION_PAGO" in self.df or self._cond_familia_col() in self.df:
            for condition, pattern in COND_PAGO_PATTERNS.items():
                if re.search(pattern, lower):
                    if "CONDICION_PAGO" in self.df:
                        mask &= (
                            self.df["CONDICION_PAGO"]
                            .astype(str)
                            .str.contains(pattern, case=False, na=False, regex=True)
                        )
                    familia = normalize_cond_familia(condition)
                    if self._cond_familia_col() in self.df:
                        mask &= self.df[self._cond_familia_col()] == familia
                    filters.append(f"condicion={condition}")
                    break

        for category in ("VINIBALL", "VINIFAN", "REPRESENTADAS"):
            if category.lower() in lower and "categoria" in self.df:
                mask &= self.df["categoria"].astype(str).str.upper().eq(category)
                filters.append(f"categoria={category}")
                break

        sku_col = self._sku_col()
        sku_match = re.search(r"(?:sku|producto)[:\s]+([0-9A-Za-z_-]+)", lower)
        if sku_match and sku_col in self.df:
            sku = sku_match.group(1)
            mask &= self.df[sku_col].astype(str).str.strip().eq(sku)
            filters.append(f"SKU={sku}")

        # IDs numericos sueltos (SKU, vendedor o cliente) aunque haya otros filtros.
        # Ej: "014270 canje" -> SKU + condicion; "031 anticipo" -> vendedor + condicion.
        digit_tokens = [t for t in re.split(r"[\s,;]+", lower) if t.isdigit() and len(t) <= 6]
        already = {f.split("=")[-1] for f in filters if "=" in f}
        for idt in digit_tokens:
            if idt in already:
                continue
            if sku_col in self.df and len(idt) >= 4:
                eq_sku = self.df[sku_col].astype(str).str.strip().eq(idt)
                if eq_sku.any():
                    mask &= eq_sku
                    filters.append(f"SKU={idt}")
                    already.add(idt)
                    continue
            if "ID_VENDEDOR" in self.df:
                eq_ven = self.df["ID_VENDEDOR"].astype(str).str.strip().eq(idt)
                if eq_ven.any():
                    mask &= eq_ven
                    filters.append(f"vendedor={idt}")
                    already.add(idt)
                    continue
            if "COD_CLIENTE" in self.df:
                eq_cli = self.df["COD_CLIENTE"].astype(str).str.strip().eq(idt)
                if eq_cli.any():
                    mask &= eq_cli
                    filters.append(f"cliente={idt}")
                    already.add(idt)

        if not filters:
            # Token >= 4 chars, o numericos cortos (IDs de vendedor/cliente/OC)
            tokens = [
                token
                for token in re.split(r"[\s,;]+", lower)
                if (len(token) >= 4 or token.isdigit())
                and token not in QUERY_STOPWORDS
                and not (es_no_aprobado and token.startswith("aprobad"))
            ]
            search_columns = [
                c
                for c in [
                    "NOM_ARTICULO",
                    "nombre_catalogo",
                    "linea",
                    "grupo",
                    "familia",
                    "ID_PEDIDO",
                    "NRO_DOCUMENTO",
                    "ID_DOCUMENTO",
                    "CONDICION_PAGO",
                    "ID_VENDEDOR",
                    "NOM_VENDEDOR",
                    "COD_CLIENTE",
                    "NOM_CLIENTE",
                    "PEDIDO_ESTADO",
                ]
                if c in self.df
            ]
            if tokens and search_columns:
                # Todos los tokens deben aparecer en alguna columna (AND)
                for token in tokens:
                    tok_mask = pd.Series(False, index=self.df.index)
                    for col in search_columns:
                        tok_mask |= (
                            self.df[col]
                            .astype(str)
                            .str.contains(token, case=False, na=False, regex=False)
                        )
                    mask &= tok_mask
                filters.append("texto~'" + "' y '".join(tokens) + "'")

        result = self.df.loc[mask]
        if result.empty:
            return result, f"Sin resultados para '{text}'"
        return result, " y ".join(filters) if filters else "Vista completa"

    # ---------------------------------------------------------------
    # Queries especificas
    # ---------------------------------------------------------------
    def get_vinifan_client_summary(self, client_id: str | int) -> dict:
        """Resumen para la query 'VINIFAN cliente <id>'.

        Retorna: total_pedido (soles), units (saldo), cajas, desglose por
        estado_linea con sus valores en soles.
        """
        df = self.df
        cat_col = self._cat_col()
        cli_col = self._cliente_col()
        est_col = self._estado_col()
        if cat_col not in df.columns or cli_col not in df.columns:
            return {}
        sub = df[
            (df[cat_col] == "VINIFAN")
            & (df[cli_col].astype(str).str.strip() == str(client_id).strip())
        ].copy()
        if sub.empty:
            return {}

        total_pedido_soles = float(sub["valor_saldo"].sum()) if "valor_saldo" in sub else 0.0
        units_saldo = float(sub["saldo"].sum()) if "saldo" in sub else 0.0
        cajas = float(sub["cajas"].sum()) if "cajas" in sub else 0.0

        estado_breakdown: dict[str, float] = {}
        if est_col in sub.columns:
            for est, g in sub.groupby(est_col, dropna=False):
                key = str(est) if est is not None and str(est) != "" else "(sin estado)"
                estado_breakdown[key] = round(float(g["valor_saldo"].sum()), 2)

        return {
            "categoria": "VINIFAN",
            "cliente_id": str(client_id),
            "total_pedido_soles": round(total_pedido_soles, 2),
            "units_saldo": round(units_saldo, 2),
            "cajas": round(cajas, 2),
            "estado_linea_breakdown": estado_breakdown,
        }

    def get_sku_box_query(self, sku: str | int) -> dict:
        """Responde cuantas cajas de un SKU especifico se deben entregar.

        Retorna: SKU, nombre, categoria/estado_linea, units pendientes, cajas.
        """
        df = self.df
        sku_col = self._sku_col()
        if sku_col not in df.columns:
            return {}
        sub = df[df[sku_col].astype(str).str.strip() == str(sku).strip()]
        if sub.empty:
            return {}

        # El SKU puede repetirse en varias filas (clientes/almacenes):
        # se agrega el saldo y las cajas de todas sus filas.
        row = sub.iloc[0]
        return {
            "sku": str(sku),
            "nombre": str(row.get("NOM_ARTICULO", row.get("nombre_catalogo", ""))),
            "categoria": str(row.get("categoria", "")),
            "estado_linea": str(row.get("estado_linea", "")),
            "units_pendientes": float(sub["saldo"].sum()) if "saldo" in sub else 0.0,
            "cajas": float(sub["cajas"].sum()) if "cajas" in sub else 0.0,
        }

    # ---------------------------------------------------------------
    # Monitor operativo: rankings, cola de despacho y resumen por pedido
    # ---------------------------------------------------------------
    def get_pedido_id_col(self) -> str | None:
        """Clave operativa para despacho parcial: ID_PEDIDO."""
        return self._get_col("ID_PEDIDO")

    def get_lineas_by_id_pedido(self, id_pedido) -> pd.DataFrame:
        """Todas las lineas de un ID_PEDIDO (drill pedido -> linea)."""
        id_col = self.get_pedido_id_col()
        if id_col is None:
            return self.get_lineas_filtradas_oc(id_pedido)
        return self.df[self.df[id_col].astype(str) == str(id_pedido)].reset_index(drop=True)

    def get_lineas_filtradas_oc(self, oc) -> pd.DataFrame:
        """Lineas filtradas por NRO_DOCUMENTO (compatibilidad)."""
        if "NRO_DOCUMENTO" in self.df.columns:
            return self.df[self.df["NRO_DOCUMENTO"].astype(str) == str(oc)].reset_index(drop=True)
        return self.get_lineas_by_id_pedido(oc)

    def get_cond_familias(self) -> pd.DataFrame:
        """Agrupado por familia normalizada de condicion de pago."""
        col = self._cond_familia_col()
        if col is None or col not in self.df.columns:
            return pd.DataFrame()
        g = self.df.groupby(col, dropna=False)
        out = pd.DataFrame(
            {
                "items": g.size(),
                "pedido": g["CAN_PEDIDO"].sum() if "CAN_PEDIDO" in self.df else 0,
                "saldo": g["saldo"].sum() if "saldo" in self.df else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in self.df else 0,
                "cajas": g["cajas"].sum() if "cajas" in self.df else 0,
            }
        ).reset_index()
        out.index.name = col
        return out.sort_values("valor", ascending=False).reset_index(drop=True)

    def get_resumen_pedidos(self, top: int | None = None) -> pd.DataFrame:
        """Resumen por ID_PEDIDO (nivel raiz 'Por Pedido' del drill).

        Retorna: ID_PEDIDO, NRO_DOCUMENTO, vendedor, cliente, items, pedido,
        despacho, saldo, cajas, por_atendido, estado, valor, stock_VES/121/otros,
        disp_cub_VES.
        """
        id_col = self.get_pedido_id_col()
        if id_col is None or "CAN_PEDIDO" not in self.df.columns:
            return pd.DataFrame()
        sub = self.df.copy()
        for c in [
            "CAN_PEDIDO",
            "CAN_DESPACHO",
            "saldo",
            "cajas",
            "valor_saldo",
            "valor_pedido",
            "valor_atendido",
        ]:
            if c in sub:
                sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0)
        g = sub.groupby(id_col, dropna=False)
        agg = {
            "items": (id_col, "size"),
            "pedido": ("CAN_PEDIDO", "sum"),
            "despacho": ("CAN_DESPACHO", "sum"),
        }
        for c, ex in [
            ("saldo", "saldo"),
            ("cajas", "cajas"),
            ("valor", "valor_saldo"),
            ("valor_pedido", "valor_pedido"),
            ("valor_atendido", "valor_atendido"),
        ]:
            if ex in sub.columns:
                agg[c] = (ex, "sum")
        out = g.agg(**agg).reset_index()
        out["por_atendido"] = (
            pd.to_numeric(out["despacho"], errors="coerce").fillna(0)
            / pd.to_numeric(out["pedido"], errors="coerce").replace(0, 1)
            * 100
        ).round(1)
        # % atendido en soles (monto) a partir de los totales del pedido
        if "valor_pedido" in out.columns and "valor_atendido" in out.columns:
            out["por_atendido_valor"] = (
                pd.to_numeric(out["valor_atendido"], errors="coerce").fillna(0)
                / pd.to_numeric(out["valor_pedido"], errors="coerce").replace(0, 1)
                * 100
            ).round(1)
            out.loc[out["valor_pedido"] == 0, "por_atendido_valor"] = 0.0
        else:
            out["por_atendido_valor"] = 0.0
        # Lineas validas: filas con estado_linea real (catalogo); sin catalogo cae a items.
        if "estado_linea" in sub.columns:
            valido = sub["estado_linea"].fillna("").astype(str).str.strip().ne("")
            out["lineas_validas"] = (
                valido.groupby(sub[id_col])
                .sum()
                .reindex(out[id_col], fill_value=0)
                .astype(int)
                .values
            )
        else:
            out["lineas_validas"] = out["items"]

        def _estado(r):
            pct = float(r.get("por_atendido", 0))
            if pct >= 100.0:
                return "100%"
            if pct > 0.0:
                return "PARCIAL"
            return "PENDIENTE"

        out["estado"] = out.apply(_estado, axis=1)
        for c in [
            "NRO_DOCUMENTO",
            "COD_CLIENTE",
            "NOM_CLIENTE",
            "ID_VENDEDOR",
            "NOM_VENDEDOR",
            "PEDIDO_ESTADO",
            "CONDICION_PAGO",
        ]:
            if c in sub:
                out[c] = out[id_col].map(g[c].first())
        for c, src in [
            ("stock_VES", "stock_api_ves"),
            ("stock_121", "stock_api_121"),
            ("stock_otros", "stock_api_otros"),
        ]:
            if src in sub:
                out[c] = out[id_col].map(sub.groupby(id_col, dropna=False)[src].first()).fillna(0)
            else:
                out[c] = 0
        if "stock_VES" in out and "saldo" in out:
            out["disp_cub_VES"] = out.apply(
                lambda r: float(
                    min(max(float(r.get("stock_VES", 0)), 0), max(float(r.get("saldo", 0)), 0))
                ),
                axis=1,
            )
        out = out.sort_values("saldo", ascending=False)
        if top:
            out = out.head(top)
        return out.reset_index(drop=True)

    def get_top_clientes_deudores(self, top: int = 10, by: str = "valor") -> pd.DataFrame:
        """Ranking de clientes que mas se les debe (valor o saldo)."""
        out = self.get_by_cliente()
        if out.empty:
            return out
        col = "valor" if by == "valor" else "saldo"
        if col not in out.columns:
            return out.head(top).reset_index(drop=True)
        return out.sort_values(col, ascending=False).head(top).reset_index(drop=True)

    def get_vendedores_pendientes(self, top: int | None = None) -> pd.DataFrame:
        """Ranking de vendedores por saldo pendiente y valor."""
        out = self.get_by_vendedor()
        if out.empty:
            return out
        if top:
            out = out.head(top)
        return out.reset_index(drop=True)

    def get_pedidos_casi_100(self, min_pct: float = 80.0, top: int = 15) -> pd.DataFrame:
        """Pedidos (ID_PEDIDO) con atencion casi completa (>= min_pct y < 100%)."""
        id_col = self.get_pedido_id_col()
        if id_col is None or "CAN_PEDIDO" not in self.df.columns:
            return pd.DataFrame()
        out = self.get_resumen_pedidos(top=None)
        if out.empty:
            return out
        out = out[
            (out["por_atendido"] >= min_pct) & (out["por_atendido"] < 100.0) & (out["saldo"] > 0)
        ]
        return out.sort_values("por_atendido", ascending=False).head(top).reset_index(drop=True)

    def get_skus_mas_necesitados(self, familia: str | None = None, top: int = 20) -> pd.DataFrame:
        """SKUs mas necesitados (mayor saldo), opcionalmente por familia de condicion."""
        sku_col = self._sku_col()
        if sku_col is None or "saldo" not in self.df.columns:
            return pd.DataFrame()
        sub = self.df.copy()
        familia_col = self._cond_familia_col()
        if familia and familia_col in sub.columns:
            sub = sub[sub[familia_col] == familia]
        for c in [
            "saldo",
            "cajas",
            "valor_saldo",
            "stock_api_ves",
            "stock_api_121",
            "stock_api_otros",
        ]:
            if c in sub:
                sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0)
        group_cols = [sku_col]
        nom = self._nombre_col()
        if nom in sub.columns and nom != sku_col:
            group_cols.append(nom)
        agg = {"items": (sku_col, "size"), "saldo": ("saldo", "sum")}
        for c, ex in [("cajas", "cajas"), ("valor", "valor_saldo")]:
            if ex in sub.columns:
                agg[c] = (ex, "sum")
        for c, src in [
            ("stock_VES", "stock_api_ves"),
            ("stock_121", "stock_api_121"),
            ("stock_otros", "stock_api_otros"),
        ]:
            if src in sub.columns:
                agg[c] = (src, "sum")
        out = sub.groupby(group_cols, dropna=False).agg(**agg).reset_index()
        if "categoria" in sub.columns:
            out["categoria"] = (
                out[sku_col].map(sub.groupby(sku_col, dropna=False)["categoria"].first()).fillna("")
            )
        if "stock_VES" in out.columns and "saldo" in out.columns:
            out["disp_cub_VES"] = out.apply(
                lambda r: float(
                    min(max(float(r.get("stock_VES", 0)), 0), max(float(r.get("saldo", 0)), 0))
                ),
                axis=1,
            )
        return out.sort_values("saldo", ascending=False).head(top).reset_index(drop=True)

    def get_cola_despacho(self) -> pd.DataFrame:
        """Lineas listas para cargar en el ERP (despacho manual).

        Agrupa por ID_PEDIDO + SKU: cant_a_despachar = min(saldo, stock VES),
        cajas_a_despachar = cant/un_bx. Solo cant_a_despachar > 0.
        """
        id_col = self.get_pedido_id_col()
        sku_col = self._sku_col()
        if id_col is None or sku_col is None or "saldo" not in self.df.columns:
            return pd.DataFrame()
        sub = self.df.copy()
        for c in [
            "saldo",
            "CAN_PEDIDO",
            "CAN_DESPACHO",
            "un_bx",
            "stock_api_ves",
            "stock_api_121",
            "stock_api_otros",
        ]:
            if c in sub:
                sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0)
        if "un_bx" not in sub.columns:
            sub["un_bx"] = 1
        sub["un_bx"] = sub["un_bx"].replace(0, 1)
        sub["cant_a_despachar"] = sub.apply(
            lambda r: float(
                min(max(float(r.get("saldo", 0)), 0), max(float(r.get("stock_api_ves", 0)), 0))
            ),
            axis=1,
        )
        sub["cajas_a_despachar"] = sub["cant_a_despachar"] / sub["un_bx"]
        pend = sub[(sub["cant_a_despachar"] > 0)].copy()
        cols = [
            "NRO_DOCUMENTO",
            "COD_CLIENTE",
            "NOM_CLIENTE",
            "ID_VENDEDOR",
            "NOM_VENDEDOR",
            "CONDICION_PAGO",
            "cond_familia",
            "NOM_ARTICULO",
            "CAN_PEDIDO",
            "CAN_DESPACHO",
            "saldo",
            "stock_api_ves",
            "stock_api_121",
            "stock_api_otros",
            "un_bx",
            "cant_a_despachar",
            "cajas_a_despachar",
        ]
        keep = {
            "ID_PEDIDO": id_col,
            "SKU": sku_col,
            **{c: c for c in cols if c in pend.columns},
        }
        out = pend[list(keep.values())].rename(columns={id_col: "ID_PEDIDO", sku_col: "SKU"})
        return out.sort_values(["ID_PEDIDO", "SKU"]).reset_index(drop=True)

    # ---------------------------------------------------------------
    # Funnel Vigencias multifamilia (v1 ANTICIPO, v2 CONTADO/CANJE, v3 LETRA/FACTURA)
    # ---------------------------------------------------------------
    @staticmethod
    def n_letras(cond_pago) -> int:
        """Nro de vencimientos en una condicion LETRA (1 letra vs 2+)."""
        return len(re.findall(r"\d+", str(cond_pago or "")))

    def _familia_serie(self, df: pd.DataFrame) -> pd.Series:
        """Familia normalizada por fila (usa cond_familia si existe)."""
        if "cond_familia" in df.columns:
            return df["cond_familia"].astype(str).str.strip().str.upper()
        if "CONDICION_PAGO" in df.columns:
            return df["CONDICION_PAGO"].apply(normalize_cond_familia)
        return pd.Series("OTRO", index=df.index)

    def filtrar_lineas_validas(self) -> pd.DataFrame:
        """Solo filas SKU de linea valida (sufijo) con saldo > 0.

        Granular fila-SKU: el pedido se conserva si tiene >=1 valida,
        mostrando solo esas filas. Vendedor/cliente se reducen en cascada.
        """
        df = self.df
        if "saldo" not in df.columns:
            return df.reset_index(drop=True)
        mask = pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0
        if "es_linea_valida" in df.columns:
            mask &= df["es_linea_valida"].fillna(False).astype(bool)
        return df.loc[mask].reset_index(drop=True)

    def filtrar_familia(self, familia: str = "ANTICIPO") -> pd.DataFrame:
        """Embudo por familia: saldo>0 + linea valida + APROBADO + condicion.

        ANTICIPO = match exacto 'ANTICIPO EN LETRAS' (fiel al VBA);
        resto = familia normalizada (CONTADO/CANJE/LETRA/FACTURA).
        """
        df = self.filtrar_lineas_validas()
        if df.empty:
            return df
        fam = str(familia or "ANTICIPO").strip().upper()
        if fam == "ANTICIPO":
            if "CONDICION_PAGO" in df.columns:
                df = df[
                    df["CONDICION_PAGO"].astype(str).str.strip().str.upper() == "ANTICIPO EN LETRAS"
                ]
        else:
            df = df[self._familia_serie(df) == fam]
        if "PEDIDO_ESTADO" in df.columns:
            df = df[df["PEDIDO_ESTADO"].astype(str).str.strip().str.upper() == "APROBADO"]
        return df.reset_index(drop=True)

    def filtrar_prototipo(self) -> pd.DataFrame:
        """Alias v1: embudo VBA (ANTICIPO EN LETRAS + APROBADO)."""
        return self.filtrar_familia("ANTICIPO")

    def resumen_pedidos_familia(self, familia: str = "ANTICIPO") -> pd.DataFrame:
        """Pedido completo (% real a pedido total, no al slice cubierto).

        Columnas: pedido, despacho, saldo, pct_cant, pct_valor, filas,
        vendedor, cliente, fecha, val (suma val_atencion/val_pendiente).
        Orden: val_atencion desc (monto) con pct como columna.
        """
        df = self.filtrar_familia(familia)
        if df.empty:
            return df
        id_col = self.get_pedido_id_col() or "ID_PEDIDO"
        key = id_col if id_col in df.columns else None
        if key is None:
            return pd.DataFrame()
        # % a pedido TOTAL del ERP (todas las filas del pedido, validas o no)
        base = self.df
        if "PEDIDO_ESTADO" in base.columns:
            base = base[base["PEDIDO_ESTADO"].astype(str).str.strip().str.upper() == "APROBADO"]
        tot = base.groupby(key, dropna=False).agg(
            pedido=("CAN_PEDIDO", "sum") if "CAN_PEDIDO" in base else (key, "size"),
            despacho=("CAN_DESPACHO", "sum") if "CAN_DESPACHO" in base else (key, "size"),
        )
        tot["pct_cant"] = (
            pd.to_numeric(tot["despacho"], errors="coerce").fillna(0)
            / pd.to_numeric(tot["pedido"], errors="coerce").replace(0, 1)
            * 100
        ).round(1)
        if "valor_pedido" in base.columns and "valor_atendido" in base.columns:
            vtot = base.groupby(key, dropna=False).agg(
                vp=("valor_pedido", "sum"), va=("valor_atendido", "sum")
            )
            tot["pct_valor"] = (
                pd.to_numeric(vtot["va"], errors="coerce").fillna(0)
                / pd.to_numeric(vtot["vp"], errors="coerce").replace(0, 1)
                * 100
            ).round(1)
        else:
            tot["pct_valor"] = 0.0
        g = df.groupby(key, dropna=False)
        out = pd.DataFrame(
            {
                "filas": g.size(),
                "saldo": g["saldo"].sum() if "saldo" in df else 0,
                "val_atencion": g["val_atencion"].sum() if "val_atencion" in df else 0,
                "val_pendiente": g["val_pendiente"].sum() if "val_pendiente" in df else 0,
            }
        )
        for c in [
            "NOM_VENDEDOR",
            "NOM_CLIENTE",
            "COD_CLIENTE",
            "ID_VENDEDOR",
            "NRO_DOCUMENTO",
            "PEDIDO_FECHA",
            "CONDICION_PAGO",
        ]:
            if c in df.columns:
                out[c] = g[c].first()
        out = out.join(tot[["pedido", "despacho", "pct_cant", "pct_valor"]], how="left")
        if "PEDIDO_FECHA" in out.columns:
            out["_fecha"] = pd.to_datetime(out["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
            out = out.sort_values(
                ["val_atencion", "pct_cant", "_fecha"],
                ascending=[False, False, True],
            ).drop(columns=["_fecha"])
        else:
            out = out.sort_values(["val_atencion", "pct_cant"], ascending=[False, False])
        return out.reset_index()

    def get_val_atencion(self, familia: str = "ANTICIPO") -> pd.DataFrame:
        """Filas familia donde VES cubre el saldo (despachable hoy)."""
        df = self.filtrar_familia(familia)
        if df.empty or "stock_real" not in df.columns or "saldo" not in df.columns:
            return df
        stock = pd.to_numeric(df["stock_real"], errors="coerce").fillna(0)
        saldo = pd.to_numeric(df["saldo"], errors="coerce").fillna(0)
        return df.loc[stock >= saldo].reset_index(drop=True)

    def get_val_pendiente(self, familia: str = "ANTICIPO") -> pd.DataFrame:
        """Filas familia donde VES no cubre (incluye INGRESADO planilla)."""
        df = self.filtrar_familia(familia)
        if df.empty or "stock_real" not in df.columns or "saldo" not in df.columns:
            return df
        stock = pd.to_numeric(df["stock_real"], errors="coerce").fillna(0)
        saldo = pd.to_numeric(df["saldo"], errors="coerce").fillna(0)
        return df.loc[stock < saldo].reset_index(drop=True)

    def filtrar_dias(self, dias: int) -> "PedidosAnalytics":
        """Recorta por antiguedad del pedido (PEDIDO_FECHA). dias<=0 = todo."""
        if not dias or dias <= 0 or "PEDIDO_FECHA" not in self.df.columns:
            return self
        f = pd.to_datetime(self.df["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
        corte = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=int(dias))
        return PedidosAnalytics(self.df[f >= corte].reset_index(drop=True))

    def filtrar_segmento(
        self,
        lineas: list[str] | None = None,
        categorias: list[str] | None = None,
        estados: list[str] | None = None,
    ) -> "PedidosAnalytics":
        """Segmenta por linea / categoria / estado de linea (AND combinado).

        Los valores se comparan normalizados (strip+upper) y aceptan tanto el
        codigo corto (78) como el nombre (ARCHIVO) para `lineas`. `estados`
        acepta tambien el sufijo del estado (NUEVO/TRADICIONAL/IMPORTADO).
        """
        df = self.df
        if df is None or len(df) == 0:
            return self

        def _norm(series: pd.Series) -> pd.Series:
            return series.astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": ""})

        def _match(series: pd.Series, valores: list[str]) -> pd.Series:
            objetivo = {str(v).strip().upper() for v in valores if str(v).strip()}
            if not objetivo:
                return pd.Series(True, index=series.index)
            n = _norm(series)
            mask = n.isin(objetivo)
            # sufijo 2 chars: '0178' / '01MA' aceptan '78' / 'MA'
            for v in objetivo:
                if len(v) <= 2:
                    mask |= n.str.endswith(v, na=False)
            # nombre en el propio texto ('01 - PELOTAS' acepta 'PELOTAS')
            for v in objetivo:
                if len(v) > 2:
                    mask |= n.str.contains(v, na=False, regex=False)
            return mask

        m = pd.Series(True, index=df.index)
        if lineas and "linea" in df.columns:
            m &= _match(df["linea"], lineas)
        if categorias and "categoria" in df.columns:
            m &= _match(df["categoria"], categorias)
        if estados and "estado_linea" in df.columns:
            m &= _match(df["estado_linea"], estados)
        return PedidosAnalytics(df[m].reset_index(drop=True))

    def resumen_accion_pedido(
        self, familia: str = "ANTICIPO", umbral: float = 1200.0
    ) -> pd.DataFrame:
        """Una fila por pedido con estado de accion (llave operativa).

        Estados: ENTREGA_TOTAL / PARCIAL / OBSERVACION(<umbral) /
        TRASLADO (121 cubre faltante) / SIN_COBERTURA.
        """
        df = self.filtrar_familia(familia)
        id_col = self.get_pedido_id_col() or "ID_PEDIDO"
        if df.empty or id_col not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["_ves"] = pd.to_numeric(
            df.get("stock_real", df.get("stock_api_ves", 0)), errors="coerce"
        ).fillna(0)
        df["_s121"] = pd.to_numeric(df.get("stock_api_121", 0), errors="coerce").fillna(0)
        df["_saldo"] = pd.to_numeric(df.get("saldo", 0), errors="coerce").fillna(0)
        df["_cub"] = df["_ves"] >= df["_saldo"]
        df["_falt"] = (df["_saldo"] - df["_ves"]).clip(lower=0)
        df["_tras"] = df.apply(lambda r: float(min(r["_falt"], r["_s121"])), axis=1)
        # Split comercial: planilla INGRESADO condiciona la salida.
        if "NOM_ESTADO_PLANILLA_ANTICIPO" in df.columns:
            _pl = df["NOM_ESTADO_PLANILLA_ANTICIPO"].astype(str).str.strip().str.upper()
            _bloq = _pl.eq("INGRESADO")
        else:
            _bloq = pd.Series(False, index=df.index)
        df["_bloq"] = _bloq
        if "val_atencion" in df.columns:
            df["_val_hoy"] = df["val_atencion"].where(~_bloq, 0).astype(float)
            df["_val_aprob"] = df["val_atencion"].where(_bloq, 0).astype(float)
        else:
            df["_val_hoy"] = 0.0
            df["_val_aprob"] = 0.0
        g = df.groupby(id_col, dropna=False)
        out = pd.DataFrame(
            {
                "filas": g.size(),
                "filas_cubiertas": g["_cub"].sum(),
                "saldo": g["_saldo"].sum(),
                "val_atencion": g["val_atencion"].sum() if "val_atencion" in df else 0,
                "val_pendiente": g["val_pendiente"].sum() if "val_pendiente" in df else 0,
                "trasladable": g["_tras"].sum(),
                "despachable_hoy": g["_val_hoy"].sum(),
                "si_se_aprueba": g["_val_aprob"].sum(),
            }
        )
        # Segmentos visibles a nivel pedido (para filtrar sin partir el libro)
        for col, nombre in (
            ("linea", "lineas"),
            ("linea_nombre", "lineas_nombre"),
            ("categoria", "categorias"),
            ("estado_linea", "estados_linea"),
        ):
            if col in df.columns:
                norm = (
                    df[col]
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .replace({"NAN": "", "NONE": ""})
                    .fillna("")
                )
                out[nombre] = norm.groupby(df[id_col], dropna=False).apply(
                    lambda s: ", ".join(sorted({v for v in s if v}))
                )
            else:
                out[nombre] = ""
        # Alinear `lineas_nombre` con `lineas` (mismo orden de codigos).
        # Sin esto las dos columnasTenian ordenes distintos (numerico vs
        # alfabetico) y no se podia emparejar posicion a posicion.
        if "lineas" in out.columns and "lineas_nombre" in out.columns:
            mapa_nombre: dict[str, str] = {}
            if "linea" in df.columns and "linea_nombre" in df.columns:
                for cod, nom in zip(df["linea"].astype(str), df["linea_nombre"].astype(str)):
                    cod = cod.strip().upper()
                    nom = nom.strip().upper()
                    if cod and nom and cod not in mapa_nombre:
                        mapa_nombre[cod] = nom

            def _alinear(cods) -> str:
                partes = [c.strip() for c in str(cods).split(",") if c.strip()]
                return ", ".join(
                    f"{c} ({mapa_nombre[c]})" if c in mapa_nombre else c for c in partes
                )

            out["lineas_nombre"] = out["lineas"].map(_alinear)
        # Peso despachable: kg por linea (saldo x peso_kg del catalogo Render)
        if "peso_kg" in df.columns:
            peso = pd.to_numeric(df["peso_kg"], errors="coerce").fillna(0)
            saldo_fila = pd.to_numeric(df["saldo"], errors="coerce").fillna(0)
            kg_total = saldo_fila * peso
            # kg solo de las lineas que hoy se despachan (val_atencion > 0)
            cub = (
                (
                    df.get("stock_real", df.get("stock_api_ves", 0)).astype(float).fillna(0)
                    >= saldo_fila
                )
                if "stock_real" in df.columns
                else pd.Series(False, index=df.index)
            )
            df["_kg_total"] = kg_total
            df["_kg_hoy"] = kg_total.where(cub & ~_bloq, 0)
            df["_kg_saldo"] = kg_total.where(~_bloq, 0)
            out["kg_saldo"] = g["_kg_saldo"].sum().round(1)
            out["kg_hoy"] = g["_kg_hoy"].sum().round(1)
            out["peso_estimada"] = (
                pd.to_numeric(df["peso_kg"], errors="coerce")
                .fillna(0)
                .le(0)
                .groupby(df[id_col], dropna=False)
                .any()
            )
            # % de unidades del pedido con peso conocido en el maestro Render.
            # El peso del maestro cubre ~52% de los SKUs: sin este dato, el kg
            # del pedido es una cota inferior, no el peso real de carga.
            _peso = pd.to_numeric(df["peso_kg"], errors="coerce").fillna(0)
            _un = pd.to_numeric(df["saldo"], errors="coerce").fillna(0).clip(lower=0)
            _un_known = _un.where(_peso > 0, 0.0)
            df["_u_un"] = _un
            df["_u_known"] = _un_known
            out["kg_cobertura"] = (
                g["_u_known"].sum() / g["_u_un"].sum().replace(0, 1) * 100
            ).round(1)
        else:
            out["kg_saldo"] = 0.0
            out["kg_hoy"] = 0.0
            out["peso_estimada"] = True
            out["kg_cobertura"] = 0.0
        # Precio unitario efectivo del pedido (ponderado por unidades) y
        # control de coherencia: el precio sale del reporte de vigencias.
        if "precio_unitario" in df.columns and "saldo" in df.columns:
            _pu = pd.to_numeric(df["precio_unitario"], errors="coerce")
            _sl = pd.to_numeric(df["saldo"], errors="coerce").fillna(0).clip(lower=0)
            df["_pu_x_sl"] = _pu.fillna(0) * _sl
            df["_sl_precio"] = _sl
            out["precio_unitario"] = (
                (g["_pu_x_sl"].sum() / g["_sl_precio"].sum().replace(0, pd.NA))
                .astype(float)
                .round(2)
            )
        else:
            out["precio_unitario"] = 0.0
        if "precio_verificable" in df.columns:
            out["precios_verificados"] = (
                df["precio_verificable"].astype(bool).groupby(df[id_col], dropna=False).sum()
            )
            out["precios_coherentes"] = (
                (df["precio_verificable"].astype(bool) & df["precio_coherente"].astype(bool))
                .groupby(df[id_col], dropna=False)
                .sum()
            )
        for c in [
            "NRO_DOCUMENTO",
            "COD_CLIENTE",
            "NOM_CLIENTE",
            "ID_VENDEDOR",
            "NOM_VENDEDOR",
            "PEDIDO_FECHA",
            "CONDICION_PAGO",
            "PEDIDO_ESTADO",
            "NOM_ESTADO_PLANILLA_ANTICIPO",
        ]:
            if c in df.columns:
                out[c] = g[c].first()
        if "dias_desde_pedido" in df.columns:
            out["dias"] = g["dias_desde_pedido"].max()
        else:
            out["dias"] = 0
        pct = self.resumen_pedidos_familia(familia)
        if not pct.empty and id_col in pct.columns:
            out = out.join(pct.set_index(id_col)[["pct_cant", "pct_valor", "pedido", "despacho"]])
        else:
            out["pct_cant"] = 0.0
            out["pct_valor"] = 0.0

        def _estado(r):
            va = float(r.get("val_atencion", 0) or 0)
            fc = int(r.get("filas_cubiertas", 0) or 0)
            fi = int(r.get("filas", 0) or 0)
            if va >= umbral:
                return "ENTREGA_TOTAL" if fc == fi and fi else "PARCIAL"
            if va > 0:
                return "OBSERVACION"
            if float(r.get("trasladable", 0) or 0) > 0:
                return "TRASLADO"
            return "SIN_COBERTURA"

        out["estado_accion"] = out.apply(_estado, axis=1)
        # % cubierto del pedido (base para P1 vs P2)
        _fi = pd.to_numeric(out["filas"], errors="coerce").fillna(0)
        _fc = pd.to_numeric(out["filas_cubiertas"], errors="coerce").fillna(0)
        out["pct_cubierto"] = (_fc / _fi.replace(0, 1) * 100).round(1)
        # "Casi cierra": va por encima del 80% de lineas cubiertas y aun tiene
        # saldo por despachar -> cerrarlo hoy tiene alto rendimiento.
        out["casi_cierra"] = out["pct_cubierto"].ge(80) & out["despachable_hoy"].gt(0)

        def _prio(r):
            """P1..P5 sugerida (editable por el usuario via prio_manual)."""
            hoy = float(r.get("despachable_hoy", 0) or 0)
            cond = float(r.get("si_se_aprueba", 0) or 0)
            fc = int(r.get("filas_cubiertas", 0) or 0)
            fi = int(r.get("filas", 0) or 0)
            tras = float(r.get("trasladable", 0) or 0)
            va = float(r.get("val_atencion", 0) or 0)
            if hoy >= umbral:
                return "P1" if (fc == fi and fi) else "P2"
            if cond > 0 and va > 0:
                return "P4"
            if tras > 0:
                return "P3"
            if va > 0:
                return "P2" if va >= umbral else "P5"
            return "P3" if tras > 0 else "P5"

        out["prio_sugerida"] = out.apply(_prio, axis=1)

        def _acciones(r):
            hoy = float(r.get("despachable_hoy", 0) or 0)
            cond = float(r.get("si_se_aprueba", 0) or 0)
            tras = float(r.get("trasladable", 0) or 0)
            fc = int(r.get("filas_cubiertas", 0) or 0)
            p = str(r.get("prio_sugerida", ""))
            a1 = a2 = ""
            if p == "P1":
                a1 = "DESPACHAR"
            elif p == "P2":
                a1, a2 = "DESPACHAR", ("SOLICITAR_TRASLADO" if tras > 0 else "REGISTRAR_SALDO")
            elif p == "P3":
                a1, a2 = "SOLICITAR_TRASLADO", ("DESPACHAR" if hoy > 0 else "ACUMULAR")
            elif p == "P4":
                a1, a2 = "APROBAR_PLANILLA", ("DESPACHAR" if hoy > 0 else "ACUMULAR")
            else:
                a1, a2 = "ACUMULAR", ("REPONER" if fc == 0 else "CONSULTAR")
            if cond > 0 and p in ("P1", "P2") and not a2:
                a2 = "APROBAR_PLANILLA"
            return a1, a2

        _acc = out.apply(_acciones, axis=1, result_type="expand")
        out["accion_1"] = _acc[0]
        out["accion_2"] = _acc[1]
        order = {
            "ENTREGA_TOTAL": 0,
            "PARCIAL": 1,
            "TRASLADO": 2,
            "OBSERVACION": 3,
            "SIN_COBERTURA": 4,
        }
        out["_ord"] = out["estado_accion"].map(order).fillna(9)
        out = out.sort_values(
            ["_ord", "despachable_hoy", "val_atencion"], ascending=[True, False, False]
        )
        out = out.drop(columns=["_ord"]).reset_index()
        return self._anotar_prioridad(out)

    # ------------------------------------------------------------------
    # Prioridad comercial + tramite + pedido raiz (columna aparte; NO toca
    # la escala P1-P5, que sigue midiendo cobertura de stock).
    # ------------------------------------------------------------------
    def _anotar_prioridad(self, out: pd.DataFrame) -> pd.DataFrame:
        """Agrega prioridad_comercial / requiere / tiene_oc / pedido_raiz.

        prioridad_comercial: 1 ANTICIPO -> 2 CANJE -> 3 LETRA -> 4 CONTADO ->
        5 FACTURA y todas las demas. Es solo orden/filtro: no altera P1-P5.
        requiere: tramite pendiente (APROBAR_PEDIDO / APROBAR_PLANILLA /
        SOLICITAR_OC / ""). tiene_oc: SI/NO (la OC falta 63% de las veces).
        """
        if out is None or len(out) == 0:
            return out
        out = out.copy()
        fam = (
            out["familia"]
            if "familia" in out.columns
            else out.get("CONDICION_PAGO", pd.Series("", index=out.index)).map(
                normalize_cond_familia
            )
        )
        out["prioridad_comercial"] = fam.map(prioridad_comercial)
        out["prioridad_comercial_etq"] = out["prioridad_comercial"].map(etiqueta_prioridad)
        est = out.get("estado_pedido", out.get("PEDIDO_ESTADO", pd.Series("", index=out.index)))
        pl = out.get("NOM_ESTADO_PLANILLA_ANTICIPO", pd.Series("", index=out.index))
        oc = out.get("PEDIDO_ORD_COMPRA", pd.Series("", index=out.index))
        out["requiere"] = [
            requiere_tramite(f, e, p, o)
            for f, e, p, o in zip(fam.astype(str), est.astype(str), pl.astype(str), oc.astype(str))
        ]
        out["tiene_oc"] = ["SI" if str(o).strip() not in ("", "nan", "None") else "NO" for o in oc]
        idc = self.get_pedido_id_col() or "ID_PEDIDO"
        if idc in out.columns:
            out["pedido_raiz"] = out[idc].map(pedido_raiz)
            out["es_complemento"] = ["SI" if es_complemento(p) else "NO" for p in out[idc]]
        else:
            out["pedido_raiz"] = ""
            out["es_complemento"] = "NO"
        return out

    def get_por_vendedor(self, familia: str = "ANTICIPO", umbral: float = 1200.0) -> pd.DataFrame:
        """Drill vendedor -> cliente -> pedido con subtotales por vendedor.

        Replica la tabla dinamica del prototipo VBA sin depender de Excel:
        una fila por vendedor con su subtotal, y bajo cada uno los pedidos
        (cliente incluido) ordenados por monto a despachar.
        """
        acc = self.resumen_accion_pedido(familia, umbral)
        bloq = self.get_pedidos_bloqueados()
        frames = []
        if not acc.empty:
            frames.append(acc)
        if not bloq.empty:
            frames.append(bloq)
        if not frames:
            return pd.DataFrame()
        ped = pd.concat(frames, ignore_index=True, sort=False)

        # Reconciliar columnas entre ambos orígenes
        for c in ("despachable_hoy", "val_atencion"):
            if c not in ped.columns:
                ped[c] = 0.0
        ped["monto_hoy"] = pd.to_numeric(ped["despachable_hoy"], errors="coerce").fillna(0)
        ped["monto_total"] = pd.to_numeric(ped.get("val_atencion", 0), errors="coerce").fillna(0)

        vn = "NOM_VENDEDOR" if "NOM_VENDEDOR" in ped.columns else "ID_VENDEDOR"
        vi = "ID_VENDEDOR" if "ID_VENDEDOR" in ped.columns else vn
        rows: list[dict] = []
        subtotal_rows: list[dict] = []
        gped = ped.groupby(vn, dropna=False)
        for vendedor, g in gped:
            sub_hoy = float(g["monto_hoy"].sum())
            sub_tot = float(g["monto_total"].sum())
            g2 = g.sort_values(["monto_hoy", "monto_total"], ascending=False)
            subtotal_rows.append(
                {
                    "nivel": "VENDEDOR",
                    "ID_VENDEDOR": str(g[vi].iloc[0] if vi in g.columns else ""),
                    "NOM_VENDEDOR": str(vendedor),
                    "ID_PEDIDO": "",
                    "COD_CLIENTE": "",
                    "NOM_CLIENTE": "(SUBTOTAL)",
                    "CONDICION_PAGO": "",
                    "PEDIDO_ESTADO": "",
                    "estado_accion": "",
                    "prio_sugerida": "",
                    "filas": int(len(g2)),
                    "pct_cubierto": round(
                        float(
                            pd.to_numeric(g.get("pct_cubierto", 0), errors="coerce")
                            .fillna(0)
                            .mean()
                        ),
                        1,
                    )
                    if "pct_cubierto" in g.columns
                    else 0.0,
                    "monto_hoy": round(sub_hoy, 2),
                    "monto_total": round(sub_tot, 2),
                    "kg_hoy": round(
                        float(pd.to_numeric(g.get("kg_hoy", 0), errors="coerce").fillna(0).sum()), 1
                    )
                    if "kg_hoy" in g.columns
                    else 0.0,
                    "casi_cierra": int(
                        pd.to_numeric(g.get("casi_cierra", False), errors="coerce").fillna(0).sum()
                    )
                    if "casi_cierra" in g.columns
                    else 0,
                    "accion_1": f"{len(g2)} pedidos",
                }
            )
            for _, r in g2.iterrows():
                rows.append(
                    {
                        "nivel": "PEDIDO",
                        "ID_VENDEDOR": str(r.get("ID_VENDEDOR", "")),
                        "NOM_VENDEDOR": str(vendedor),
                        "ID_PEDIDO": str(r.get("ID_PEDIDO", "")),
                        "COD_CLIENTE": str(r.get("COD_CLIENTE", "")),
                        "NOM_CLIENTE": str(r.get("NOM_CLIENTE", "")),
                        "CONDICION_PAGO": str(r.get("CONDICION_PAGO", "")),
                        "PEDIDO_ESTADO": str(r.get("PEDIDO_ESTADO", "")),
                        "estado_accion": str(r.get("estado_accion", "")),
                        "prio_sugerida": str(r.get("prio_sugerida", "")),
                        "filas": int(pd.to_numeric(r.get("filas", 0), errors="coerce") or 0),
                        "pct_cubierto": float(
                            pd.to_numeric(r.get("pct_cubierto", 0), errors="coerce") or 0
                        ),
                        "monto_hoy": round(
                            float(pd.to_numeric(r.get("monto_hoy", 0), errors="coerce") or 0), 2
                        ),
                        "monto_total": round(
                            float(pd.to_numeric(r.get("monto_total", 0), errors="coerce") or 0), 2
                        ),
                        "kg_hoy": float(pd.to_numeric(r.get("kg_hoy", 0), errors="coerce") or 0),
                        "casi_cierra": bool(r.get("casi_cierra", False)),
                        "accion_1": str(r.get("accion_1", "")),
                    }
                )

        subs = (
            pd.DataFrame(subtotal_rows)
            .sort_values("monto_hoy", ascending=False)
            .reset_index(drop=True)
        )
        out_rows: list[dict] = []
        for _, sub in subs.iterrows():
            out_rows.append(sub.to_dict())
            vend_rows = [r for r in rows if r["NOM_VENDEDOR"] == sub["NOM_VENDEDOR"]]
            out_rows.extend(vend_rows)
        return pd.DataFrame(out_rows)

    def get_pedidos_bloqueados(self) -> pd.DataFrame:
        """Pedidos INGRESADO con stock listo (accion: aprobar).

        Linea valida + saldo>0, cualquier condicion de pago.
        """
        df = self.df
        if "PEDIDO_ESTADO" not in df.columns or "saldo" not in df.columns:
            return pd.DataFrame()
        sub = df[
            (df["PEDIDO_ESTADO"].astype(str).str.strip().str.upper() == "INGRESADO")
            & (pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0)
        ].copy()
        if "es_linea_valida" in sub.columns:
            sub = sub[sub["es_linea_valida"].fillna(False).astype(bool)]
        if sub.empty:
            return sub.reset_index(drop=True)
        id_col = self.get_pedido_id_col() or "ID_PEDIDO"
        if id_col not in sub.columns:
            return pd.DataFrame()
        sub["_ves"] = pd.to_numeric(
            sub.get("stock_real", sub.get("stock_api_ves", 0)), errors="coerce"
        ).fillna(0)
        sub["_saldo"] = pd.to_numeric(sub.get("saldo", 0), errors="coerce").fillna(0)
        sub["_cub"] = (sub["_ves"] >= sub["_saldo"]).astype(int)
        # Precio unitario efectivo (ponderado por unidades pendientes), igual
        # que en resumen_accion_pedido: el precio sale del reporte de vigencias.
        if "precio_unitario" in sub.columns:
            _pu = pd.to_numeric(sub["precio_unitario"], errors="coerce").fillna(0)
            sub["_pu_x_sl"] = _pu * sub["_saldo"]
        g = sub.groupby(id_col, dropna=False)
        out = pd.DataFrame(
            {
                "filas": g.size(),
                "saldo": g["_saldo"].sum(),
                "cubiertas_ves": g["_cub"].sum(),
                "valor": g["valor_saldo"].sum() if "valor_saldo" in sub else 0,
            }
        )
        if "precio_unitario" in sub.columns:
            out["precio_unitario"] = (
                (g["_pu_x_sl"].sum() / g["_saldo"].sum().replace(0, pd.NA)).astype(float).round(2)
            )
        else:
            out["precio_unitario"] = 0.0
        if "precio_verificable" in sub.columns:
            sub["_verif"] = sub["precio_verificable"].astype(bool)
            sub["_ok_verif"] = sub["precio_coherente"].astype(bool) & sub["_verif"]
            out["precios_verificados"] = (
                sub["precio_verificable"].astype(bool).groupby(sub[id_col], dropna=False).sum()
            )
            out["precios_coherentes"] = sub["_ok_verif"].groupby(sub[id_col], dropna=False).sum()
        for c in [
            "NRO_DOCUMENTO",
            "COD_CLIENTE",
            "NOM_CLIENTE",
            "ID_VENDEDOR",
            "NOM_VENDEDOR",
            "PEDIDO_FECHA",
            "CONDICION_PAGO",
            "PEDIDO_ESTADO",
        ]:
            if c in sub.columns:
                out[c] = g[c].first()
        if "dias_desde_pedido" in sub.columns:
            out["dias"] = g["dias_desde_pedido"].max()
        else:
            out["dias"] = 0
        _fi = pd.to_numeric(out["filas"], errors="coerce").fillna(0)
        _fc = pd.to_numeric(out["cubiertas_ves"], errors="coerce").fillna(0)
        out["pct_cubierto"] = (_fc / _fi.replace(0, 1) * 100).round(1)
        # Estados de linea del pedido (mismo criterio que resumen_accion_pedido).
        if "estado_linea" in sub.columns:
            _est = (
                sub["estado_linea"]
                .astype(str)
                .str.strip()
                .str.upper()
                .replace({"NAN": "", "NONE": ""})
            )
            out["estados_linea"] = _est.groupby(sub[id_col], dropna=False).apply(
                lambda s: ", ".join(sorted({v for v in s if v}))
            )
        else:
            out["estados_linea"] = ""
        out["estado_linea"] = out["estados_linea"]
        out["estado_accion"] = "BLOQUEADO_ESTADO"
        out["familia"] = (
            out["CONDICION_PAGO"].map(normalize_cond_familia)
            if "CONDICION_PAGO" in out.columns
            else "OTRO"
        )
        out["prio_sugerida"] = "P4"
        out["accion_1"] = "APROBAR_PEDIDO"
        out["accion_2"] = "DESPACHAR" if (_fc > 0).any() else "ACUMULAR"
        out["despachable_hoy"] = 0.0
        out["si_se_aprueba"] = 0.0  # no es bloqueo de planilla sino de estado
        out["val_atencion"] = 0.0
        out["val_pendiente"] = out["valor"]
        out["trasladable"] = 0.0
        out["pct_cant"] = 0.0
        out["pct_valor"] = 0.0
        out = out.reset_index().sort_values("valor", ascending=False).reset_index(drop=True)
        return self._anotar_prioridad(out)

    def resumen_cobranza(self, umbral_dias: int = 10) -> pd.DataFrame:
        """Planillas ANTICIPO no aprobadas con dias (proxy PEDIDO_FECHA)."""
        df = self.df
        need = {"CONDICION_PAGO", "saldo", "NOM_ESTADO_PLANILLA_ANTICIPO"}
        if not need.issubset(set(df.columns)):
            return pd.DataFrame()
        sub = df[
            (df["CONDICION_PAGO"].astype(str).str.strip().str.upper() == "ANTICIPO EN LETRAS")
            & (pd.to_numeric(df["saldo"], errors="coerce").fillna(0) > 0)
            & (
                df["NOM_ESTADO_PLANILLA_ANTICIPO"].astype(str).str.strip().str.upper()
                == "INGRESADO"
            )
        ].copy()
        if sub.empty:
            return sub.reset_index(drop=True)
        if "dias_planilla" in sub.columns:
            sub["_dias"] = (
                pd.to_numeric(sub["dias_planilla"], errors="coerce").fillna(0).astype(int)
            )
        elif "PEDIDO_FECHA" in sub.columns:
            _f = pd.to_datetime(sub["PEDIDO_FECHA"], dayfirst=True, errors="coerce")
            sub["_dias"] = (
                (pd.Timestamp.now().normalize() - _f).dt.days.clip(lower=0).fillna(0).astype(int)
            )
        else:
            sub["_dias"] = 0
        plan_col = "ID_PLANILLA_ANTICIPO" if "ID_PLANILLA_ANTICIPO" in sub.columns else None
        id_col = self.get_pedido_id_col() or "ID_PEDIDO"
        keys = [k for k in [plan_col, id_col] if k and k in sub.columns] or [id_col]
        g = sub.groupby(keys, dropna=False)
        out = pd.DataFrame(
            {
                "dias": g["_dias"].max(),
                "filas": g.size(),
                "saldo": g["saldo"].sum() if "saldo" in sub else 0,
                "valor": g["valor_saldo"].sum() if "valor_saldo" in sub else 0,
            }
        )
        for c in [
            "NOM_VENDEDOR",
            "ID_VENDEDOR",
            "NOM_CLIENTE",
            "COD_CLIENTE",
            "PEDIDO_FECHA",
            "NRO_DOCUMENTO",
        ]:
            if c in sub.columns:
                out[c] = g[c].first()
        out["bucket"] = pd.cut(
            out["dias"],
            bins=[-1, 5, 10, 20, float("inf")],
            labels=["0-5", "6-10", "11-20", ">20"],
        ).astype(str)
        out["accion"] = out["dias"].apply(
            lambda d: "escalar" if d > umbral_dias else "seguimiento normal"
        )
        return out.reset_index().sort_values("dias", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Vista comparativa pedido vs entregado vs saldo, por estado_linea
    # ------------------------------------------------------------------
    def resumen_avance_pedido(self, familia: str | None = None) -> pd.DataFrame:
        """Una fila por PEDIDO x estado_linea (comparativa de avance).

        Responde "de cuanto era el pedido, cuanto entregue y cuanto debo",
        desglosado por estado_linea (NUEVO/IMPORTADO/TRADICIONAL/NACIONAL).
        La suma de las filas de un pedido es exactamente su total.

        Columnas: pedido, pedido_raiz, es_complemento, cliente, vendedor,
        condicion, familia, prioridad_comercial, estado_pedido, requiere,
        tiene_oc, estado_linea, lineas, pedido_und, entregado_und, saldo_und,
        pct_avance, valor_saldo, VES_cubre, dias.
        """
        df = self.df.copy() if self.df is not None else pd.DataFrame()
        if df.empty:
            return df
        idc = self.get_pedido_id_col() or "ID_PEDIDO"
        if idc not in df.columns:
            return pd.DataFrame()
        if familia:
            df = df[self._familia_serie(df) == str(familia).strip().upper()]
        if df.empty:
            return pd.DataFrame()

        def _num(col, default=0.0):
            if col not in df.columns:
                df[col] = default
            return pd.to_numeric(df[col], errors="coerce").fillna(default)

        df["_ped"] = _num("CAN_PEDIDO")
        df["_des"] = _num("CAN_DESPACHO")
        df["_sal"] = _num("saldo")
        df["_vsal"] = _num("valor_saldo")
        df["_ves"] = _num("stock_real")
        df["_cub"] = (df["_ves"] >= df["_sal"]).astype(int)
        df["_estl"] = (
            df.get("estado_linea", pd.Series("", index=df.index))
            .astype(str)
            .str.strip()
            .str.upper()
            .replace({"NAN": "", "NONE": ""})
        )
        df["_estl"] = df["_estl"].replace({"": "(sin estado)"})

        keys = [idc, "_estl"]
        g = df.groupby(keys, dropna=False)
        out = (
            pd.DataFrame(
                {
                    "lineas": g.size(),
                    "pedido_und": g["_ped"].sum(),
                    "entregado_und": g["_des"].sum(),
                    "saldo_und": g["_sal"].sum(),
                    "valor_saldo": g["_vsal"].sum(),
                    "VES_cubre": g["_cub"].sum(),
                    "dias": g["dias_desde_pedido"].max() if "dias_desde_pedido" in df else 0,
                }
            )
            .reset_index()
            .rename(columns={"_estl": "estado_linea", idc: "pedido"})
        )
        out["pct_avance"] = (out["entregado_und"] / out["pedido_und"].replace(0, 1) * 100).round(1)
        for c, nombre in (
            ("NOM_CLIENTE", "cliente"),
            ("COD_CLIENTE", "cod_cliente"),
            ("NOM_VENDEDOR", "vendedor"),
            ("ID_VENDEDOR", "id_vendedor"),
            ("CONDICION_PAGO", "condicion"),
            ("PEDIDO_ESTADO", "estado_pedido"),
            ("NOM_ESTADO_PLANILLA_ANTICIPO", "planilla"),
            ("PEDIDO_ORD_COMPRA", "orden_compra"),
            ("PEDIDO_FECHA", "fecha"),
        ):
            if c in df.columns:
                out[nombre] = df.groupby(keys, dropna=False)[c].first().values
        out["familia"] = (
            out["condicion"].map(normalize_cond_familia) if "condicion" in out else "OTRO"
        )
        out["prioridad_comercial"] = out["familia"].map(prioridad_comercial)
        out["prioridad_comercial_etq"] = out["prioridad_comercial"].map(etiqueta_prioridad)
        out["requiere"] = [
            requiere_tramite(f, e, p, o)
            for f, e, p, o in zip(
                out["familia"].astype(str),
                out.get("estado_pedido", pd.Series("", index=out.index)).astype(str),
                out.get("planilla", pd.Series("", index=out.index)).astype(str),
                out.get("orden_compra", pd.Series("", index=out.index)).astype(str),
            )
        ]
        out["tiene_oc"] = [
            "SI" if str(o).strip() not in ("", "nan", "None") else "NO"
            for o in out.get("orden_compra", pd.Series("", index=out.index))
        ]
        out["pedido_raiz"] = out["pedido"].map(pedido_raiz)
        out["es_complemento"] = ["SI" if es_complemento(p) else "NO" for p in out["pedido"]]
        # Orden: por raiz -> pedido -> estado (bloques contiguos para filtrar).
        out = out.sort_values(
            ["pedido_raiz", "pedido", "estado_linea"], ascending=[True, True, True]
        )
        return out.reset_index(drop=True)

    def resumen_por_cliente(self, familia: str | None = None) -> pd.DataFrame:
        """Una fila por VENDEDOR x CLIENTE con desglose por estado_linea.

        Responde "del vendedor 052, al cliente xxx, cuanto TRADICIONAL y
        cuanto NUEVO le debemos, y de cuanto era el pedido".
        """
        av = self.resumen_avance_pedido(familia)
        if av.empty:
            return av
        cols_est = ["NUEVO", "IMPORTADO", "TRADICIONAL", "NACIONAL"]

        def _piv(campo):
            p = av.pivot_table(
                index=["id_vendedor", "vendedor", "cod_cliente", "cliente"],
                columns="estado_linea",
                values=campo,
                aggfunc="sum",
                fill_value=0,
            )
            return p

        base = av.groupby(["id_vendedor", "vendedor", "cod_cliente", "cliente"], dropna=False).agg(
            pedidos=("pedido", "nunique"),
            lineas=("lineas", "sum"),
            pedido_und=("pedido_und", "sum"),
            entregado_und=("entregado_und", "sum"),
            saldo_und=("saldo_und", "sum"),
            valor_saldo=("valor_saldo", "sum"),
        )
        for campo, sufijo in (("saldo_und", "sal"), ("pedido_und", "ped")):
            p = _piv(campo)
            for est in cols_est:
                if est in p.columns:
                    base[f"{est}_{sufijo}"] = p[est]
                else:
                    base[f"{est}_{sufijo}"] = 0
        base = base.fillna(0)
        base["pct_avance"] = (base["entregado_und"] / base["pedido_und"].replace(0, 1) * 100).round(
            1
        )
        return (
            base.reset_index()
            .sort_values(["vendedor", "valor_saldo"], ascending=[True, False])
            .reset_index(drop=True)
        )
