"""Puerto de verificacion externa (Policia Nacional / RUES). Escenario 8."""
from abc import ABC, abstractmethod

from .objetos_valor import ResultadoVerificacion


class VerificadorAntecedentes(ABC):
    @abstractmethod
    def verificar(self, proveedor_id: str, fuente: str) -> ResultadoVerificacion: ...
