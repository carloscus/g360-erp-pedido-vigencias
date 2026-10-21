"""
Foto del dia: comparacion contra el snapshot anterior (sin marcado manual).

El seguimiento de avance no depende de que alguien marque pedidos: se guarda
la foto de cada corrida y se compara contra la anterior. Por pedido devuelve
saldo_ayer / saldo_hoy / delta y una clasificacion de cambio:

- ATENDIDO    : el saldo del pedido quedo en 0 (o cayo por completo)
- AVANCE      : el saldo bajo (despacho parcial)
- NUEVO       : el pedido aparecio hoy
- REGRESO     : el saldo subio (ajuste del ERP)
- SIN_CAMBIO  : nadie toco el pedido
- DESAPARECIDO: el pedido ya no esta en la foto de hoy

 degrading offline: si no hay snapshot previo, la foto se emite como
"sin base" con los totales del dia, sin inventar deltas.
"""

from __future__ import annotations

import pandas as pd

_ORDEN = {"NUEVO": 0, "ATENDIDO": 1, "AVANCE": 2, "REGRESO": 3,
          "SIN_CAMBIO": 4}


def _saldo_por_pedido(df: pd.DataFrame, id_col: str = "ID_PEDIDO") -> pd.Series:
    if id_col not in df.columns:
        return pd.Series(dtype=float)
    out = df.copy()
    if "saldo" not in out.columns and "CAN_PEDIDO" in out.columns:
        ped = pd.to_numeric(out["CAN_PEDIDO"], errors="coerce").fillna(0)
        des = pd.to_numeric(out.get("CAN_DESPACHO", 0), errors="coerce").fillna(0)
        out["saldo"] = ped - des
    if "saldo" not in out.columns:
        return pd.Series(dtype=float)
    return out.groupby(id_col, dropna=False)["saldo"].sum()


def foto_del_dia(
    df_actual: pd.DataFrame,
    snapshot_mgr,
    base_label: str | None = None,
    id_col: str = "ID_PEDIDO",
) -> tuple[pd.DataFrame, dict]:
    """Foto del dia vs foto anterior. Retorna (DataFrame, resumen).

    Si `base_label` es None se usa el snapshot mas reciente. Si no existe
    ninguna base, devuelve el resumen del dia con `base=None` y sin deltas.
    """
    hoy = _saldo_por_pedido(df_actual, id_col)
    base_label = base_label or snapshot_mgr.latest_label()
    meta = snapshot_mgr.label_meta(base_label) if base_label else {}
    dias = snapshot_mgr.dias_entre(base_label) if base_label else None

    if not base_label or not meta:
        resumen = {
            "base": None,
            "dias": None,
            "pedidos_hoy": int(hoy.index.nunique()) if len(hoy) else 0,
            "saldo_hoy": round(float(hoy.sum()), 2) if len(hoy) else 0.0,
        }
        return pd.DataFrame(), resumen

    base_path = snapshot_mgr._snapshots_dir / f"{base_label}.csv"  # noqa: SLF001
    if not base_path.exists():
        return pd.DataFrame(), {"base": base_label, "dias": dias,
                                "pedidos_hoy": 0, "saldo_hoy": 0.0}
    ayer = pd.read_csv(base_path)
    if id_col not in ayer.columns:
        ayer = ayer.rename(columns={"ID_PEDIDO": id_col}) if "ID_PEDIDO" in ayer.columns else ayer
    ayer_saldo = _saldo_por_pedido(ayer, id_col)

    pedidos = pd.Index(
        sorted(set(hoy.index.astype(str)) | set(ayer_saldo.index.astype(str)))
    )
    rows = []
    for pid in pedidos:
        h = float(hoy.get(pid, 0) or 0) if pid in hoy.index else None
        a = float(ayer_saldo.get(pid, 0) or 0) if pid in ayer_saldo.index else None
        if a is not None and (h is None or h <= 0):
            # estaba pendiente en la foto anterior y hoy quedo en 0
            cambio, s_hoy, s_ayer = "ATENDIDO", 0.0, a
        elif a is not None and h is not None:
            s_hoy, s_ayer = h, a
            if h < a:
                cambio = "AVANCE"
            elif h > a:
                cambio = "REGRESO"
            else:
                cambio = "SIN_CAMBIO"
        elif a is None and (h or 0) > 0:
            cambio, s_hoy, s_ayer = "NUEVO", h, 0.0
        else:
            # sin pendiente hoy ni ayer: no hay nada que reportar
            continue
        sub = df_actual[df_actual[id_col].astype(str) == str(pid)] if id_col in df_actual.columns else pd.DataFrame()
        rows.append({
            id_col: pid,
            "saldo_ayer": round(s_ayer, 2),
            "saldo_hoy": round(s_hoy, 2),
            "delta": round(s_hoy - s_ayer, 2),
            "cambio": cambio,
            "NOM_VENDEDOR": str(sub["NOM_VENDEDOR"].iloc[0]) if "NOM_VENDEDOR" in sub.columns and len(sub) else "",
            "NOM_CLIENTE": str(sub["NOM_CLIENTE"].iloc[0]) if "NOM_CLIENTE" in sub.columns and len(sub) else "",
            "CONDICION_PAGO": str(sub["CONDICION_PAGO"].iloc[0]) if "CONDICION_PAGO" in sub.columns and len(sub) else "",
            "filas_hoy": int(len(sub)),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out, {"base": base_label, "dias": dias, "pedidos_hoy": 0, "saldo_hoy": 0.0}
    out["_ord"] = out["cambio"].map(_ORDEN).fillna(9)
    out = out.sort_values(["_ord", "delta"]).drop(columns=["_ord"]).reset_index(drop=True)
    att = out[out["cambio"] == "ATENDIDO"]
    resumen = {
        "base": base_label,
        "dias": dias,
        "pedidos_hoy": int((out["saldo_hoy"] > 0).sum()),
        "saldo_hoy": round(float(hoy.sum()), 2) if len(hoy) else 0.0,
        "saldo_ayer": round(float(ayer_saldo.sum()), 2) if len(ayer_saldo) else 0.0,
        "atendidos": int(len(att)),
        "avance": int((out["cambio"] == "AVANCE").sum()),
        "nuevos": int((out["cambio"] == "NUEVO").sum()),
        "regresos": int((out["cambio"] == "REGRESO").sum()),
        "sin_cambio": int((out["cambio"] == "SIN_CAMBIO").sum()),
        "delta_total": round(float(out["delta"].sum()), 2),
        "atendidos_valor": round(
            float(
                df_actual.loc[df_actual[id_col].astype(str).isin(att[id_col].astype(str)),
                             "valor_saldo"].sum()
            ) if "valor_saldo" in df_actual.columns and not att.empty else 0.0, 2
        ),
    }
    return out, resumen
