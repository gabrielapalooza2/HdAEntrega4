"""Prueba de la aplicación completa contra SQLite en memoria (sin Pulsar).

Verifica el camino comando -> agregación -> repositorio -> outbox -> consulta.
El outbox se comprueba leyendo la tabla: el evento tiene que existir en la misma
transacción, aunque el broker no esté levantado.
"""
import pytest

from motor_reglas import create_app
from motor_reglas.config.db import db


@pytest.fixture
def app():
    app = create_app({"TESTING": True})
    yield app


def test_registrar_partner_y_consultarlo(app):
    cliente = app.test_client()
    r = cliente.post("/partners", json={
        "nombre": "Aseguradora Andina",
        "tipo_partner": "ASEGURADORA",
        "convenio_numero": "CONV-2026-031",
        "vigencia_desde": "2026-01-01T00:00:00Z",
        "porcentaje_comision": 12.5,
        "regla": {
            "cobertura_contratada": ["PLOMERIA", "ELECTRICIDAD"],
            "sla_minutos": 120,
            "monto_maximo_sin_aprobacion": {"monto": 50000000, "moneda": "COP"},
            "pasos_de_aprobacion": ["ANALISTA_SINIESTROS"],
            "red_homologada": ["prov-001", "prov-002"],
        },
    })
    assert r.status_code == 202
    partner_id = r.get_json()["id"]

    detalle = cliente.get(f"/partners/{partner_id}").get_json()
    assert detalle["regla"]["sla_minutos"] == 120
    assert detalle["regla"]["version"] == 1
    assert detalle["regla"]["red_homologada"] == ["prov-001", "prov-002"]

    # el evento quedó en el outbox dentro de la MISMA transacción
    with app.app_context():
        from motor_reglas.modulos.partners.infraestructura.dto import Outbox
        filas = db.session.query(Outbox).all()
        assert len(filas) == 1
        assert filas[0].tipo == "ReglaDePartnerActualizada"
        assert filas[0].clave == partner_id          # clave de partición y compactación
        assert filas[0].publicado is False           # el relay aún no lo publicó
        assert filas[0].payload["sla_minutos"] == 120
        assert filas[0].payload["activo"] is True


def test_actualizar_regla_sube_version_y_encola_otro_evento(app):
    cliente = app.test_client()
    partner_id = cliente.post("/partners", json={
        "nombre": "Banco del Sur", "tipo_partner": "BANCO",
        "convenio_numero": "CONV-2026-040", "vigencia_desde": "2026-01-01T00:00:00Z",
        "regla": {"cobertura_contratada": ["PLOMERIA"], "sla_minutos": 60,
                  "monto_maximo_sin_aprobacion": {"monto": 1000, "moneda": "COP"}},
    }).get_json()["id"]

    r = cliente.put(f"/partners/{partner_id}/regla", json={
        "cobertura_contratada": ["PLOMERIA", "PINTURA"], "sla_minutos": 45,
        "monto_maximo_sin_aprobacion": {"monto": 2000, "moneda": "COP"},
        "red_homologada": ["prov-007"],
    })
    assert r.status_code == 202
    assert r.get_json()["version_regla"] == 2

    with app.app_context():
        from motor_reglas.modulos.partners.infraestructura.dto import Outbox
        assert db.session.query(Outbox).count() == 2


def test_health(app):
    assert app.test_client().get("/health").status_code == 200
