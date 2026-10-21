"""Prioridad comercial y requisitos de tramite por pedido.

Regla de negocio CIPSA (definida por el usuario):

  Orden comercial:  ANTICIPO -> CANJE -> LETRA -> CONTADO -> FACTURA (+ resto)

  Un pedido APROBADO ya puede enviarse. Lo que cambia es el TRAMITE que le
  falta ("requiere"):

    ANTICIPO + planilla APROBADO   -> no requiere nada
    ANTICIPO + planilla INGRESADO  -> APROBAR_PLANILLA
    CANJE / LETRA                  -> no requieren planilla (el ERP no la trae)
    PEDIDO INGRESADO (no aprobado) -> APROBAR_PEDIDO
    sin PEDIDO_ORD_COMPRA          -> SOLICITAR_OC  (no bloquea; es un aviso)

Este modulo es puro (sin estado, sin I/O) para poder testearlo directo.
"""

from __future__ import annotations

import re

# Escala comercial: menor numero = mas prioridad.
# Fuente unica: cualquier consumidor (reporte, orden, filtro) usa esto.
PRIORIDAD_COMERCIAL: dict[str, int] = {
    "ANTICIPO": 1,
    "CANJE": 2,
    "LETRA": 3,
    "CONTADO": 4,
    "FACTURA": 5,
}

# Etiqueta legible de cada nivel (para publicar en el libro).
PRIORIDAD_ETIQUETA: dict[int, str] = {
    1: "1-ANTICIPO",
    2: "2-CANJE",
    3: "3-LETRA",
    4: "4-CONTADO",
    5: "5-FACTURA+OTRAS",
}

# Familias que NO requieren planilla de anticipo (el ERP no trae el dato).
FAMILIAS_SIN_PLANILLA = {"CANJE", "LETRA", "CONTADO", "FACTURA", "OTRO", "MUESTRA", "PLANILLA"}


def prioridad_comercial(familia: str | None) -> int:
    """Nivel comercial de la familia de condicion de pago (1 = mas prioritario).

    Todo lo que no sea ANTICIPO/CANJE/LETRA/CONTADO/FACTURA cae en 5
    (FACTURA + todas las demas: OTRO, PLANILLA, MUESTRA, marketing, donacion).
    """
    fam = str(familia or "").strip().upper()
    return PRIORIDAD_COMERCIAL.get(fam, 5)


def etiqueta_prioridad(nivel: int) -> str:
    """Etiqueta legible de un nivel comercial (para publicar en la hoja)."""
    return PRIORIDAD_ETIQUETA.get(int(nivel), "5-FACTURA+OTRAS")


def _norm(val) -> str:
    txt = str(val or "").strip().upper()
    return "" if txt in ("NAN", "NONE", "NAT") else txt


def planilla_requerida(familia: str | None, planilla: str | None) -> bool:
    """True si el pedido esta esperando aprobacion de planilla de anticipo.

    Solo ANTICIPO trae planilla en el ERP. En las demas familias el campo viene
    vacio y NO debe interpretarse como bloqueo (antes se asumia; ahora se
    distingue explicitamente).
    """
    fam = _norm(familia)
    if fam not in {"ANTICIPO", ""}:
        return False
    pl = _norm(planilla)
    if not pl:
        # ANTICIPO sin planilla: no hay dato que condicione la salida.
        return False
    return pl == "INGRESADO"


def requiere_tramite(
    familia: str | None,
    estado_pedido: str | None,
    planilla: str | None = None,
    orden_compra: str | None = None,
) -> str:
    """Tramite que falta para poder enviar el pedido ("" si no falta nada).

    Devuelve uno de:
      ""                 nada (listo para enviar)
      APROBAR_PEDIDO     el pedido esta INGRESADO (no APROBADO)
      APROBAR_PLANILLA   anticipo con planilla INGRESADO
      SOLICITAR_OC       falta la orden de compra (aviso, no bloquea)
    """
    fam = _norm(familia)
    est = _norm(estado_pedido)
    if est and est != "APROBADO":
        return "APROBAR_PEDIDO"
    if planilla_requerida(fam, planilla):
        return "APROBAR_PLANILLA"
    if not _norm(orden_compra):
        return "SOLICITAR_OC"
    return ""


def es_apto_enviar(
    estado_pedido: str | None, planilla: str | None, familia: str | None = None
) -> bool:
    """True si el pedido no tiene tramite bloqueante (OC no bloquea)."""
    req = requiere_tramite(familia, estado_pedido, planilla, orden_compra="X")
    return req == ""


# ---------------------------------------------------------------------------
# Pedido raiz / complemento (C2185 vs 2185A, A1308 vs A1308A)
# ---------------------------------------------------------------------------
_SUFIJO_RE = re.compile(r"^(?P<raiz>.*?)(?P<sufijo>[A-Z])$")


def pedido_raiz(pedido_id) -> str:
    """Raiz del pedido: 'A1308A' -> 'A1308', 'CC000135' -> 'CC000135'.

    Solo se recorta un sufijo alfabetico final cuando la raiz conserva al menos
    un digito (asi 'SADIE 46' queda intacto y 'CC000135' no pierde la C inicial).
    """
    txt = str(pedido_id or "").strip().upper()
    if not txt:
        return ""
    m = _SUFIJO_RE.match(txt)
    if not m:
        return txt
    raiz = m.group("raiz")
    if any(ch.isdigit() for ch in raiz) and any(ch.isdigit() for ch in txt):
        return raiz
    return txt


def es_complemento(pedido_id) -> bool:
    """True si el pedido es un complemento (lleva sufijo alfabetico final)."""
    txt = str(pedido_id or "").strip().upper()
    return bool(txt) and pedido_raiz(txt) != txt
