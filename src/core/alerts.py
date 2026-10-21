"""
Motor de alertas operativas (sin dependencias de UI).

Cada regla produce una alerta a partir de columnas derivadas del ingester
(estado_vigencia, por_vigencia_consumida, stock_real, es_bloqueado, categoria)
y de la configuracion del usuario (umbral de 'por vencer' y toggles).

Una alerta es un dict con:
  key, title, severity, icon, description, count_pedidos (ID_PEDIDO unicos),
  lineas, unidades (saldo), valor (valor_saldo) y lines (DataFrame de detalle).
"""

from __future__ import annotations

import pandas as pd

# Registro de reglas de alerta (orden de presentacion).
ALERTS: list[dict] = [
    {
        "key": "vencidos_sin_stock",
        "title": "Vencidos sin stock",
        "severity": "error",
        "icon": "EVENT_BUSY",
        "default": True,
        "description": "Pedidos con vigencia vencida y sin stock VES para despachar.",
    },
    {
        "key": "por_vencer",
        "title": "Por vencer",
        "severity": "warning",
        "icon": "ACCESS_TIME",
        "default": True,
        "description": "Pedidos con mas del umbral de vigencia consumida (configurable).",
    },
    {
        "key": "100_atendible",
        "title": "100% atendible",
        "severity": "success",
        "icon": "CHECK_CIRCLE",
        "default": True,
        "description": "Lineas con stock VES suficiente para cubrir el saldo pendiente.",
    },
    {
        "key": "bloqueados_sin_stock",
        "title": "Sin stock (bloqueados)",
        "severity": "warning",
        "icon": "BLOCK",
        "default": True,
        "description": "Saldo pendiente sin stock VES suficiente hoy.",
    },
    {
        "key": "sin_catalogo",
        "title": "Sin catalogo",
        "severity": "warning",
        "icon": "SEARCH_OFF",
        "default": True,
        "description": "SKUs sin categoria (catalogo) con saldo pendiente.",
    },
    {
        "key": "api_offline",
        "title": "API de stock sin conexion",
        "severity": "error",
        "icon": "CLOUD_OFF",
        "default": True,
        "description": "Stock en 0 porque el API de Render no respondio.",
    },
]


def _pedido_col(df: pd.DataFrame) -> str | None:
    for col in ("ID_PEDIDO", "NRO_DOCUMENTO"):
        if col in df.columns:
            return col
    return None


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0)


def compute_alerts(
    df: pd.DataFrame | None,
    *,
    umbral_por_vencer_pct: float = 75.0,
    toggles: dict[str, bool] | None = None,
    api_state: str = "offline",
) -> list[dict]:
    """Calcula las alertas habilitadas sobre el dataframe procesado.

    Args:
        df: DataFrame enriquecido (compute_derived aplicado).
        umbral_por_vencer_pct: % de vigencia consumida para considerar "por vencer".
        toggles: dict {key_alert: bool} para habilitar/deshabilitar reglas.
        api_state: "online"/"offline" (controla la alerta api_offline).

    Returns:
        Lista de alertas (cada una con su DataFrame de detalle en "lines").
    """
    result: list[dict] = []
    if df is None or len(df) == 0:
        return result
    toggles = toggles or {}

    def enabled(key: str, default: bool = True) -> bool:
        return bool(toggles.get(key, default))

    saldo = _num(df, "saldo")
    pend = saldo > 0
    categoria = df.get("categoria", pd.Series("", index=df.index)).astype(str).str.strip()
    sin_cat = categoria.isin(["", "nan"])
    stock_real = _num(df, "stock_real")
    if "es_linea_valida" in df.columns:
        linea_ok = df["es_linea_valida"].fillna(False).astype(bool)
    else:
        linea_ok = pd.Series(True, index=df.index)

    def _meta(sub: pd.DataFrame) -> dict:
        ped = _pedido_col(sub)
        return {
            "count_pedidos": int(sub[ped].nunique()) if ped else int(len(sub)),
            "lineas": int(len(sub)),
            "unidades": float(_num(sub, "saldo").sum()),
            "valor": float(_num(sub, "valor_saldo").sum()),
        }

    for rule in ALERTS:
        key = rule["key"]
        if not enabled(key, rule.get("default", True)):
            continue

        if key == "api_offline":
            if api_state == "offline":
                sub = df[pend].reset_index(drop=True)
                result.append({**rule, **_meta(sub), "lines": sub})
            continue

        if key == "vencidos_sin_stock":
            ev = df.get("estado_vigencia", pd.Series("", index=df.index)).astype(str)
            mask = pend & ev.eq("VENCIDO") & (stock_real <= 0)
        elif key == "por_vencer":
            pvc = _num(df, "por_vigencia_consumida")
            vig = _num(df, "vigencia")
            mask = pend & vig.gt(0) & pvc.ge(float(umbral_por_vencer_pct)) & pvc.lt(100)
        elif key == "100_atendible":
            mask = pend & (~sin_cat) & linea_ok & stock_real.ge(saldo)
        elif key == "bloqueados_sin_stock":
            if "es_bloqueado" in df.columns:
                mask = df["es_bloqueado"].fillna(False).astype(bool)
            else:
                mask = pend & ~(stock_real.ge(saldo) & (~sin_cat) & linea_ok)
        elif key == "sin_catalogo":
            mask = pend & sin_cat
        else:
            continue

        sub = df[mask].reset_index(drop=True)
        if not sub.empty:
            result.append({**rule, **_meta(sub), "lines": sub})

    return result