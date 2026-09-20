import os

import pytest
from fastapi.testclient import TestClient

os.environ["CONECTAR_A_PULSAR"] = "false"

from bff import config                                   
from bff.infraestructura import publicador as mod_pub    
from bff.infraestructura.operaciones import ACEPTADA, COMPLETADA, RECHAZADA, registro  
from bff.infraestructura.proyeccion import proyeccion     
from bff.main import app                                 


class PublicadorFalso:
    def __init__(self):
        self.publicados = []

    def publicar(self, topico, tipo, payload, correlation_id, clave_particion=None):
        self.publicados.append({
            "topico": topico, "tipo": tipo, "payload": payload,
            "correlation_id": correlation_id, "clave_particion": clave_particion,
        })

    def conectar(self):
        pass

    def cerrar(self):
        pass


@pytest.fixture
def cliente(monkeypatch):
    falso = PublicadorFalso()
    monkeypatch.setattr(mod_pub, "publicador", falso)
    import bff.rutas.comandos as rc
    monkeypatch.setattr(rc, "publicador", falso)
    proyeccion.partners.clear()
    proyeccion.proveedores.clear()
    proyeccion.trabajos.clear()
    proyeccion.asignaciones.clear()
    proyeccion.sagas.clear()
    with TestClient(app) as c:
        c.falso = falso
        yield c




def test_registrar_partner_devuelve_202_y_publica_en_cmd_partners(cliente):
    r = cliente.post("/partners", json={
        "nombre": "Aseguradora Andina", "tipo_partner": "ASEGURADORA",
        "convenio_numero": "CONV-2026-031",
        "vigencia_desde": "2026-01-01T00:00:00Z",
        "regla": {"cobertura_contratada": ["PLOMERIA", "ELECTRICIDAD"],
                  "sla_minutos": 120,
                  "monto_maximo_sin_aprobacion": {"monto": 500000.0, "moneda": "COP"}},
    })
    assert r.status_code == 202
    cuerpo = r.json()
    assert cuerpo["estado"] == "ACEPTADA"
    assert cuerpo["consultar_en"] == f"/operaciones/{cuerpo['correlation_id']}"

    publicado = cliente.falso.publicados[-1]
    assert publicado["topico"] == config.CMD_PARTNERS
    assert publicado["tipo"] == "RegistrarPartner"
    assert publicado["correlation_id"] == cuerpo["correlation_id"]


def test_los_pesos_se_publican_como_centavos(cliente):

    cliente.post("/partners", json={
        "nombre": "X", "tipo_partner": "BANCO", "convenio_numero": "C1",
        "vigencia_desde": "2026-01-01T00:00:00Z",
        "regla": {"cobertura_contratada": ["PLOMERIA"], "sla_minutos": 60,
                  "monto_maximo_sin_aprobacion": {"monto": 500000.0, "moneda": "COP"}},
    })
    payload = cliente.falso.publicados[-1]["payload"]
    assert payload['monto_maximo_sin_aprobacion']['monto'] == 50_000_000


def test_las_fechas_se_publican_como_milisegundos(cliente):
    cliente.post("/partners", json={
        "nombre": "X", "tipo_partner": "BANCO", "convenio_numero": "C1",
        "vigencia_desde": "2026-01-01T00:00:00Z",
        "regla": {"cobertura_contratada": ["PLOMERIA"], "sla_minutos": 60,
                  "monto_maximo_sin_aprobacion": {"monto": 1.0, "moneda": "COP"}},
    })
    payload = cliente.falso.publicados[-1]["payload"]
    assert payload['vigencia_desde'] == 1767225600000
    assert payload['vigencia_hasta'] == 0       


