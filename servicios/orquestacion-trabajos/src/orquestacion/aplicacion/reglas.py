"""Manejador del evento ReglaDePartnerActualizada.

La capa de aplicacion orquesta: abre la transaccion, decide el orden de los
pasos y no sabe nada de Pulsar ni de Avro. Recibe un mensaje YA TRADUCIDO al
vocabulario propio por la costura.
"""
import logging

from orquestacion.dominio.regla_partner import ReglaDePartner
from orquestacion.infraestructura.persistencia import bd, reglas
from orquestacion.mensajeria import contratos as c

logger = logging.getLogger(__name__)


def manejar_regla_actualizada(sobre: c.Sobre) -> None:
    """Aplica una regla de partner a la proyeccion local.

    TODO ocurre en UNA SOLA TRANSACCION: la marca de idempotencia y el upsert de
    la proyeccion. Si el upsert fallara, la marca se va con el rollback y el
    mensaje se reprocesa en la siguiente entrega.
    """
    mensaje: c.ReglaDePartnerActualizada = sobre.contenido()

    regla = ReglaDePartner(
        partner_id=mensaje.partner_id,
        regla_version=mensaje.regla_version,
        activo=mensaje.activo,
        sla_minutos=mensaje.sla_minutos,
        categorias_cubiertas=tuple(mensaje.categorias_cubiertas),
        monto_max=mensaje.monto_max,
        moneda=mensaje.moneda,
    )

    with bd.pool().connection() as con:
        with con.cursor() as cur:
            if not bd.reclamar_mensaje(cur, sobre.id):
                logger.info("Regla %s v%s: sobre %s repetido, se descarta",
                            regla.partner_id, regla.regla_version, sobre.id)
                return

            if reglas.guardar(cur, regla):
                logger.info("Regla aplicada: partner=%s v=%s sla=%smin cubre=%s",
                            regla.partner_id, regla.regla_version,
                            regla.sla_minutos, list(regla.categorias_cubiertas))
            else:
                # No es un fallo: es la guarda de version haciendo su trabajo.
                logger.info("Regla %s v%s descartada por ser mas vieja que la "
                            "aplicada", regla.partner_id, regla.regla_version)
