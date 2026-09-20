"""Fase 1: el mensaje va y vuelve.

Estas pruebas NO levantan Pulsar ni PostgreSQL. La costura es traduccion pura, y
poder probarla sin infraestructura es justamente la razon de que sea un modulo
aparte y de que use fastavro en vez del cliente nativo del broker.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from orquestacion.mensajeria import contratos as c


TODOS = [
    c.CrearTrabajo(partner_id="SEGUROS_ANDES", mercado_id="BOG", categoria="PLOMERIA",
                   urgencia="ALTA", zona="BOGOTA", descripcion="Fuga en cocina",
                   monto_estimado=350000, moneda="COP"),
    c.ReglaDePartnerActualizada(partner_id="SEGUROS_ANDES", regla_version=7, sla_minutos=120,
                                categorias_cubiertas=["PLOMERIA", "ELECTRICIDAD"],
                                monto_max=Decimal("500000"), moneda="COP", activo=True),
    c.TrabajoAsignado(trabajo_id="11111111-1111-1111-1111-111111111111",
                      asignacion_id="a-1", proveedor_id="PROV_9", partner_id="SEGUROS_ANDES",
                      vence_en=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
                      origen_habilitacion="CACHE"),
    c.AsignacionRechazadaPorHabilitacion(trabajo_id="11111111-1111-1111-1111-111111111111",
                                         asignacion_id="a-1", proveedor_id="PROV_9",
                                         estado_real="SUSPENDIDO", motivo="SIN_HABILITACION",
                                         # Explicito: a_datos() rellena este campo con "ahora"
                                         # cuando viene vacio, asi que sin fijarlo la ida y
                                         # vuelta no seria simetrica. Es intencional: solo
                                         # RECIBIMOS este mensaje, y a_datos() existe para que
                                         # scripts/publicar.py pueda simularlo.
                                         verificado_en=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)),
    c.AsignacionConfirmadaPorHabilitacion(trabajo_id="11111111-1111-1111-1111-111111111111",
                                          asignacion_id="a-1", proveedor_id="PROV_9",
                                          estado_real="HABILITADO",
                                          verificado_en=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)),
    c.AsignacionAceptadaPorReglaPartner(trabajo_id="11111111-1111-1111-1111-111111111111",
                                       asignacion_id="a-1", proveedor_id="PROV_9",
                                       partner_id="SEGUROS_ANDES", regla_version=7,
                                       verificado_en=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)),
    c.AsignacionRechazadaPorReglaPartner(trabajo_id="11111111-1111-1111-1111-111111111111",
                                        asignacion_id="a-1", proveedor_id="PROV_9",
                                        partner_id="SEGUROS_ANDES", regla_version=7,
                                        motivo="PROVEEDOR_FUERA_DE_RED",
                                        verificado_en=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)),
    c.TrabajoCreado(trabajo_id="11111111-1111-1111-1111-111111111111",
                    partner_id="SEGUROS_ANDES", mercado_id="BOG", categoria="PLOMERIA",
                    urgencia="ALTA", zona="BOGOTA", sla_minutos=120, requiere_aprobacion=False),
    c.TrabajoRechazado(trabajo_id="11111111-1111-1111-1111-111111111111",
                       partner_id="SEGUROS_ANDES", categoria="CERRAJERIA",
                       motivo="CATEGORIA_NO_CUBIERTA", detalle="La regla v7 no cubre CERRAJERIA"),
    c.AsignarProveedor(trabajo_id="11111111-1111-1111-1111-111111111111",
                       motivo="REINTENTO_POR_HABILITACION",
                       proveedores_excluidos=["PROV_9"], intento=2),
]


@pytest.mark.parametrize("mensaje", TODOS, ids=lambda m: m.TIPO)
def test_ida_y_vuelta_avro(mensaje):
    """Codificar a Avro y decodificar devuelve el MISMO mensaje de dominio.

    Es la prueba de que la traduccion de nombres es simetrica: si a_datos() y
    desde_datos() no fueran inversas, aqui se veria.
    """
    sobre = c.empaquetar(mensaje, correlation_id="22222222-2222-2222-2222-222222222222")
    crudo = sobre.a_bytes()

    devuelto = c.decodificar(crudo)
    assert devuelto is not None
    assert devuelto.type == mensaje.TIPO
    assert devuelto.correlation_id == "22222222-2222-2222-2222-222222222222"
    assert devuelto.contenido() == mensaje


def test_el_sobre_se_lee_sin_saber_el_tipo():
    """El discriminador viaja en el mensaje: `decodificar` no recibe pistas.

    Es lo que hace viable publicar evt.trabajos con BytesSchema pese a llevar
    tres tipos distintos por el mismo topico.
    """
    tres_tipos_un_topico = [m for m in TODOS if m.TOPICO == c.TOPICO_EVT_TRABAJOS]
    assert len(tres_tipos_un_topico) == 3

    for mensaje in tres_tipos_un_topico:
        sobre = c.decodificar(c.empaquetar(mensaje).a_bytes())
        assert sobre.type == mensaje.TIPO


def test_traduccion_de_nombres_hacia_afuera():
    """El vocabulario de adentro NO aparece en el cable, y viceversa."""
    datos = c.TrabajoCreado(trabajo_id="t", zona="BOGOTA").a_datos()
    assert datos["ciudad"] == "BOGOTA"
    assert "zona" not in datos

    datos = c.AsignarProveedor(trabajo_id="t", proveedores_excluidos=["P1"]).a_datos()
    assert datos["excluir_proveedores"] == ["P1"]
    assert "proveedores_excluidos" not in datos

    datos = c.ReglaDePartnerActualizada(partner_id="p", regla_version=3,
                                        categorias_cubiertas=["PLOMERIA"],
                                        monto_max=Decimal("500000"), moneda="COP").a_datos()
    assert datos["version_regla"] == 3
    assert datos["cobertura_contratada"] == ["PLOMERIA"]
    assert datos["monto_maximo_sin_aprobacion"] == {"monto": 500000, "moneda": "COP"}
    assert "regla_version" not in datos and "categorias_cubiertas" not in datos


def test_traduccion_de_nombres_hacia_adentro():
    entrante = c.CrearTrabajo.desde_datos({"ciudad": "MEDELLIN", "categoria": "PLOMERIA"})
    assert entrante.zona == "MEDELLIN"

    regla = c.ReglaDePartnerActualizada.desde_datos({
        "partner_id": "p", "version_regla": 9, "cobertura_contratada": ["ELECTRICIDAD"],
        "sla_minutos": 60, "monto_maximo_sin_aprobacion": {"monto": 1000, "moneda": "COP"},
    })
    assert (regla.regla_version, regla.sla_minutos) == (9, 60)
    assert regla.categorias_cubiertas == ["ELECTRICIDAD"]
    assert regla.monto_max == Decimal(1000)


def test_el_tiempo_viaja_como_long_de_milisegundos():
    """El contrato usa long de ms desde epoch, no ISO-8601."""
    vence = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    datos = c.TrabajoAsignado(trabajo_id="t", vence_en=vence).a_datos()
    assert isinstance(datos["sla_vence_en"], int)
    assert datos["sla_vence_en"] == int(vence.timestamp() * 1000)
    assert c.TrabajoAsignado.desde_datos(datos).vence_en == vence


def test_un_sobre_propio_se_reconoce_como_eco():
    """Mitigacion del ciclo de evt.trabajos: hay que poder distinguir nuestro
    propio eco del evento real de Emparejamiento."""
    propio = c.decodificar(c.empaquetar(c.TrabajoCreado(trabajo_id="t")).a_bytes())
    assert propio.es_propio() is True

    ajeno = c.decodificar(
        c.empaquetar(c.TrabajoAsignado(trabajo_id="t"),
                     service_name="emparejamiento-asignacion").a_bytes()
    )
    assert ajeno.es_propio() is False


def test_tipo_desconocido_se_ignora_en_silencio():
    """Los topicos son por agregado, no por tipo: recibir mensajes ajenos es
    normal y no debe reventar el consumidor."""
    assert c.decodificar(b"\x00\x01basura") is None


def test_se_acepta_json_legado_pero_nunca_se_emite():
    """LIBERAL al recibir, ESTRICTO al emitir.

    cmd.trabajos tiene retencion infinita y conserva CrearTrabajo en JSON de
    antes de que el grupo publicara el .avsc. Un consumidor que lea desde el
    inicio los va a encontrar, y dejarlos caer en silencio seria perder
    comandos reales.
    """
    legado = json.dumps({
        "id": "33333333-3333-3333-3333-333333333333",
        "time": 1789393925307, "ingestion": 1789393925307,
        "specversion": "v1", "type": "CrearTrabajo", "datacontenttype": "JSON",
        "service_name": "simulado:aseguradora",
        "correlation_id": "44444444-4444-4444-4444-444444444444",
        "data": {"trabajo_id": "f5c55831-6121-4053-af69-7faf2d6b0372",
                 "partner_id": "SEGUROS_BETA", "categoria": "PLOMERIA",
                 "zona": "BOG-CHAPINERO", "descripcion": "Fuga"},
    }).encode("utf-8")

    sobre = c.decodificar(legado)
    assert sobre is not None
    assert sobre.type == "CrearTrabajo"
    # `zona` del JSON legado se lee igual que `ciudad` del contrato Avro
    assert sobre.contenido().zona == "BOG-CHAPINERO"

    # Pero lo que ESTE servicio emite siempre es Avro: nunca empieza por '{'
    assert c.empaquetar(c.CrearTrabajo(partner_id="p")).a_bytes()[:1] != b"{"
