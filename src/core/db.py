"""
Persistencia SQLite acotada para g360-erp-pedido-vigencias.

No reemplaza el flujo en memoria (DataFrames + PedidosAnalytics). Guarda SOLO
lo que necesita sobrevivir entre cargas y las decisiones manuales del usuario:

- importaciones      : trazabilidad de archivos procesados (hash para detectar
                       re-procesos y comparar con cargas anteriores).
- seguimiento         : prioridad, anclas, observaciones y fecha de revision.
                       Dato manual, separado de la informacion del Excel.
- snapshots           : captura diaria de cabeceras (lab manual o automatica).
- snapshot_detalles   : estado de cada linea (id_pedido + id_articulo) por
                       captura. Conserva el pasado aunque el Excel del
                       dia ya no muestre un pedido ya completado.

La identidad probada sobre datos reales es (ID_PEDIDO, ID_ARTICULO): unica
dentro de un archivo, sin NAs y sin duplicados por almacen.

El esquema se versiona con PRAGMA user_version; cada entrada de MIGRATIONS es
un bloque de SQL aplicado en orden solo si la version actual es anterior.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config.settings import DATA_DIR

_log = logging.getLogger("g360.pedido_vigencias")

DEFAULT_DB_PATH = DATA_DIR / "pedidos.db"

SCHEMA_VERSION = 1

MIGRATIONS: list[str] = [
    # v1: importaciones + seguimiento + snapshots + snapshot_detalles
    """
    CREATE TABLE IF NOT EXISTS importaciones (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        filename   TEXT NOT NULL,
        file_hash  TEXT NOT NULL,
        filas      INTEGER NOT NULL DEFAULT 0,
        api_state  TEXT NOT NULL DEFAULT 'offline',
        resultado  TEXT NOT NULL DEFAULT 'ok',
        mensaje    TEXT,
        creado_en  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_importaciones_hash
        ON importaciones (file_hash);

    CREATE TABLE IF NOT EXISTS seguimiento (
        tipo          TEXT NOT NULL CHECK (tipo IN ('pedido', 'cliente', 'articulo')),
        referencia    TEXT NOT NULL,
        prioridad     INTEGER,
        anclado       INTEGER NOT NULL DEFAULT 0,
        observaciones TEXT,
        fecha_revision TEXT,
        actualizado_en TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (tipo, referencia)
    );
    CREATE INDEX IF NOT EXISTS idx_seguimiento_anclado
        ON seguimiento (anclado);

    CREATE TABLE IF NOT EXISTS snapshots (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT NOT NULL,
        ts          TEXT NOT NULL,
        fecha       TEXT,
        total_items INTEGER NOT NULL DEFAULT 0,
        total_saldo REAL NOT NULL DEFAULT 0,
        archivo     TEXT,
        creado_en   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots (ts);

    CREATE TABLE IF NOT EXISTS snapshot_detalles (
        snapshot_id  INTEGER NOT NULL REFERENCES snapshots (id) ON DELETE CASCADE,
        id_pedido    TEXT NOT NULL,
        id_articulo  TEXT NOT NULL,
        can_pedido   REAL NOT NULL DEFAULT 0,
        can_despacho REAL NOT NULL DEFAULT 0,
        saldo        REAL NOT NULL DEFAULT 0,
        pedido_estado TEXT,
        PRIMARY KEY (snapshot_id, id_pedido, id_articulo)
    );
    CREATE INDEX IF NOT EXISTS idx_snapshot_det_pedido
        ON snapshot_detalles (id_pedido);
    """,
]

_SNAPSHOT_COLS = ["ID_PEDIDO", "ID_ARTICULO", "CAN_PEDIDO", "CAN_DESPACHO", "saldo", "PEDIDO_ESTADO"]


def hash_archivo(path: str | Path) -> str:
    """MD5 del contenido de un archivo (detecta re-procesos)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class PedidosDB:
    """Acceso con una conexion SQLite por operacion (seguro entre hilos)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB_PATH)
        self._lock = threading.RLock()
        self._log = _log

    # ---------------------------------------------------------------
    # Conexion y esquema
    # ---------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path), timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            pass
        return con

    def schema_version(self) -> int:
        with self._lock:
            con = self._connect()
            try:
                row = con.execute("PRAGMA user_version").fetchone()
                return int(row[0])
            finally:
                con.close()

    def migrate(self) -> None:
        """Aplica las migraciones pendientes en orden."""
        with self._lock:
            con = self._connect()
            try:
                version = int(con.execute("PRAGMA user_version").fetchone()[0])
                for i in range(version, SCHEMA_VERSION):
                    con.executescript(MIGRATIONS[i])
                con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                con.commit()
            except sqlite3.Error as ex:
                con.rollback()
                self._log.error("[db] migracion fallo: %s", ex)
                raise
            finally:
                con.close()

    def ensure_schema(self) -> "PedidosDB":
        """Guerantiza el esquema actual (idempotente)."""
        if self.schema_version() < SCHEMA_VERSION:
            self.migrate()
        return self

    def close(self) -> None:
        """No-op por compatibilidad; cada operacion abre/cierra su conexion."""
        return None

    # ---------------------------------------------------------------
    # importaciones
    # ---------------------------------------------------------------
    def registrar_importacion(
        self,
        filename: str,
        file_hash: str,
        filas: int = 0,
        api_state: str = "offline",
        resultado: str = "ok",
        mensaje: str | None = None,
    ) -> int:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                cur = con.execute(
                    """INSERT INTO importaciones (filename, file_hash, filas, api_state, resultado, mensaje)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (filename, file_hash, filas, api_state, resultado, mensaje),
                )
                con.commit()
                return int(cur.lastrowid)
            finally:
                con.close()

    def ultima_importacion(self, file_hash: str | None = None, filename: str | None = None) -> dict | None:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                if file_hash:
                    row = con.execute(
                        "SELECT * FROM importaciones WHERE file_hash = ? ORDER BY id DESC LIMIT 1",
                        (file_hash,),
                    ).fetchone()
                elif filename:
                    row = con.execute(
                        "SELECT * FROM importaciones WHERE filename = ? ORDER BY id DESC LIMIT 1",
                        (filename,),
                    ).fetchone()
                else:
                    row = con.execute("SELECT * FROM importaciones ORDER BY id DESC LIMIT 1").fetchone()
                return dict(row) if row else None
            finally:
                con.close()

    def listar_importaciones(self, limit: int = 20) -> list[dict]:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT * FROM importaciones ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    # ---------------------------------------------------------------
    # seguimiento (dato manual, no se sobrescribe con cada carga)
    # ---------------------------------------------------------------
    def upsert_seguimiento(
        self,
        tipo: str,
        referencia: str,
        prioridad: int | None = None,
        anclado: bool | None = None,
        observaciones: str | None = None,
        fecha_revision: str | None = None,
    ) -> None:
        if tipo not in ("pedido", "cliente", "articulo"):
            raise ValueError(f"tipo de seguimiento invalido: {tipo}")
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                # TOCTOU minimizado: se lee primero y se actualiza con los campos no-None
                cur = con.execute(
                    "SELECT prioridad, anclado, observaciones, fecha_revision FROM seguimiento WHERE tipo = ? AND referencia = ?",
                    (tipo, referencia),
                )
                row = cur.fetchone()
                if row is None:
                    con.execute(
                        """INSERT INTO seguimiento
                           (tipo, referencia, prioridad, anclado, observaciones, fecha_revision)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (tipo, referencia,
                         prioridad, 1 if anclado else 0,
                         observaciones, fecha_revision),
                    )
                else:
                    prio = prioridad if prioridad is not None else row["prioridad"]
                    anc = 1 if anclado else row["anclado"]
                    obs = observaciones if observaciones is not None else row["observaciones"]
                    rev = fecha_revision if fecha_revision is not None else row["fecha_revision"]
                    con.execute(
                        """UPDATE seguimiento
                           SET prioridad = ?, anclado = ?, observaciones = ?, fecha_revision = ?,
                               actualizado_en = datetime('now')
                           WHERE tipo = ? AND referencia = ?""",
                        (prio, anc, obs, rev, tipo, referencia),
                    )
                con.commit()
            finally:
                con.close()

    def get_seguimiento(self, tipo: str, referencia: str) -> dict | None:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT * FROM seguimiento WHERE tipo = ? AND referencia = ?",
                    (tipo, referencia),
                ).fetchone()
                return dict(row) if row else None
            finally:
                con.close()

    def get_seguimientos(
        self,
        tipo: str | None = None,
        anclados_solo: bool = False,
        priorizados_solo: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                where, args = [], []
                if tipo:
                    where.append("tipo = ?")
                    args.append(tipo)
                if anclados_solo:
                    where.append("anclado = 1")
                if priorizados_solo:
                    where.append("prioridad IS NOT NULL")
                sql = "SELECT * FROM seguimiento"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY prioridad IS NULL, prioridad ASC, actualizado_en DESC LIMIT ?"
                args.append(limit)
                rows = con.execute(sql, args).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def borrar_seguimiento(self, tipo: str, referencia: str) -> None:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM seguimiento WHERE tipo = ? AND referencia = ?", (tipo, referencia))
                con.commit()
            finally:
                con.close()

    # ---------------------------------------------------------------
    # snapshots (captura completa del estado, no solo pendientes)
    # ---------------------------------------------------------------
    def guardar_snapshot(
        self,
        df,
        label: str | None = None,
        archivo: str | None = None,
        ts: str | None = None,
    ) -> int:
        """Guarda un DataFrame como snapshot + detalles. Retorna el id del snapshot.

        Se conservan todas las lineas (incluidas las atendidas) para que el
        historial pueda mostrar pedidos que ya desaparecieron del Excel.
        """
        self.ensure_schema()
        if df is None or len(df) == 0:
            raise ValueError("snapshot vacio: sin filas para persistir")

        if "saldo" not in df.columns and "CAN_PEDIDO" in df.columns:
            df = df.copy()
            df["saldo"] = df["CAN_PEDIDO"].astype(float) - df["CAN_DESPACHO"].astype(float)

        ts = ts or datetime.now().strftime("%Y%m%d_%H%M%S")
        label = label or f"snapshot_{ts}"
        cols = [c for c in _SNAPSHOT_COLS if c in df.columns]

        with self._lock:
            con = self._connect()
            try:
                total_items = int(
                    df["CAN_PEDIDO"].count() if "CAN_PEDIDO" in df.columns else len(df)
                )
                total_saldo = float(
                    pd.to_numeric(df["saldo"], errors="coerce").sum() if "saldo" in df.columns else 0
                )
                cur = con.execute(
                    """INSERT INTO snapshots (label, ts, fecha, total_items, total_saldo, archivo)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (label, ts, ts[:10], total_items, total_saldo, archivo),
                )
                snapshot_id = int(cur.lastrowid)

                rows = [
                    (
                        snapshot_id,
                        str(row.get("ID_PEDIDO", "")),
                        str(row.get("ID_ARTICULO", "")),
                        to_float(row.get("CAN_PEDIDO")),
                        to_float(row.get("CAN_DESPACHO")),
                        to_float(row.get("saldo")),
                        str(row.get("PEDIDO_ESTADO", "")) or None,
                    )
                    for _, row in df.iterrows()
                ]
                con.executemany(
                    """INSERT INTO snapshot_detalles
                       (snapshot_id, id_pedido, id_articulo, can_pedido, can_despacho, saldo, pedido_estado)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                con.commit()
                return snapshot_id
            except sqlite3.Error as ex:
                con.rollback()
                self._log.error("[db] guardar_snapshot fallo: %s", ex)
                raise
            finally:
                con.close()

    def listar_snapshots(self, limit: int = 30) -> list[dict]:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT * FROM snapshots ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def detalles_de_snapshot(self, snapshot_id: int) -> list[dict]:
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT * FROM snapshot_detalles WHERE snapshot_id = ? ORDER BY id_pedido, id_articulo",
                    (snapshot_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def evolucion_pedido(self, id_pedido: str) -> list[dict]:
        """Estado del pedido en cada snapshot (para el historial)."""
        self.ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    """SELECT s.id AS snapshot_id, s.ts, s.label,
                              d.id_pedido, d.id_articulo, d.can_pedido, d.can_despacho, d.saldo, d.pedido_estado
                       FROM snapshot_detalles d
                       JOIN snapshots s ON s.id = d.snapshot_id
                       WHERE d.id_pedido = ?
                       ORDER BY s.ts, d.id_articulo""",
                    (id_pedido,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()


def to_float(val) -> float:
    try:
        if val is None:
            return 0.0
        return float(val)
    except (TypeError, ValueError):
        return 0.0