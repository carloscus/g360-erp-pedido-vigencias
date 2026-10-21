"""Tests de prioridad comercial, tramites y pedido raiz."""

from src.core.prioridad import (
    es_apto_enviar,
    es_complemento,
    etiqueta_prioridad,
    pedido_raiz,
    planilla_requerida,
    prioridad_comercial,
    requiere_tramite,
)


class TestPrioridadComercial:
    def test_orden_declarado_por_el_usuario(self):
        # ANTICIPO -> CANJE -> LETRA -> CONTADO -> FACTURA (+ resto)
        assert prioridad_comercial("ANTICIPO") == 1
        assert prioridad_comercial("CANJE") == 2
        assert prioridad_comercial("LETRA") == 3
        assert prioridad_comercial("CONTADO") == 4
        assert prioridad_comercial("FACTURA") == 5

    def test_orden_estricto(self):
        orden = [
            prioridad_comercial(f) for f in ("ANTICIPO", "CANJE", "LETRA", "CONTADO", "FACTURA")
        ]
        assert orden == sorted(orden)

    def test_todo_lo_demas_cae_en_5(self):
        for fam in ("OTRO", "PLANILLA", "MUESTRA", "", None, "MARKETING"):
            assert prioridad_comercial(fam) == 5

    def test_normaliza_mayusculas_y_espacios(self):
        assert prioridad_comercial(" anticipo ") == 1
        assert prioridad_comercial("canje") == 2

    def test_etiqueta(self):
        assert etiqueta_prioridad(1) == "1-ANTICIPO"
        assert etiqueta_prioridad(5) == "5-FACTURA+OTRAS"


class TestPlanilla:
    def test_anticipo_con_planilla_ingresado_requiere(self):
        assert planilla_requerida("ANTICIPO", "INGRESADO") is True

    def test_anticipo_con_planilla_aprobado_no_requiere(self):
        assert planilla_requerida("ANTICIPO", "APROBADO") is False

    def test_canje_letra_no_requieren_planilla(self):
        # El ERP no trae planilla para CANJE/LETRA: NO es un bloqueo.
        for fam in ("CANJE", "LETRA", "CONTADO", "FACTURA"):
            assert planilla_requerida(fam, "") is False
            assert planilla_requerida(fam, None) is False
            assert planilla_requerida(fam, "INGRESADO") is False

    def test_anticipo_sin_dato_de_planilla_no_bloquea(self):
        assert planilla_requerida("ANTICIPO", "") is False


class TestRequiereTramite:
    def test_aprobado_canje_sin_oc_solo_pide_oc(self):
        assert requiere_tramite("CANJE", "APROBADO", "", None) == "SOLICITAR_OC"
        assert requiere_tramite("CANJE", "APROBADO", "", "4500655324") == ""

    def test_ingresado_pide_aprobar_pedido(self):
        assert requiere_tramite("LETRA", "INGRESADO", "", "123") == "APROBAR_PEDIDO"

    def test_anticipo_planilla_ingresado(self):
        assert requiere_tramite("ANTICIPO", "APROBADO", "INGRESADO", "1") == "APROBAR_PLANILLA"

    def test_anticipo_planilla_aprobado_limpio(self):
        assert requiere_tramite("ANTICIPO", "APROBADO", "APROBADO", "1") == ""

    def test_apto_enviar_ignora_oc(self):
        assert es_apto_enviar("APROBADO", "", "CANJE") is True
        assert es_apto_enviar("APROBADO", "INGRESADO", "ANTICIPO") is False
        assert es_apto_enviar("INGRESADO", "", "CANJE") is False


class TestPedidoRaiz:
    def test_raiz_de_complemento_numerico(self):
        # El caso del usuario: C2185 / 2185A
        assert pedido_raiz("A1308A") == "A1308"
        assert pedido_raiz("A1308") == "A1308"

    def test_codigo_con_letra_inicial_se_conserva(self):
        assert pedido_raiz("CC000135") == "CC000135"

    def test_id_con_espacio_se_conserva(self):
        assert pedido_raiz("SADIE 46") == "SADIE 46"

    def test_es_complemento(self):
        assert es_complemento("A1308A") is True
        assert es_complemento("A1308") is False
        assert es_complemento("46451100") is False

    def test_vacio(self):
        assert pedido_raiz("") == ""
        assert es_complemento("") is False