def test_cada_comando_sale_a_su_topico(cliente):
    cliente.post("/trabajos", json={"partner_id": "p1", "categoria": "PLOMERIA",
                                    "ciudad": "BOGOTA"})
    assert cliente.falso.publicados[-1]["topico"] == config.CMD_TRABAJOS

    cliente.post("/proveedores", json={"nombre": "Plomeria Express",
                                       "categorias": ["PLOMERIA"], "ciudades": ["BOGOTA"]})
    assert cliente.falso.publicados[-1]["topico"] == config.CMD_PROVEEDORES


def test_la_clave_de_particion_es_la_del_agregado(cliente):

    cliente.put("/partners/p-42/regla", json={
        "cobertura_contratada": ["PLOMERIA"], "sla_minutos": 30,
        "monto_maximo_sin_aprobacion": {"monto": 1.0, "moneda": "COP"}})
    assert cliente.falso.publicados[-1]["clave_particion"] == "p-42"


def test_no_existe_endpoint_de_asignacion(cliente):

    assert cliente.post("/trabajos/t1/asignacion", json={}).status_code == 404


def test_entrada_invalida_devuelve_422_no_500(cliente):
    r = cliente.post("/trabajos", json={"categoria": "PLOMERIA"})   # falta partner_id
    assert r.status_code == 422




def test_operacion_nace_aceptada_y_se_consulta(cliente):
    corr = cliente.post("/trabajos", json={"partner_id": "p1", "categoria": "PLOMERIA",
                                           "ciudad": "BOGOTA"}).json()["correlation_id"]
    r = cliente.get(f"/operaciones/{corr}")
    assert r.status_code == 200
    assert r.json()["estado"] == ACEPTADA


def test_un_evento_de_exito_completa_la_operacion(cliente):
    corr = cliente.post("/trabajos", json={"partner_id": "p1", "categoria": "PLOMERIA",
                                           "ciudad": "BOGOTA"}).json()["correlation_id"]
    proyeccion.aplicar("TrabajoCreado",
                       {"trabajo_id": "t1", "partner_id": "p1", "sla_minutos": 120}, corr)
    assert cliente.get(f"/operaciones/{corr}").json()["estado"] == COMPLETADA


def test_un_evento_de_rechazo_marca_la_operacion_rechazada(cliente):
    corr = cliente.post("/trabajos", json={"partner_id": "p1", "categoria": "CARPINTERIA",
                                           "ciudad": "BOGOTA"}).json()["correlation_id"]
    proyeccion.aplicar("TrabajoRechazado",
                       {"trabajo_id": "t2", "partner_id": "p1",
                        "motivo": "FUERA_DE_COBERTURA"}, corr)
    cuerpo = cliente.get(f"/operaciones/{corr}").json()
    assert cuerpo["estado"] == RECHAZADA
    assert cuerpo["motivo"] == "FUERA_DE_COBERTURA"


def test_una_operacion_resuelta_no_se_pisa(cliente):
    """Pulsar entrega al menos una vez: el mismo evento puede llegar dos veces."""
    corr = cliente.post("/trabajos", json={"partner_id": "p1", "categoria": "PLOMERIA",
                                           "ciudad": "BOGOTA"}).json()["correlation_id"]
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t1", "partner_id": "p1"}, corr)
    proyeccion.aplicar("TrabajoRechazado",
                       {"trabajo_id": "t1", "motivo": "DUPLICADO"}, corr)
    assert cliente.get(f"/operaciones/{corr}").json()["estado"] == COMPLETADA


def test_operacion_inexistente_devuelve_404(cliente):
    assert cliente.get("/operaciones/no-existe").status_code == 404



def test_la_proyeccion_se_llena_con_eventos_no_con_llamadas(cliente):
    proyeccion.aplicar("ReglaDePartnerActualizada",
                       {"partner_id": "p1", "nombre": "Andina", "version_regla": 1,
                        "sla_minutos": 120, "cobertura_contratada": ["PLOMERIA"]}, "")
    r = cliente.get("/partners/p1")
    assert r.status_code == 200
    assert r.json()["nombre"] == "Andina"


