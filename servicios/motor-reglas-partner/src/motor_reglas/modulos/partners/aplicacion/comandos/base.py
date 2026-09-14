from abc import ABC

from motor_reglas.seedwork.aplicacion.comandos import ComandoHandler

from ...infraestructura.repositorios import RepositorioPartnersSQLAlchemy


class RegistrarPartnerBaseHandler(ComandoHandler, ABC):
    """Provee el repositorio a los handlers. La capa de aplicación no sabe que
    detrás hay SQLAlchemy: recibe una implementación de la interfaz del dominio."""

    def __init__(self):
        self._repositorio = RepositorioPartnersSQLAlchemy()

    @property
    def repositorio(self):
        return self._repositorio
