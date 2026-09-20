"""El dominio, probado SIN infraestructura.

Ni base de datos, ni broker, ni Flask. Que estas pruebas corran en una maquina
pelada es la evidencia de que la arquitectura hexagonal se sostiene: si para
probar una regla de negocio hiciera falta un broker, la capa se habria roto.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from orquestacion.dominio import eventos as ev
from orquestacion.dominio import trabajo as dom
from orquestacion.dominio.objetos_valor import EstadoTrabajo, MotivoRechazo
from orquestacion.dominio.regla_partner import ReglaDePartner

AHORA = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
TRABAJO = "11111111-1111-1111-1111-111111111111"


def regla(**cambios):
    base = dict(partner_id="SEGUROS_ANDES", regla_version=7, activo=True,
                sla_minutos=120, categorias_cubiertas=("PLOMERIA", "ELECTRICIDAD"),
                monto_max=Decimal("500000"), moneda="COP")
    base.update(cambios)
    return ReglaDePartner(**base)


def crear(**cambios):
    args = dict(partner_id="SEGUROS_ANDES", categoria="PLOMERIA", zona="BOGOTA",
                regla=regla(), ahora=AHORA)
    args.update(cambios)
    return dom.decidir_creacion(TRABAJO, **args)


# ══════════════════════════════════════════════ ESCENARIO: congelamiento ═══

def test_el_sla_se_congela_en_el_evento():
    """El corazon del escenario de MODIFICABILIDAD.

    sla_minutos, regla_version y vence_en se copian de la regla vigente y quedan
    escritos en el evento. Como el event store es append-only, cambiar la regla
    manana no los puede mover.
    """
    evento = crear()
    assert isinstance(evento, ev.TrabajoCreado)
    assert evento.sla_minutos == 120
    assert evento.regla_version == 7
    assert evento.vence_en == AHORA + timedelta(minutes=120)


def test_cambiar_la_regla_no_altera_un_trabajo_ya_creado():
    """LA PRUEBA DEL ESCENARIO.

    Se crea un trabajo con la regla v7 (SLA 120). El partner publica la v12 con
    SLA 15. El trabajo viejo sigue con 120 y con v7, porque su evento ya ocurrio
    y los eventos no se editan.
    """
    evento_viejo = crear()
    trabajo = dom.Trabajo.reconstruir(TRABAJO, [(1, evento_viejo)])

    # el partner cambia su regla drasticamente
    nueva = regla(regla_version=12, sla_minutos=15, categorias_cubiertas=("ASEO",))

    # un trabajo NUEVO usa la regla nueva...
    evento_nuevo = crear(regla=nueva, categoria="ASEO")
    assert evento_nuevo.sla_minutos == 15
    assert evento_nuevo.regla_version == 12

    # ...pero el VIEJO sigue igual. Nada lo toco.
    assert trabajo.sla_minutos == 120
    assert trabajo.regla_version == 7
    assert trabajo.vence_en == AHORA + timedelta(minutes=120)


# ═════════════════════════════════════════════════ ESCENARIO: rechazos ═════

def test_rechazo_por_categoria_no_cubierta():
    evento = crear(categoria="CERRAJERIA")
    assert isinstance(evento, ev.TrabajoRechazado)
    assert evento.motivo == MotivoRechazo.CATEGORIA_NO_CUBIERTA.value
    assert "CERRAJERIA" in evento.detalle
    assert "v7" in evento.detalle


def test_rechazo_por_partner_desconocido():
    evento = crear(regla=None)
    assert evento.motivo == MotivoRechazo.PARTNER_DESCONOCIDO.value
    assert evento.regla_version is None


def test_rechazo_por_partner_inactivo():
    evento = crear(regla=regla(activo=False))
    assert evento.motivo == MotivoRechazo.PARTNER_INACTIVO.value


def test_la_variabilidad_entre_partners_es_solo_dato():
    """CERO CONDICIONALES POR PARTNER.

    El mismo codigo, con la misma categoria, acepta o rechaza segun lo que diga
    la regla. No hay ninguna rama por partner_id en ninguna parte.
    """
    cubre = crear(partner_id="A", regla=regla(partner_id="A",
                                              categorias_cubiertas=("PLOMERIA",)))
    no_cubre = crear(partner_id="B", regla=regla(partner_id="B",
                                                 categorias_cubiertas=("ASEO",)))
    assert isinstance(cubre, ev.TrabajoCreado)
    assert isinstance(no_cubre, ev.TrabajoRechazado)


def test_requiere_aprobacion_sale_del_tope_del_partner():
    caro = crear(monto_estimado=900_000)
    barato = crear(monto_estimado=100_000)
    assert caro.requiere_aprobacion is True
    assert barato.requiere_aprobacion is False


# ═══════════════════════════════════════════ ESCENARIO: tope de intentos ═══

def _trabajo_creado():
    return dom.Trabajo.reconstruir(TRABAJO, [(1, crear())])


def test_el_primer_rechazo_pide_otro_proveedor():
    trabajo = _trabajo_creado()
    nuevos = dom.decidir_rechazo_de_habilitacion(
        trabajo, proveedor_id="PROV_1", motivo="SUSPENDIDO", max_intentos=3)

    assert [type(e) for e in nuevos] == [ev.ProveedorDescartado, ev.ReasignacionSolicitada]
    assert nuevos[1].proveedores_excluidos == ("PROV_1",)
    assert nuevos[1].intento == 2


def test_al_tercer_rechazo_escala_en_vez_de_reintentar():
    """El tope de reintentos. Sin el, un proveedor mal habilitado y un
    Emparejamiento que lo reasigna harian un bucle infinito."""
    trabajo = _trabajo_creado()
    secuencia = 1

    for i, proveedor in enumerate(["PROV_1", "PROV_2", "PROV_3"], start=1):
        nuevos = dom.decidir_rechazo_de_habilitacion(
            trabajo, proveedor_id=proveedor, motivo="SUSPENDIDO", max_intentos=3)
        for evento in nuevos:
            secuencia += 1
            trabajo.aplicar(evento)
            trabajo.secuencia = secuencia

        if i < 3:
            assert isinstance(nuevos[1], ev.ReasignacionSolicitada), f"intento {i}"
        else:
            assert isinstance(nuevos[1], ev.TrabajoEscalado), "el 3ro debe escalar"

    assert trabajo.estado is EstadoTrabajo.ESCALADO_MANUAL
    assert trabajo.intentos == 3
    assert set(trabajo.proveedores_excluidos) == {"PROV_1", "PROV_2", "PROV_3"}


def test_los_excluidos_se_acumulan_para_que_no_se_repita_el_proveedor():
    trabajo = _trabajo_creado()
    nuevos = dom.decidir_rechazo_de_habilitacion(
        trabajo, proveedor_id="PROV_1", motivo="X", max_intentos=3)
    for e in nuevos:
        trabajo.aplicar(e)

    siguientes = dom.decidir_rechazo_de_habilitacion(
        trabajo, proveedor_id="PROV_2", motivo="X", max_intentos=3)
    assert set(siguientes[1].proveedores_excluidos) == {"PROV_1", "PROV_2"}


def test_compensar_una_asignacion_optimista_vuelve_a_creado():
    """La saga de Entrega 5: ASIGNADO no es irreversible.

    Emparejamiento asigno contra su proyeccion. Acreditacion, duena del dato
    autoritativo, rechaza. El agregado deshace la asignacion: el SLA no se
    cumplio de verdad, el reloj tiene que seguir.
    """
    trabajo = _trabajo_creado()
    for e in dom.decidir_asignacion(trabajo, proveedor_id="PROV_1", asignacion_id="a-1"):
        trabajo.aplicar(e)
    assert trabajo.estado is EstadoTrabajo.ASIGNADO
    assert trabajo.proveedor_id == "PROV_1"

    nuevos = dom.decidir_rechazo_de_habilitacion(
        trabajo, proveedor_id="PROV_1", motivo="SUSPENDIDO", max_intentos=3)
    for e in nuevos:
        trabajo.aplicar(e)

    assert trabajo.estado is EstadoTrabajo.CREADO
    assert trabajo.proveedor_id is None
    assert trabajo.proveedores_excluidos == ("PROV_1",)
    assert isinstance(nuevos[0], ev.ProveedorDescartado)
    assert isinstance(nuevos[1], ev.ReasignacionSolicitada)


# ═════════════════════════════════════════════════ ESCENARIO: SLA y reloj ══

def test_asignar_detiene_el_reloj_del_sla():
    """ASIGNADO es terminal: el SLA es de RESPUESTA, no de ejecucion."""
    trabajo = _trabajo_creado()
    for e in dom.decidir_asignacion(trabajo, proveedor_id="PROV_9"):
        trabajo.aplicar(e)

    assert trabajo.estado is EstadoTrabajo.ASIGNADO
    muy_tarde = AHORA + timedelta(days=30)
    assert dom.decidir_vencimiento(trabajo, muy_tarde) == [], \
        "un trabajo ya asignado no se escala aunque pase el tiempo"


def test_el_sla_vencido_escala():
    trabajo = _trabajo_creado()
    nuevos = dom.decidir_vencimiento(trabajo, AHORA + timedelta(minutes=121))
    assert isinstance(nuevos[0], ev.TrabajoEscalado)
    assert nuevos[0].motivo == "SLA_VENCIDO"


def test_antes_de_vencer_no_pasa_nada():
    trabajo = _trabajo_creado()
    assert dom.decidir_vencimiento(trabajo, AHORA + timedelta(minutes=119)) == []


def test_un_trabajo_rechazado_nunca_se_escala():
    rechazo = crear(categoria="CERRAJERIA")
    trabajo = dom.Trabajo.reconstruir(TRABAJO, [(1, rechazo)])
    assert trabajo.estado is EstadoTrabajo.RECHAZADO
    assert dom.decidir_vencimiento(trabajo, AHORA + timedelta(days=1)) == []


# ══════════════════════════════════════════════ reconstruccion y eventos ═══

def test_el_estado_se_deriva_de_la_historia_no_se_guarda():
    """Event Sourcing: reproducir los mismos eventos da el mismo estado."""
    historia = [
        (1, crear()),
        (2, ev.ProveedorDescartado(trabajo_id=TRABAJO, proveedor_id="P1",
                                   motivo="X", intento=1)),
        (3, ev.ReasignacionSolicitada(trabajo_id=TRABAJO, intento=2,
                                      proveedores_excluidos=("P1",))),
        (4, ev.ProveedorAsignado(trabajo_id=TRABAJO, proveedor_id="P2")),
    ]
    trabajo = dom.Trabajo.reconstruir(TRABAJO, historia)

    assert trabajo.estado is EstadoTrabajo.ASIGNADO
    assert trabajo.proveedor_id == "P2"
    assert trabajo.intentos == 1
    assert trabajo.proveedores_excluidos == ("P1",)
    assert trabajo.secuencia == 4

    # determinista: reconstruir dos veces da lo mismo
    assert dom.Trabajo.reconstruir(TRABAJO, historia) == trabajo


def test_sin_historia_el_trabajo_no_existe():
    trabajo = dom.Trabajo.reconstruir(TRABAJO, [])
    assert trabajo.existe is False
    assert trabajo.secuencia == 0


def test_los_eventos_son_inmutables():
    """Un hecho que ya ocurrio no se corrige: se le agrega otro encima."""
    evento = crear()
    with pytest.raises(Exception):
        evento.sla_minutos = 999


@pytest.mark.parametrize("evento", [
    ev.TrabajoCreado(trabajo_id=TRABAJO, partner_id="P", categoria="PLOMERIA",
                     zona="BOGOTA", sla_minutos=60, regla_version=3, vence_en=AHORA),
    ev.TrabajoRechazado(trabajo_id=TRABAJO, partner_id="P", categoria="X",
                        motivo="M", detalle="D"),
    ev.ProveedorAsignado(trabajo_id=TRABAJO, proveedor_id="P1"),
    ev.ProveedorDescartado(trabajo_id=TRABAJO, proveedor_id="P1", motivo="M", intento=1),
    ev.ReasignacionSolicitada(trabajo_id=TRABAJO, intento=2, proveedores_excluidos=("P1",)),
    ev.TrabajoEscalado(trabajo_id=TRABAJO, motivo="SLA_VENCIDO"),
], ids=lambda e: e.TIPO)
def test_los_eventos_sobreviven_al_viaje_por_el_event_store(evento):
    """a_payload/desde_payload tienen que ser inversas: si no, reconstruir un
    agregado viejo daria un estado distinto del que tuvo."""
    assert ev.rehidratar(evento.TIPO, evento.a_payload()) == evento