def test_la_ultima_version_de_la_regla_gana(cliente):
    for v, sla in ((1, 120), (2, 45)):
        proyeccion.aplicar("ReglaDePartnerActualizada",
                           {"partner_id": "p1", "version_regla": v, "sla_minutos": sla}, "")
    assert cliente.get("/partners/p1").json()["sla_minutos"] == 45


def test_vista_compuesta_reune_tres_servicios_en_una_respuesta(cliente):
    """La razon de ser del BFF, comprobada."""
    proyeccion.aplicar("ReglaDePartnerActualizada",
                       {"partner_id": "p1", "nombre": "Andina", "version_regla": 1,
                        "sla_minutos": 120, "cobertura_contratada": ["PLOMERIA"]}, "")
    proyeccion.aplicar("EstadoDeHabilitacionCambiado",
                       {"proveedor_id": "prov-1", "nombre": "Plomeria Express",
                        "estado": "HABILITADO"}, "")
    proyeccion.aplicar("TrabajoCreado",
                       {"trabajo_id": "t1", "partner_id": "p1", "sla_minutos": 120}, "")
    proyeccion.aplicar("TrabajoAsignado",
                       {"trabajo_id": "t1", "asignacion_id": "a1",
                        "proveedor_id": "prov-1", "partner_id": "p1"}, "")

    v = cliente.get("/trabajos/t1").json()
    assert v["trabajo"]["estado"] == "ASIGNADO"
    assert v["partner"]["nombre"] == "Andina"          
    assert v["asignacion"]["asignacion_id"] == "a1"   
    assert v["proveedor"]["estado"] == "HABILITADO"   


def test_la_compensacion_de_la_saga_se_refleja_en_la_vista(cliente):
    """El camino infeliz: la asignacion se deshace y el trabajo lo muestra."""
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t1", "partner_id": "p1"}, "")
    proyeccion.aplicar("TrabajoAsignado",
                       {"trabajo_id": "t1", "asignacion_id": "a1",
                        "proveedor_id": "prov-1"}, "")
    proyeccion.aplicar("AsignacionRechazadaPorHabilitacion",
                       {"trabajo_id": "t1", "asignacion_id": "a1", "proveedor_id": "prov-1",
                        "estado_real": "SUSPENDIDO", "motivo": "POLIZA_VENCIDA"}, "")

    v = cliente.get("/trabajos/t1").json()
    assert v["trabajo"]["estado"] == "ASIGNACION_REVERTIDA"
    assert v["trabajo"]["motivo_reversion"] == "POLIZA_VENCIDA"
    assert v["asignacion"]["estado"] == "RECHAZADA"


def test_trabajo_desconocido_devuelve_404(cliente):
    assert cliente.get("/trabajos/no-existe").status_code == 404


def test_health_responde_sin_broker(cliente):

    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"




def test_la_saga_feliz_queda_completada(cliente):
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t9", "partner_id": "p1"},
                       "", "orquestacion-trabajos")
    proyeccion.aplicar("TrabajoAsignado",
                       {"trabajo_id": "t9", "asignacion_id": "a9", "proveedor_id": "pr9"},
                       "", "emparejamiento-asignacion")
    proyeccion.aplicar("AsignacionAceptadaPorReglaPartner",
                       {"trabajo_id": "t9", "asignacion_id": "a9", "proveedor_id": "pr9",
                        "regla_version": 1}, "", "motor-reglas-partner")
    proyeccion.aplicar("AsignacionConfirmadaPorHabilitacion",
                       {"trabajo_id": "t9", "asignacion_id": "a9", "proveedor_id": "pr9",
                        "estado_real": "HABILITADO"}, "", "acreditacion-habilitacion")

    s = cliente.get("/sagas/t9").json()
    assert s["estado"] == "COMPLETADA"
    assert s["total_pasos"] == 4
    assert [p["servicio"] for p in s["pasos"]] == [
        "orquestacion-trabajos", "emparejamiento-asignacion",
        "motor-reglas-partner", "acreditacion-habilitacion",
    ]


