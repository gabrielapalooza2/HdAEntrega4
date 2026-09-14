"""La regla de un partner, como objeto de DOMINIO.

Vive aqui y no en infraestructura/ porque tiene COMPORTAMIENTO de negocio:
decide si una categoria esta cubierta y si un monto necesita aprobacion. La
tabla donde se guarda es un detalle; las decisiones que toma no lo son.

En infraestructura/persistencia/reglas.py queda solo el repositorio -el SQL que
la lee y la escribe-, que es lo que si es un detalle de infraestructura.

Es la pieza que sostiene la regla dura "cero condicionales por partner": toda la
variabilidad entre aseguradoras esta en los CAMPOS de este objeto, que llegan
como dato por evt.partners. No hay ningun `if partner_id == ...` en el servicio.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ReglaDePartner:
    partner_id: str
    regla_version: int
    activo: bool
    sla_minutos: int
    categorias_cubiertas: tuple[str, ...]
    monto_max: Decimal | None
    moneda: str | None

    def cubre(self, categoria: str) -> bool:
        return categoria in self.categorias_cubiertas

    def requiere_aprobacion(self, monto_estimado: int | None) -> bool:
        """Si el trabajo supera el tope del partner, necesita aprobacion.

        Es una decision de negocio que sale ENTERAMENTE de un dato de la regla.
        Sin tope configurado no se exige aprobacion: la ausencia de limite no es
        un limite de cero.
        """
        if self.monto_max is None or monto_estimado is None:
            return False
        return Decimal(monto_estimado) > self.monto_max
