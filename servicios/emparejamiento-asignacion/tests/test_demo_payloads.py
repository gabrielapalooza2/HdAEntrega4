from infraestructura.http.demo import PARTNER_ID, payload_regla, payload_trabajo_creado, payloads_habilitacion


def test_regla_es_evento_de_carga_de_estado():
    rec = payload_regla("corr-1")
    assert rec["type"] == "ReglaDePartnerActualizada"
    assert rec["service_name"] == "motor-reglas-partner"
    assert rec["data"]["partner_id"] == PARTNER_ID
    assert rec["data"]["red_homologada"] == ["prov-b", "prov-a"]


def test_trabajo_creado_simula_orquestacion():
    rec = payload_trabajo_creado("t-1", PARTNER_ID, "corr-1")
    assert rec["type"] == "TrabajoCreado"
    assert rec["service_name"] == "orquestacion-trabajos"
    assert rec["data"]["categoria"] == "PLOMERIA"
    assert rec["data"]["ciudad"] == "Bogota"


def test_habilitaciones_incluyen_prov_a():
    habs = dict(payloads_habilitacion("corr-1"))
    assert habs["prov-a"]["data"]["estado"] == "HABILITADO"
    assert habs["prov-c"]["data"]["estado"] == "SUSPENDIDO"