def test_la_saga_compensada_queda_marcada(cliente):
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t8", "partner_id": "p1"},
                       "", "orquestacion-trabajos")
    proyeccion.aplicar("TrabajoAsignado",
                       {"trabajo_id": "t8", "asignacion_id": "a8", "proveedor_id": "pr8"},
                       "", "emparejamiento-asignacion")
    proyeccion.aplicar("AsignacionRechazadaPorHabilitacion",
                       {"trabajo_id": "t8", "asignacion_id": "a8", "proveedor_id": "pr8",
                        "estado_real": "SUSPENDIDO", "motivo": "POLIZA_VENCIDA"},
                       "", "acreditacion-habilitacion")

    s = cliente.get("/sagas/t8").json()
    assert s["estado"] == "COMPENSADA"
    assert s["pasos"][-1]["resultado"] == "COMPENSACION"
    v = cliente.get("/trabajos/t8").json()
    assert v["trabajo"]["estado"] == "ASIGNACION_REVERTIDA"
    assert v["trabajo"]["motivo_reversion"] == "POLIZA_VENCIDA"


def test_rechazo_por_regla_de_partner_tambien_compensa(cliente):
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t7", "partner_id": "p1"}, "", "orq")
    proyeccion.aplicar("AsignacionRechazadaPorReglaPartner",
                       {"trabajo_id": "t7", "asignacion_id": "a7", "proveedor_id": "pr7",
                        "partner_id": "p1", "regla_version": 2,
                        "motivo": "FUERA_DE_COBERTURA"}, "", "motor-reglas-partner")
    assert cliente.get("/sagas/t7").json()["estado"] == "COMPENSADA"


def test_saga_de_un_trabajo_desconocido_devuelve_404(cliente):
    assert cliente.get("/sagas/no-existe").status_code == 404


def test_la_vista_compuesta_incluye_la_saga(cliente):
    proyeccion.aplicar("TrabajoCreado", {"trabajo_id": "t6", "partner_id": "p1"}, "", "orq")
    v = cliente.get("/trabajos/t6").json()
    assert v["saga"]["estado"] == "EN_CURSO"




def test_el_sobre_viaja_completo_y_se_puede_releer():
    """Si esto falla, el BFF publica mensajes que nadie puede leer."""
    from bff.esquemas import avro
    sobre = {"id": "i", "time": 1, "ingestion": 2, "specversion": "v1",
             "type": "CrearTrabajo", "datacontenttype": "AVRO",
             "service_name": "bff", "correlation_id": "corr-9",
             "data": avro.completar("CrearTrabajo",
                                    {"partner_id": "p1", "categoria": "PLOMERIA",
                                     "ciudad": "BOGOTA"})}
    vuelta = avro.decodificar(avro.codificar(sobre))
    assert vuelta["type"] == "CrearTrabajo"
    assert vuelta["correlation_id"] == "corr-9"
    assert vuelta["data"]["partner_id"] == "p1"


def test_los_cuatro_eventos_de_saga_se_decodifican():
    """Se agregaron en la entrega 5. El BFF los lee del .avsc, sin copiarlos."""
    from bff.esquemas import avro
    for tipo in ("AsignacionAceptadaPorReglaPartner",
                 "AsignacionRechazadaPorReglaPartner",
                 "AsignacionConfirmadaPorHabilitacion",
                 "AsignacionRechazadaPorHabilitacion"):
        sobre = {"id": "i", "time": 1, "ingestion": 2, "specversion": "v1",
                 "type": tipo, "datacontenttype": "AVRO", "service_name": "x",
                 "correlation_id": "c", "data": avro.completar(tipo, {"trabajo_id": "t1"})}
        assert avro.decodificar(avro.codificar(sobre))["type"] == tipo
