"""Pruebas de la capa de persistencia SQLite acotada (src/core/db.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.db import SCHEMA_VERSION, PedidosDB, hash_archivo


@pytest.fixture
def db(tmp_path) -> PedidosDB:
    """Base de datos aislada para cada test."""
    return PedidosDB(tmp_path / "pedidos.db").ensure_schema()


def test_schema_version_y_migracion_idempotente(db):
    """La base se crea con la version actual y re-migrar no falla ni duplica."""
    assert db.schema_version() == SCHEMA_VERSION
    db.migrate()
    assert db.schema_version() == SCHEMA_VERSION
    # las tablas criticas existen
    con = db._connect()
    try:
        tablas = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        con.close()
    assert {"importaciones", "seguimiento", "snapshots", "snapshot_detalles"} <= tablas


def test_persistencia_entre_instancias(tmp_path):
    """Los datos sobreviven a cerrar y abrir la base."""
    path = tmp_path / "pedidos.db"
    db1 = PedidosDB(path).ensure_schema()
    db1.upsert_seguimiento("pedido", "FC0001", prioridad=1, observaciones="revisar")
    db2 = PedidosDB(path).ensure_schema()
    row = db2.get_seguimiento("pedido", "FC0001")
    assert row is not None
    assert row["prioridad"] == 1
    assert row["observaciones"] == "revisar"


def test_registrar_y_listar_importaciones(db):
    hid = hash_archivo(__file__)
    id1 = db.registrar_importacion("18_09.xls", hid, filas=3151, api_state="online")
    id2 = db.registrar_importacion("19_09.xls", "abc123", filas=3000, resultado="error", mensaje="columna faltante")
    assert id2 > id1
    lista = db.listar_importaciones()
    assert len(lista) == 2
    assert lista[0]["filename"] == "19_09.xls"
    assert lista[0]["resultado"] == "error"
    ult = db.ultima_importacion(file_hash=hid)
    assert ult["filename"] == "18_09.xls"


def test_upsert_seguimiento_actualiza_sin_perder_campos(db):
    db.upsert_seguimiento("pedido", "FC0001", prioridad=1, anclado=True, observaciones="sin obs")
    db.upsert_seguimiento("pedido", "FC0001", observaciones="corregido")  # toca solo obs
    row = db.get_seguimiento("pedido", "FC0001")
    assert row["prioridad"] == 1
    assert row["anclado"] == 1
    assert row["observaciones"] == "corregido"


def test_tipo_invalido_lanza(db):
    with pytest.raises(ValueError):
        db.upsert_seguimiento("linea", "X", prioridad=1)


def test_get_seguimientos_filtros(db):
    db.upsert_seguimiento("pedido", "FC0001", prioridad=1, anclado=True)
    db.upsert_seguimiento("cliente", "C001", anclado=False)
    db.upsert_seguimiento("pedido", "FC0002")
    assert len(db.get_seguimientos()) == 3
    assert len(db.get_seguimientos(tipo="pedido")) == 2
    assert len(db.get_seguimientos(anclados_solo=True)) == 1
    assert [r["referencia"] for r in db.get_seguimientos(priorizados_solo=True)] == ["FC0001"]


def test_borrar_seguimiento(db):
    db.upsert_seguimiento("pedido", "FC0001", prioridad=1)
    db.borrar_seguimiento("pedido", "FC0001")
    assert db.get_seguimiento("pedido", "FC0001") is None


def _df_muestra():
    return pd.DataFrame({
        "ID_PEDIDO": ["FC0001", "FC0001", "FC0002"],
        "ID_ARTICULO": ["A001", "A002", "A003"],
        "CAN_PEDIDO": [100, 50, 30],
        "CAN_DESPACHO": [40, 50, 0],
        "PEDIDO_ESTADO": ["APROBADO", "APROBADO", "INGRESADO"],
    })


def test_guardar_snapshot_calcula_saldo_y_conserva_atendidos(db):
    sid = db.guardar_snapshot(_df_muestra(), label="dia1", archivo="18_09.xls")
    meta = [s for s in db.listar_snapshots() if s["id"] == sid][0]
    assert meta["label"] == "dia1"
    assert meta["total_items"] == 3
    assert meta["total_saldo"] == pytest.approx(90.0)  # saldo: 60 + 0 + 30

    det = db.detalles_de_snapshot(sid)
    assert len(det) == 3
    # la linea 100/50 (atendida) se conserva para el historial
    atendida = [d for d in det if d["id_pedido"] == "FC0001" and d["id_articulo"] == "A002"][0]
    assert atendida["saldo"] == 0.0


def test_evolucion_pedido_entre_snapshots(db):
    d1 = _df_muestra()
    sid1 = db.guardar_snapshot(d1, label="dia1")
    d2 = d1.copy()
    d2.loc[0, "CAN_DESPACHO"] = 70  # FC0001/A001 avanzo de 40 a 70
    sid2 = db.guardar_snapshot(d2, label="dia2")
    assert sid2 > sid1

    evo = db.evolucion_pedido("FC0001")
    lineas_a001 = [(e["label"], e["saldo"]) for e in evo if e["id_articulo"] == "A001"]
    assert ("dia1", 60.0) in lineas_a001
    assert ("dia2", 30.0) in lineas_a001


def test_snapshot_vacio_lanza(db):
    with pytest.raises(ValueError):
        db.guardar_snapshot(pd.DataFrame())


def test_hash_archivo(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hola", encoding="utf-8")
    assert hash_archivo(f) == hash_archivo(str(f))
    assert len(hash_archivo(f)) == 32


def test_registrar_importaciones_desde_ingester(tmp_path):
    """El Ingester traza cada archivo procesado (por nombre + hash + filas)."""
    from src.core.ingest import Ingester

    f1 = tmp_path / "a.xls"
    f2 = tmp_path / "b.xls"
    f1.write_bytes(b"fake-excel-a")
    f2.write_bytes(b"fake-excel-b")
    df = pd.DataFrame({"_fuente": ["a.xls", "a.xls", "b.xls"]})

    ing = Ingester()
    ing.registrar_importaciones([str(f1), str(f2)], df, api_state="online",
                                db_path=tmp_path / "pedidos.db")

    lista = PedidosDB(tmp_path / "pedidos.db").listar_importaciones()
    assert len(lista) == 2
    por_archivo = {r["filename"]: r for r in lista}
    assert por_archivo["a.xls"]["filas"] == 2
    assert por_archivo["b.xls"]["filas"] == 1
    assert por_archivo["a.xls"]["api_state"] == "online"

    # re-procesar el mismo archivo queda detectado por hash
    ing.registrar_importaciones([str(f1)], df, resultado="error", mensaje="boom",
                                db_path=tmp_path / "pedidos.db")
    ult = PedidosDB(tmp_path / "pedidos.db").ultima_importacion(filename="a.xls")
    assert ult["resultado"] == "error"
    assert ult["mensaje"] == "boom"