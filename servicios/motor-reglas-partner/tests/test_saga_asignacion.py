"""Paso de Motor en la saga: red homologada autoritativa."""
from datetime import datetime, timedelta

from motor_reglas import create_app
from motor_reglas.config.db import db
from motor_reglas.modulos.partners.aplicacion.comandos.verificar_asignacion import (
    VerificarAsignacion,
    ejecutar,
)
from motor_reglas.modulos.partners.dominio.entidades import Convenio, Partner, ReglaDePartner
from motor_reglas.modulos.partners.dominio.objetos_valor import (
    AcuerdoDeServicio,
    Categoria,
    CoberturaContratada,
    RedHomologada,
    Tarifa,
    TipoPartner,
    Vigencia,
)
from motor_reglas.modulos.partners.infraestructura.dto import Outbox
from motor_reglas.seedwork.dominio.objetos_valor import Dinero


def construir_partner(categorias=(Categoria.PLOMERIA,), red=()):
    p = Partner(nombre="Aseguradora Andina", tipo=TipoPartner.ASEGURADORA)
    convenio = Convenio(
        numero="CONV-2026-031",
        vigencia=Vigencia(desde=datetime.utcnow() - timedelta(days=1)),
        tarifa=Tarifa(12.5, "COP"),
    )
    p.firmar_convenio(convenio)
    p.definir_regla(ReglaDePartner(
        cobertura=CoberturaContratada(tuple(categorias)),
        acuerdo=AcuerdoDeServicio(120, Dinero(50_000_00, "COP"), ("ANALISTA",)),
        red_homologada=RedHomologada(tuple(red)),
    ), convenio.id)
    return p


def test_evaluar_asignacion_acepta_red_homologada():
    p = construir_partner(red=("prov-001", "prov-002"))
    ok, motivo, version = p.evaluar_asignacion("prov-001")
    assert ok is True
    assert motivo == "ACEPTADA"
    assert version == 1


def test_evaluar_asignacion_rechaza_fuera_de_red():
    p = construir_partner(red=("prov-001",))
    ok, motivo, _ = p.evaluar_asignacion("prov-999")
    assert ok is False
    assert motivo == "PROVEEDOR_FUERA_DE_RED"


def test_evaluar_asignacion_rechaza_partner_inactivo():
    p = construir_partner(red=("prov-001",))
    p.dar_de_baja("baja")
    ok, motivo, _ = p.evaluar_asignacion("prov-001")
    assert ok is False
    assert motivo == "PARTNER_INACTIVO"


def test_verificar_asignacion_encola_aceptacion():
    app = create_app({"TESTING": True})
    with app.app_context():
        cliente = app.test_client()
        r = cliente.post("/partners", json={
            "nombre": "Saga Partner",
            "tipo_partner": "ASEGURADORA",
            "convenio_numero": "CONV-SAGA",
            "vigencia_desde": "2026-01-01T00:00:00Z",
            "regla": {
                "cobertura_contratada": ["PLOMERIA"],
                "sla_minutos": 120,
                "monto_maximo_sin_aprobacion": {"monto": 1000, "moneda": "COP"},
                "red_homologada": ["prov-ok"],
            },
        })
        partner_id = r.get_json()["id"]

        resultado = ejecutar(VerificarAsignacion(
            trabajo_id="t-1",
            asignacion_id="a-1",
            proveedor_id="prov-ok",
            partner_id=partner_id,
            correlation_id="corr-1",
            mensaje_id="msg-1",
        ))
        assert resultado == "ACEPTADA"
        fila = (
            db.session.query(Outbox)
            .filter_by(tipo="AsignacionAceptadaPorReglaPartner")
            .one()
        )
        assert fila.clave == "t-1"
        assert fila.payload["proveedor_id"] == "prov-ok"
        assert fila.publicado is False

        otra = ejecutar(VerificarAsignacion(
            trabajo_id="t-1",
            asignacion_id="a-1",
            proveedor_id="prov-ok",
            partner_id=partner_id,
            correlation_id="corr-1",
            mensaje_id="msg-1",
        ))
        assert otra == "DUPLICADO"
        assert db.session.query(Outbox).filter_by(
            tipo="AsignacionAceptadaPorReglaPartner"
        ).count() == 1


def test_verificar_asignacion_encola_rechazo_fuera_de_red():
    app = create_app({"TESTING": True})
    with app.app_context():
        cliente = app.test_client()
        partner_id = cliente.post("/partners", json={
            "nombre": "Saga Partner 2",
            "tipo_partner": "ASEGURADORA",
            "convenio_numero": "CONV-SAGA-2",
            "vigencia_desde": "2026-01-01T00:00:00Z",
            "regla": {
                "cobertura_contratada": ["PLOMERIA"],
                "sla_minutos": 120,
                "monto_maximo_sin_aprobacion": {"monto": 1000, "moneda": "COP"},
                "red_homologada": ["prov-ok"],
            },
        }).get_json()["id"]

        resultado = ejecutar(VerificarAsignacion(
            trabajo_id="t-2",
            asignacion_id="a-2",
            proveedor_id="prov-ajeno",
            partner_id=partner_id,
            correlation_id="corr-2",
            mensaje_id="msg-2",
        ))
        assert resultado == "RECHAZADA"
        fila = (
            db.session.query(Outbox)
            .filter_by(tipo="AsignacionRechazadaPorReglaPartner")
            .one()
        )
        assert fila.payload["motivo"] == "PROVEEDOR_FUERA_DE_RED"
