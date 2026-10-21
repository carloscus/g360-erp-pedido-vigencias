"""
Configuracion de la aplicacion g360-erp-pedido-vigencias.

Contiene constantes para la conexion con la API G360 Stock (Render), tiempos de
cache, categorias de negocio, almacenes prioritarios y el umbral de alerta QC.
Los valores pueden sobreescribirse con variables de entorno G360_*.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Directorio base del proyecto (dos niveles arriba de src/config)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# API G360 Stock (Render)
S1_API_URL = os.environ.get("G360_S1_API_URL", "https://g360-stock-api.onrender.com/api/v1")
S1_API_KEY = os.environ.get("G360_S1_API_KEY", "cipsa2026")

# Tiempos y cache (TTL en segundos: 15 minutos)
CACHE_TTL = int(os.environ.get("G360_CACHE_TTL", "900"))
API_TIMEOUT = int(os.environ.get("G360_API_TIMEOUT", "10"))

# Categorias de negocio principales
PRIMARY_CATEGORIES = ["VINIBALL", "VINIFAN", "REPRESENTADAS"]

# Almacenes prioritarios para monitoreo
# VES = Centro Logistico Principal, 121 = QC (espera liberacion)
ALMACENES_PRIORIDAD = ["VES", "121", "40", "129"]

# Umbral de alerta QC: SKUs con saldo > este valor (units) en VES generan alerta
ALERTA_QC_THRESHOLD = int(os.environ.get("G360_ALERTA_QC_THRESHOLD", "5000"))

# Lineas de producto validas (fase 1, prototipo Vigencias).
# Match por SUFIJO de 2 chars: 0101 -> 01, 01MA -> MA.
# Fuente: taxonomia DB (id_linea) / catalogo (linea), fallback a grupo.
LINEAS_VALIDAS_DEFAULT: list[str] = [
    "01",
    "02",
    "09",
    "11",
    "14",
    "72",
    "73",
    "75",
    "76",
    "77",
    "78",
    "79",
    "81",
    "85",
    "99",
    "AD",
    "CA",
    "CB",
    "CC",
    "CD",
    "CE",
    "CF",
    "CG",
    "MA",
]

# Semilla estatica nombre de linea -> codigo corto (2 chars), derivada del
# reporte de stock del API ("0178 - ARCHIVO" -> "78", "01MA - MASCOTAS" -> "MA").
# El runtime la completa con los pares "CODIGO - NOMBRE" del propio archivo
# y el `linea_codigo` del catalogo v3.2.0 (ver _nombre_a_codigo).
# Permite rescatar lineas que llegan como nombre puro ("PELOTAS") sin codigo.
LINEA_NOMBRE_A_CODIGO: dict[str, str] = {
    "PELOTAS": "01",
    "FORROS": "02",
    "SENSORIALES": "09",
    "METALICA": "11",
    "OTROS": "14",
    "PEGAMENTOS": "72",
    "DIDACTICOS": "73",
    "DIBUJO": "75",
    "ESCRITURA": "76",
    "PINTURA": "77",
    "ARCHIVO": "78",
    "ACCESORIOS": "79",
    "PUBLICIDAD": "80",
    "KITS": "81",
    "REPRESENTADAS": "85",
    "MASCOTAS": "MA",
    "MANUALIDADES": "CE",
    "SET": "CF",
    "ACCESORIOS DEPORTIVOS": "AD",
    "PRODUCTOS INDUSTRIALES": "20",
    "REPRESENTACIONES INDUSTRIALES": "21",
    "SEGURIDAD Y SEÑALIZACION VIAL": "23",
    "CIPTECH ETIQUETAS": "30",
    "CIPTECH CINTAS": "31",
    "CIPTECH CPEI": "32",
    "CIPTECH CIL": "33",
    "CIPTECH SUPPLY CHAIN": "35",
    "MATERIA PRIMA": "40",
    "MATERIALES AUXILIARES": "50",
    "INDUMENTARIA Y EPP": "57",
    "SCRAP": "60",
    "MERCADERIAS VARIAS": "65",
    "ECONOMATO": "66",
    "PRODUCTOS EN PROCESO": "70",
    "PRODUCTOS SIN EMBALAJE": "98",
}

# Nombres de linea que en el ERP designan a MAS DE UNA linea (codigo distinto).
# Un nombre ambiguo NO puede resolver un codigo por si solo: atribuiria el SKU
# a la linea equivocada. Caso real: "ACCESORIOS" es la linea 79 (tijeras,
# limpiatipo) y TAMBIEN la CD (pinceles Crayola); resolver por nombre metia los
# SKUs de una en la otra de forma no determinista (ver TESTS
# test_linea_codigo_vs_nombre). El CODIGO explicito siempre manda; un nombre
# ambiguo se resuelve solo con su codigo ("0179"/"01CD").
LINEA_NOMBRES_AMBIGUOS: set[str] = {"ACCESORIOS"}

# Estados de linea validos (guia ERP SKU_BX.xlsx -> columna ESTADO_LINEA).
# Es lo que el ERP usa para clasificar el origen del producto. Cualquier otro
# valor que llegue (p.ej. el GRUPO del producto) es contamination: el grupo
# tiene su propia columna.
ESTADOS_LINEA_VALIDOS: list[str] = ["NUEVO", "IMPORTADO", "TRADICIONAL", "NACIONAL"]

# Condicion de pago del prototipo (filtro exacto fase 1)
CONDICION_PROTOTIPO = "ANTICIPO EN LETRAS"

# Estado de pedido despachable para Val Atencion (fase 1)
ESTADO_DESPACHABLE = "APROBADO"

# Monto minimo (S/) por pedido para ir a ENTREGA_AHORA (resto a OBSERVACION)
UMBRAL_MINIMO_ENVIO = float(os.environ.get("G360_UMBRAL_MINIMO_ENVIO", "1200"))

# Dias sin aprobar planilla para escalar a cobranza (proxy PEDIDO_FECHA)
UMBRAL_PLANILLA_DIAS = int(os.environ.get("G360_UMBRAL_PLANILLA_DIAS", "10"))

# Familias de condicion de pago (orden de fases del reporte de acciones)
FAMILIAS_REPORTE = ["ANTICIPO", "CONTADO", "CANJE", "LETRA", "FACTURA"]

# Rutas locales
DATA_DIR = BASE_DIR / ".cache"
LOG_PATH = BASE_DIR / "run_log.txt"
CATALOGO_RUTA = BASE_DIR.parent / "g360-master-data" / "output" / "catalogo_productos.json"

# Version de la aplicacion (mostrada en la firma G360)
APP_VERSION = os.environ.get("G360_APP_VERSION", "1.0.0")

# Ventana de la aplicacion
WINDOW_WIDTH = 1350
WINDOW_HEIGHT = 900
WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 640

# ---------------------------------------------------------------------------
# Configuracion persistente del usuario (.cache/config.json)
# ---------------------------------------------------------------------------
_USER_CONFIG_FILE = DATA_DIR / "config.json"

# Claves de reglas de alerta (deben coincidir con src/core/alerts.py)
ALERT_TOGGLES_DEFAULTS: dict[str, bool] = {
    "vencidos_sin_stock": True,
    "por_vencer": True,
    "100_atendible": True,
    "bloqueados_sin_stock": True,
    "sin_catalogo": True,
    "api_offline": True,
}


class UserConfig:
    """Configuracion del usuario guardada en .cache/config.json.

    Carga defaults, tolera archivos incompletos/corruptos y sobreescribe
    solo las claves presentes (los dicts anidados se fusionan).
    """

    DEFAULTS: dict = {
        "umbral_por_vencer_pct": 75.0,
        "alerta_toggles": dict(ALERT_TOGGLES_DEFAULTS),
        "snapshot_auto": True,
        "snapshot_keep": 30,
        "api_url": S1_API_URL,
        "api_key": S1_API_KEY,
        "lineas_validas": list(LINEAS_VALIDAS_DEFAULT),
        "condicion_prototipo": CONDICION_PROTOTIPO,
        "solo_despachables": True,
        "umbral_minimo_envio": UMBRAL_MINIMO_ENVIO,
        "umbral_planilla_dias": UMBRAL_PLANILLA_DIAS,
    }

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or _USER_CONFIG_FILE)
        self.data: dict = {}
        self.reset()

    def reset(self) -> "UserConfig":
        """Vuelve a los valores por defecto (sin tocar el archivo)."""
        self.data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.DEFAULTS.items()}
        return self

    def load(self) -> "UserConfig":
        try:
            with open(self.path, encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return self
            for key, value in payload.items():
                if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                    self.data[key].update(value)
                else:
                    self.data[key] = value
        except (OSError, ValueError, TypeError):
            pass
        return self

    def save(self) -> "UserConfig":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        return self

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> "UserConfig":
        self.data[key] = value
        return self

    def alert_enabled(self, key: str) -> bool:
        toggles = self.data.get("alerta_toggles", {})
        return bool(toggles.get(key, ALERT_TOGGLES_DEFAULTS.get(key, True)))
