"""Fase 2: el consumidor de evt.partners y sus DOS mecanismos de idempotencia.

Son mecanismos distintos para problemas distintos:
  mensajes_procesados  ->  REPETICION (el mismo mensaje dos veces)
  guarda de version    ->  DESORDEN   (un mensaje viejo llegando tarde)
"""
from decimal import Decimal

import pytest

from orquestacion.aplicacion import reglas as aplicacion
from orquestacion.dominio.regla_partner import ReglaDePartner
from orquestacion.infraestructura.persistencia import reglas
from orquestacion.mensajeria import contratos as c


def _sobre(partner_id="SEGUROS_ANDES", version=1, sla=120,
           categorias=("PLOMERIA", "ELECTRICIDAD"), activo=True, monto=500000):
    return c.empaquetar(
        c.ReglaDePartnerActualizada(
            partner_id=partner_id, regla_version=version, sla_minutos=sla,
            categorias_cubiertas=list(categorias), activo=activo,
            monto_max=Decimal(monto), moneda="COP",
        ),
        service_name="motor-reglas-partner",
    )


def _leer(base, partner_id="SEGUROS_ANDES"):
    with base.pool().connection() as con, con.cursor() as cur:
        return reglas.buscar(cur, partner_id)


def test_una_regla_aterriza_en_la_proyeccion(limpia):
    aplicacion.manejar_regla_actualizada(_sobre())

    regla = _leer(limpia)
    assert regla.regla_version == 1
    assert regla.sla_minutos == 120
    assert regla.categorias_cubiertas == ("PLOMERIA", "ELECTRICIDAD")
    assert regla.monto_max == Decimal("500000.00")
    assert regla.activo is True


def test_el_mismo_sobre_dos_veces_no_hace_nada_la_segunda(limpia):
    """REPETICION. Pulsar entrega al menos una vez: recibir duplicados es
    normal, no excepcional.

    Aqui la repeticion la absorbe la GUARDA DE VERSION, no mensajes_procesados:
    la segunda copia trae la misma version, no es mayor, y el upsert no hace
    nada. Ver el docstring de manejar_regla_actualizada.
    """
    sobre = _sobre(version=1, sla=120)
    aplicacion.manejar_regla_actualizada(sobre)
    aplicacion.manejar_regla_actualizada(sobre)   # MISMO sobre.id

    assert _leer(limpia).sla_minutos == 120
    assert _leer(limpia).regla_version == 1

    # Este manejador NO marca sobres: hacerlo impediria reconstruir la
    # proyeccion releyendo el topico compactado.
    with limpia.pool().connection() as con, con.cursor() as cur:
        cur.execute("SELECT count(*) FROM mensajes_procesados")
        assert cur.fetchone()[0] == 0


def test_la_proyeccion_se_reconstruye_releyendo_los_mismos_mensajes(limpia):
    """LA RAZON DE QUE evt.partners ESTE COMPACTADO.

    Se simula perder la base y volver a aplicar los MISMOS sobres, como haria
    una replica nueva leyendo el topico desde el inicio. La proyeccion tiene que
    quedar igual.

    Si este manejador marcara los sobres contra mensajes_procesados, el replay
    se descartaria entero y la proyeccion quedaria vacia.
    """
    sobres = [_sobre(version=v, sla=v * 10) for v in (1, 2, 3)]
    for s in sobres:
        aplicacion.manejar_regla_actualizada(s)
    antes = _leer(limpia)

    # se pierde la base
    with limpia.pool().connection() as con:
        con.execute("TRUNCATE proyeccion_regla_partner")
    assert _leer(limpia) is None

    # se reprocesan LOS MISMOS sobres, con los MISMOS ids
    for s in sobres:
        aplicacion.manejar_regla_actualizada(s)

    assert _leer(limpia) == antes


def test_una_version_vieja_que_llega_tarde_no_hace_retroceder_el_estado(limpia):
    """DESORDEN. Este es el caso que mensajes_procesados NO cubre: son sobres
    DISTINTOS, con ids distintos, asi que los dos pasan la marca de
    idempotencia. Lo que los ordena es la version."""
    aplicacion.manejar_regla_actualizada(_sobre(version=5, sla=60))
    aplicacion.manejar_regla_actualizada(_sobre(version=3, sla=999))  # reentrega tardia

    regla = _leer(limpia)
    assert regla.regla_version == 5, "la v3 piso a la v5"
    assert regla.sla_minutos == 60

    # Los dos mensajes SE PROCESARON; lo que impidio que la v3 pisara a la v5
    # fue la guarda de version.


def test_aplicar_versiones_en_cualquier_orden_converge(limpia):
    """Con la guarda de version, el orden de llegada deja de importar: la mayor
    gana. Es lo que hace seguro consumir en paralelo."""
    for v in (2, 7, 1, 5, 3):
        aplicacion.manejar_regla_actualizada(_sobre(version=v, sla=v * 10))
    regla = _leer(limpia)
    assert (regla.regla_version, regla.sla_minutos) == (7, 70)


def test_una_version_mas_nueva_si_actualiza(limpia):
    aplicacion.manejar_regla_actualizada(_sobre(version=1, categorias=("PLOMERIA",)))
    aplicacion.manejar_regla_actualizada(
        _sobre(version=2, categorias=("PLOMERIA", "CERRAJERIA"), sla=45))

    regla = _leer(limpia)
    assert regla.regla_version == 2
    assert regla.categorias_cubiertas == ("PLOMERIA", "CERRAJERIA")
    assert regla.sla_minutos == 45


def test_partners_distintos_no_se_pisan(limpia):
    aplicacion.manejar_regla_actualizada(_sobre(partner_id="SEGUROS_ANDES", version=4))
    aplicacion.manejar_regla_actualizada(
        _sobre(partner_id="SEGUROS_BETA", version=1, categorias=("ELECTRICIDAD",)))

    assert _leer(limpia, "SEGUROS_ANDES").regla_version == 4
    assert _leer(limpia, "SEGUROS_BETA").categorias_cubiertas == ("ELECTRICIDAD",)


def test_partner_desconocido_da_none_y_no_revienta(limpia):
    """None no es un error tecnico: significa que todavia no vimos a ese
    partner, y es una causa legitima de rechazo."""
    assert _leer(limpia, "NO_EXISTE") is None


# ─────────────────────────── la regla como objeto de dominio ───────────────

def test_la_regla_decide_cobertura_y_aprobacion_sin_condicionales_por_partner():
    """Toda la variabilidad entre aseguradoras es DATO. No hay ningun
    `if partner_id == ...` en ninguna parte."""
    regla = ReglaDePartner(
        partner_id="X", regla_version=1, activo=True, sla_minutos=60,
        categorias_cubiertas=("PLOMERIA",), monto_max=Decimal("500000"), moneda="COP")

    assert regla.cubre("PLOMERIA")
    assert not regla.cubre("CERRAJERIA")
    assert regla.requiere_aprobacion(600000) is True
    assert regla.requiere_aprobacion(400000) is False
    assert regla.requiere_aprobacion(None) is False


def test_sin_tope_configurado_no_se_exige_aprobacion():
    regla = ReglaDePartner(
        partner_id="X", regla_version=1, activo=True, sla_minutos=60,
        categorias_cubiertas=("PLOMERIA",), monto_max=None, moneda=None)
    assert regla.requiere_aprobacion(10_000_000) is False
