"""Pruebas del motor de alertas y la configuracion de usuario."""

from __future__ import annotations

import pandas as pd

from src.config.settings import UserConfig
from src.core.alerts import ALERTS, compute_alerts


def _df():
    return pd.DataFrame({
        "ID_PEDIDO": ["FC1", "FC1", "FC2", "FC3", "FC4"],
        "SKU": ["A", "B", "C", "D", "E"],
        "NRO_DOCUMENTO": ["OC1", "OC1", "OC2", "OC3", "OC4"],
        "categoria": ["VINIFAN", "VINIFAN", "VINIBALL", "", "VINIFAN"],
        "cond_familia": ["ANTICIPO"] * 5,
        "saldo": [100, 5, 0, 50, 80],
        "stock_real": [200, 0, 90, 0, 0],
        "vigencia": [30] * 5,
        "por_vigencia_consumida": [40.0, 120.0, 95.0, 10.0, 90.0],
        "estado_vigencia": ["VIGENTE", "VENCIDO", "COMPLETADO", "VIGENTE", "POR VENCER"],
        "valor_saldo": [100.0, 5.0, 0.0, 50.0, 80.0],
    })


def _by_key(alerts: list[dict]) -> dict[str, dict]:
    return {a["key"]: a for a in alerts}


def test_alerts_reglas_principales():
    """Cada regla detecta las lineas esperadas en el fixture."""
    alerts = _by_key(compute_alerts(_df(), umbral_por_vencer_pct=75.0, api_state="online"))

    venc = alerts["vencidos_sin_stock"]
    assert venc["count_pedidos"] == 1
    assert venc["lineas"] == 1
    assert venc["unidades"] == 5.0

    porv = alerts["por_vencer"]
    assert porv["count_pedidos"] == 1
    assert porv["lineas"] == 1
    assert porv["valor"] == 80.0

    atend = alerts["100_atendible"]
    assert atend["count_pedidos"] == 1
    assert atend["unidades"] == 100.0

    blocked = alerts["bloqueados_sin_stock"]
    assert blocked["lineas"] == 3
    assert blocked["count_pedidos"] == 3

    sincat = alerts["sin_catalogo"]
    assert sincat["lineas"] == 1
    assert sincat["count_pedidos"] == 1


def test_alerts_umbral_y_toggles():
    """El umbral de 'por vencer' es configurable y los toggles apagan reglas."""
    alerts = compute_alerts(
        _df(),
        umbral_por_vencer_pct=95.0,
        toggles={"100_atendible": False},
        api_state="online",
    )
    keys = [a["key"] for a in alerts]
    assert "100_atendible" not in keys
    assert "por_vencer" not in keys  # el unico candidato tenia 90% (< 95)
    assert "vencidos_sin_stock" in keys


def test_alerts_api_offline_solo_cuando_offline():
    """La alerta api_offline aparece solo con api_state=offline."""
    offline = [a["key"] for a in compute_alerts(_df(), api_state="offline")]
    online = [a["key"] for a in compute_alerts(_df(), api_state="online")]
    assert "api_offline" in offline
    assert "api_offline" not in online


def test_alerts_vacio_sin_datos():
    assert compute_alerts(None) == []
    assert compute_alerts(pd.DataFrame()) == []


def test_alerts_registry_coherente():
    """Todas las reglas definidas tienen sus claves de config default."""
    for rule in ALERTS:
        assert {"key", "title", "severity", "default"} <= set(rule)
        assert bool(rule["default"]) is True


def test_user_config_roundtrip(tmp_path):
    """UserConfig persiste, fusiona defaults y tolera archivos incompletos."""
    path = tmp_path / "config.json"
    cfg = UserConfig(path)
    cfg.set("umbral_por_vencer_pct", 90.0)
    cfg.set("alerta_toggles", {"vencidos_sin_stock": False})
    cfg.save()

    cfg2 = UserConfig(path).load()
    assert cfg2.get("umbral_por_vencer_pct") == 90.0
    assert cfg2.alert_enabled("vencidos_sin_stock") is False
    # Las claves no escritas conservan su default
    assert cfg2.alert_enabled("por_vencer") is True
    assert cfg2.get("snapshot_keep") == 30


def test_user_config_archivo_corrupto(tmp_path):
    """Un archivo corrupto no rompe la carga (queda con defaults)."""
    path = tmp_path / "config.json"
    path.write_text("{no-es-json", encoding="utf-8")
    cfg = UserConfig(path).load()
    assert cfg.get("umbral_por_vencer_pct") == 75.0
    assert cfg.alert_enabled("100_atendible") is True


def test_user_config_reset(tmp_path):
    """reset() vuelve a defaults sin tocar el archivo."""
    cfg = UserConfig(tmp_path / "config.json")
    cfg.set("snapshot_keep", 5)
    cfg.reset()
    assert cfg.get("snapshot_keep") == 30