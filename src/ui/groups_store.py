"""
Almacen local (JSON) de grupos de prioridad para el monitor de pedidos.

Un grupo agrupa varios clientes, vendedores y/o pedidos (ID_PEDIDO) que se
quieren gestionar juntos al generar ordenes de despacho manuales. Se persiste
en .cache/groups.json y es exportable a XLSX.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from src.config.settings import DATA_DIR

_GROUPS_FILE = DATA_DIR / "groups.json"


class GroupsStore:
    """Persistencia de grupos de prioridad en JSON local."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _GROUPS_FILE

    # ---------------------------------------------------------------
    def load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save(self, groups: list[dict]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(groups, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------------------------------------------------------------
    def add(
        self,
        nombre: str,
        clientes: list[str] | None = None,
        vendedores: list[str] | None = None,
        pedidos: list[str] | None = None,
    ) -> dict:
        groups = self.load()
        grupo = {
            "id": uuid.uuid4().hex[:10],
            "nombre": (nombre or "Grupo sin nombre").strip(),
            "clientes": [str(c) for c in (clientes or [])],
            "vendedores": [str(v) for v in (vendedores or [])],
            "pedidos": [str(p) for p in (pedidos or [])],
            "created": time.time(),
        }
        groups.insert(0, grupo)
        self._save(groups)
        return grupo

    def delete(self, group_id: str) -> None:
        groups = [g for g in self.load() if g.get("id") != group_id]
        self._save(groups)

    def get(self, group_id: str) -> dict | None:
        for g in self.load():
            if g.get("id") == group_id:
                return g
        return None

    # ---------------------------------------------------------------
    def filter_df(self, df, group: dict | None):
        """Devuelve las filas del DataFrame que pertenecen al grupo."""
        if group is None or df is None or len(df) == 0:
            return None
        clientes = {str(c) for c in group.get("clientes", [])}
        vendedores = {str(v) for v in group.get("vendedores", [])}
        pedidos = {str(p) for p in group.get("pedidos", [])}
        if not (clientes or vendedores or pedidos):
            return None

        mask = [False] * len(df)
        cols = set(df.columns)
        for i, row in df.iterrows():
            ok = False
            if clientes and "COD_CLIENTE" in cols and str(row.get("COD_CLIENTE", "")) in clientes:
                ok = True
            if not ok and vendedores and "ID_VENDEDOR" in cols and str(row.get("ID_VENDEDOR", "")) in vendedores:
                ok = True
            if not ok and pedidos and "ID_PEDIDO" in cols and str(row.get("ID_PEDIDO", "")) in pedidos:
                ok = True
            mask[i] = ok
        return df[mask].reset_index(drop=True)