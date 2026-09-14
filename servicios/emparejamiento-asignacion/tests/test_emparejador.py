from __future__ import annotations

from dominio.emparejador import emparejar
from dominio.modelo import ProyeccionHabilitacion, ProyeccionReglaPartner, TrabajoParaAsignar


def _trabajo(**kwargs) -> TrabajoParaAsignar:
    base = dict(
        trabajo_id="t-1",
        partner_id="partner-31",
        mercado_id="CO",
        categoria="PLOMERIA",
        urgencia="ALTA",
        ciudad="Bogota",
        sla_minutos=120,
        ocurrido_en=1_700_000_000_000,
        correlacion_id="corr-1",
        evento_id="evt-1",
    )
    base.update(kwargs)
    return TrabajoParaAsignar(**base)


def _hab(proveedor_id, estado="HABILITADO", categorias=None, ciudades=None, vigente_hasta=None):
    return ProyeccionHabilitacion(
        proveedor_id=proveedor_id,
        estado=estado,
        categorias=tuple(categorias or ("PLOMERIA",)),
        ciudades=tuple(ciudades or ("Bogota",)),
        vigente_hasta=vigente_hasta,
    )


def test_elige_menor_proveedor_id_entre_habilitados():
    regla = ProyeccionReglaPartner("partner-31", (), True, None)
    habs = [_hab("prov-b"), _hab("prov-a"), _hab("prov-c")]
    asignacion, evento, fallida = emparejar(_trabajo(), regla, habs, 1_700_000_000_000, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "prov-a"
    assert asignacion.partner_id == "partner-31"
    assert evento.service_name == "emparejamiento-asignacion"
    assert evento.type == "TrabajoAsignado"
    assert evento.correlation_id == "corr-1"
    assert evento.partner_id == "partner-31"
    assert evento.sla_vence_en == 1_700_000_000_000 + 120 * 60 * 1000
    assert evento.origen_habilitacion == "PROYECCION_LOCAL"
    assert asignacion.verificado_en == 1_700_000_000_000


def test_red_homologada_no_vacia_filtra():
    regla = ProyeccionReglaPartner("partner-31", ("prov-c",), True, None)
    habs = [_hab("prov-a"), _hab("prov-c")]
    asignacion, evento, fallida = emparejar(_trabajo(), regla, habs, 1_700_000_000_000, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "prov-c"


def test_red_homologada_vacia_no_restringe():
    regla = ProyeccionReglaPartner("partner-31", (), True, None)
    habs = [_hab("prov-z")]
    asignacion, _, fallida = emparejar(_trabajo(), regla, habs, 1_700_000_000_000, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "prov-z"


def test_sin_regla_equivale_a_red_vacia():
    habs = [_hab("prov-a")]
    asignacion, _, fallida = emparejar(_trabajo(), None, habs, 1_700_000_000_000, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "prov-a"


def test_excluye_no_habilitado_categoria_ciudad_y_vencido():
    ahora = 1_000
    habs = [
        _hab("p-susp", estado="SUSPENDIDO"),
        _hab("p-cat", categorias=("ELECTRICIDAD",)),
        _hab("p-ciu", ciudades=("Medellin",)),
        _hab("p-ven", vigente_hasta=999),
        _hab("p-ok", vigente_hasta=None),
    ]
    asignacion, _, fallida = emparejar(_trabajo(), None, habs, ahora, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "p-ok"


def test_vigente_hasta_cero_es_sin_fin():
    habs = [_hab("p-ok", vigente_hasta=0)]
    asignacion, _, fallida = emparejar(_trabajo(), None, habs, 1_000, "a1", "e1")
    assert fallida is None
    assert asignacion.proveedor_id == "p-ok"


def test_sin_candidatos_no_publica():
    habs = [_hab("p-susp", estado="INHABILITADO")]
    asignacion, evento, fallida = emparejar(_trabajo(), None, habs, 1, "a1", "e1")
    assert asignacion is None
    assert evento is None
    assert fallida is not None
    assert fallida.motivo == "SIN_CANDIDATOS"
