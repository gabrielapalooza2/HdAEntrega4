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

    ─── POR QUE AQUI NO SE USA mensajes_procesados ───────────────────────
    Los demas manejadores marcan el sobre contra mensajes_procesados. Este NO,
    y es una decision, no un olvido.

    La marca por id de mensaje protege EFECTOS QUE NO SON IDEMPOTENTES POR SI
    MISMOS: crear un trabajo dos veces crea dos trabajos. Pero esto es una
    PROYECCION PURA con guarda de version: aplicar la misma regla dos veces da
    exactamente el mismo resultado, porque la guarda convierte la repeticion en
    un no-op. La marca no agregaria ninguna seguridad.

    Y si haria daño. evt.partners esta COMPACTADO precisamente para que una
    replica nueva, o una base restaurada, pueda RECONSTRUIR la proyeccion
    releyendo el topico desde el inicio. Con la marca puesta, ese replay se
    descartaria entero como "ya procesado" y la proyeccion quedaria vacia: la
    idempotencia habria bloqueado la reconstruccion.

    En resumen: idempotencia por VERSION donde el estado converge; idempotencia
    por ID DE MENSAJE solo donde el efecto no es repetible.
    ───────────────────────────────────────────────────────────────────────
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
            if reglas.guardar(cur, regla):
                logger.info("Regla aplicada: partner=%s v=%s sla=%smin cubre=%s",
                            regla.partner_id, regla.regla_version,
                            regla.sla_minutos, list(regla.categorias_cubiertas))
            else:
                # No es un fallo: es la guarda de version haciendo su trabajo.
                # Cubre tanto la reentrega del mismo mensaje como la llegada
                # tardia de una version vieja.
                logger.info("Regla %s v%s sin efecto: no es mas nueva que la "
                            "aplicada", regla.partner_id, regla.regla_version)
