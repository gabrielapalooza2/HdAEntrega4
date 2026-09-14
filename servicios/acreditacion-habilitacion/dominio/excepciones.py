"""Excepciones especificas del modulo Acreditacion."""
from ._base import ExcepcionDominio


class ProveedorNoExiste(ExcepcionDominio):
    def __init__(self, proveedor_id: str):
        self.proveedor_id = proveedor_id
        super().__init__(f"No existe un proveedor con id {proveedor_id}")
