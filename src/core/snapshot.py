"""
Gestor de Snapshots para seguimiento de atención.

Permite:
- Guardar snapshot del estado actual de pedidos
- Comparar con carga futura para ver progreso
- Identificar: atendidos, pendientes nuevos, sin movimiento
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


class SnapshotManager:
    """Guarda y compara snapshots de pedidos."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._snapshots_dir = cache_dir / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, df: pd.DataFrame, label: str | None = None) -> Path:
        """Guarda snapshot SOLO de pendientes (saldo > 0).
        
        Los atendidos (saldo <= 0) ya no necesitan seguimiento.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = label or f"snapshot_{ts}"
        path = self._snapshots_dir / f"{label}.csv"

        # Calcular saldo si no existe
        if "saldo" not in df.columns and "CAN_PEDIDO" in df.columns:
            df["saldo"] = df["CAN_PEDIDO"] - df["CAN_DESPACHO"]

        # SOLO PENDIENTES: saldo > 0
        pendientes = df[df["saldo"] > 0].copy() if "saldo" in df else df.copy()

        # Guardar columnas clave para comparacion
        cols = ["ID_PEDIDO", "ID_ARTICULO", "CAN_PEDIDO", "CAN_DESPACHO", "saldo", "PEDIDO_ESTADO"]
        cols = [c for c in cols if c in pendientes.columns]
        snapshot_df = pendientes[cols].copy()
        snapshot_df["_snapshot_ts"] = ts
        snapshot_df.to_csv(path, index=False)

        # Guardar metadata
        meta = {
            "ts": ts,
            "epoch": time.time(),
            "label": label,
            "total_items": len(pendientes),
            "total_saldo": float(pendientes["saldo"].sum()) if "saldo" in pendientes else 0,
            "file": str(path.name),
        }
        meta_path = self._snapshots_dir / f"{label}.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        return path

    def latest_label(self, prefixes: tuple[str, ...] = ("foto_", "auto_")) -> str | None:
        """Etiqueta del snapshot mas reciente util como foto (None si no hay).

        Ignora snapshots de prueba (p.ej. `test_snapshot`) y ordena por fecha
        de archivo, no por nombre (los nombres no siempre ordenan por tiempo).
        """
        metas = [
            p for p in self._snapshots_dir.glob("*.json")
            if p.stem.startswith(prefixes) and p.is_file()
        ]
        if not metas:
            return None
        return max(metas, key=lambda p: p.stat().st_mtime).stem

    def label_meta(self, label: str) -> dict:
        """Metadata de un snapshot ({} si no existe)."""
        path = self._snapshots_dir / f"{label}.json"
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def dias_entre(self, base_label: str) -> int | None:
        """Dias entre el snapshot base y hoy (para el reporte foto del dia).

        Acepta meta con `epoch` (nuevos) o con `ts` en texto
        "YYYYMMDD_HHMMSS" (snapshots anteriores).
        """
        meta = self.label_meta(base_label)
        if not meta:
            return None
        when = None
        if meta.get("epoch"):
            try:
                when = datetime.fromtimestamp(float(meta["epoch"]))
            except (TypeError, ValueError, OSError):
                when = None
        if when is None and meta.get("ts"):
            try:
                when = datetime.strptime(str(meta["ts"]), "%Y%m%d_%H%M%S")
            except (TypeError, ValueError):
                return None
        if when is None:
            return None
        return max((datetime.now() - when).days, 0)

    def list_snapshots(self) -> list[dict]:
        """Lista snapshots guardados."""
        snapshots = []
        for meta_file in sorted(self._snapshots_dir.glob("*.json"), reverse=True):
            with open(meta_file) as f:
                snapshots.append(json.load(f))
        return snapshots

    def prune(self, keep: int = 30) -> None:
        """Mantiene solo los `keep` snapshots mas recientes (por meta)."""
        metas = sorted(self._snapshots_dir.glob("*.json"), reverse=True)
        for meta in metas[keep:]:
            label = meta.stem
            meta.unlink(missing_ok=True)
            csv_path = self._snapshots_dir / f"{label}.csv"
            csv_path.unlink(missing_ok=True)

    def _merge_keys(self, df: pd.DataFrame) -> list[str]:
        """Columnas id para el merge por pedido + sku."""
        keys = ["ID_PEDIDO", "ID_ARTICULO"]
        if "ID_PEDIDO" not in df.columns:
            return []
        if "ID_ARTICULO" not in df.columns and "SKU" in df.columns:
            keys[1] = "SKU"
        return [k for k in keys if k in df.columns]

    def compare_current(self, base_label: str, current_df) -> tuple[pd.DataFrame, dict]:
        """Compara un snapshot guardado contra el estado actual (vivo).

        Retorna (merged_df, summary) con clasificacion de cambios:
        NUEVO / ATENDIDO / AJUSTE / SIN CAMBIO / ELIMINADO.
        """
        base_path = self._snapshots_dir / f"{base_label}.csv"
        if not base_path.exists() or current_df is None or len(current_df) == 0:
            return pd.DataFrame(), {}

        base_df = pd.read_csv(base_path)
        keys = self._merge_keys(current_df)
        keys_base = [k for k in ["ID_PEDIDO", "ID_ARTICULO"] if k in base_df.columns]
        if not keys or not keys_base:
            return pd.DataFrame(), {}

        cur = current_df.copy()
        if "saldo" not in cur.columns and "CAN_PEDIDO" in cur.columns:
            cur["saldo"] = cur["CAN_PEDIDO"] - cur["CAN_DESPACHO"]
        cur = cur[cur["saldo"] > 0].copy()
        # Mapeo de despacho por clave si hay duplicados (tomar el maximo despachado en el corte)
        desp_map = cur.groupby(keys)[["CAN_DESPACHO", "saldo"]].max() if len(keys) == 2 else None
        new_rows = []
        base_visited = set()
        for _, brow in base_df.iterrows():
            b_key = tuple(str(brow.get(k, "")) for k in ["ID_PEDIDO", "ID_ARTICULO"])
            base_visited.add(b_key)
            desp_antes = float(brow.get("CAN_DESPACHO", 0) or 0)
            match = None
            if desp_map is not None and isinstance(desp_map, pd.DataFrame):
                match = desp_map.loc[b_key] if b_key in desp_map.index else None
            desp_ahora = float(match.get("CAN_DESPACHO", 0)) if match is not None else None
            if match is None:
                cambio = "ELIMINADO"
            elif desp_ahora > desp_antes:
                cambio = "ATENDIDO"
            elif desp_ahora < desp_antes:
                cambio = "AJUSTE"
            else:
                cambio = "SIN CAMBIO"
            new_rows.append({
                "ID_PEDIDO": brow.get("ID_PEDIDO", ""),
                "ID_ARTICULO": brow.get("ID_ARTICULO", ""),
                "CAN_DESPACHO_antes": desp_antes,
                "CAN_DESPACHO_ahora": desp_ahora if match is not None else "",
                "cambio": cambio,
            })
        # NUEVOS: presentes en el corte actual pero no en el snapshot base
        if desp_map is not None and isinstance(desp_map, pd.DataFrame):
            for key, match in desp_map.iterrows():
                if tuple(key) not in base_visited:
                    new_rows.append({
                        "ID_PEDIDO": key[0], "ID_ARTICULO": key[1],
                        "CAN_DESPACHO_antes": "", "CAN_DESPACHO_ahora": match.get("CAN_DESPACHO", 0),
                        "cambio": "NUEVO",
                    })
        merged = pd.DataFrame(new_rows)
        if merged.empty:
            return merged, {}

        order = ["NUEVO", "ATENDIDO", "AJUSTE", "SIN CAMBIO", "ELIMINADO"]
        counts = {c: int((merged["cambio"] == c).sum()) for c in order}
        summary = {
            "base": base_label,
            "items_base": len(base_df),
            "pendientes_actuales": len(cur),
            "nuevos": counts["NUEVO"],
            "atendidos": counts["ATENDIDO"],
            "ajustes": counts["AJUSTE"],
            "sin_cambio": counts["SIN CAMBIO"],
            "eliminados": counts["ELIMINADO"],
        }
        merged = merged.sort_values("cambio").reset_index(drop=True)
        return merged, summary

    def compare_snapshots(
        self, base_label: str, new_label: str
    ) -> pd.DataFrame:
        """Compara dos snapshots y muestra cambios."""
        base_path = self._snapshots_dir / f"{base_label}.csv"
        new_path = self._snapshots_dir / f"{new_label}.csv"

        if not base_path.exists() or not new_path.exists():
            return pd.DataFrame()

        base_df = pd.read_csv(base_path)
        new_df = pd.read_csv(new_path)

        # Merge por pedido+SKU
        merged = base_df.merge(
            new_df,
            on=["ID_PEDIDO", "ID_ARTICULO"],
            how="outer",
            suffixes=("_antes", "_ahora"),
        )

        # Clasificar cambios
        def _classify(row):
            if pd.isna(row.get("CAN_DESPACHO_antes")):
                return "NUEVO"
            if pd.isna(row.get("CAN_DESPACHO_ahora")):
                return "ELIMINADO"
            desp_antes = row["CAN_DESPACHO_antes"]
            desp_ahora = row["CAN_DESPACHO_ahora"]
            if desp_ahora > desp_antes:
                return "ATENDIDO"
            elif desp_ahora < desp_antes:
                return "AJUSTE"
            else:
                return "SIN CAMBIO"

        merged["cambio"] = merged.apply(_classify, axis=1)
        return merged


class StateLineFilter:
    """Filtro por estado de linea con badges."""

    STATES = {
        "todos": "Todos",
        "nuevo": "NUEVO",
        "tradicional": "TRADICIONAL",
        "importado": "IMPORTADO",
        "sin_estado": "(Sin Estado)",
    }

    @classmethod
    def get_filter_mask(cls, df: pd.DataFrame, state: str) -> pd.Series:
        """Retorna mascara de filtro segun estado."""
        # Si no existe la columna estado_linea, retornar todos
        if "estado_linea" not in df.columns:
            return pd.Series(True, index=df.index)

        if state == "todos":
            return pd.Series(True, index=df.index)

        col = df["estado_linea"].astype(str).str.upper().str.strip()
        if state == "nuevo":
            return col.isin(["NUEVO", "NUEVA"])
        elif state == "tradicional":
            return col.isin(["TRADICIONAL", "TRAD"])
        elif state == "importado":
            return col.isin(["IMPORTADO", "IMPORTADA", "IMP"])
        elif state == "sin_estado":
            return col.isin(["", "NAN", "NONE", "NAT"])
        return pd.Series(True, index=df.index)
