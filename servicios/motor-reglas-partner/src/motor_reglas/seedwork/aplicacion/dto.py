from dataclasses import dataclass


@dataclass(frozen=True)
class DTO:
    """Estructura plana que cruza la frontera de la aplicación. No tiene comportamiento."""
