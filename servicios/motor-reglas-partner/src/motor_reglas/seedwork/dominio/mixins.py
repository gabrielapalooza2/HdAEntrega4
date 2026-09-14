from .excepciones import ExcepcionReglaDeNegocio
from .reglas import ReglaNegocio


class ValidarReglasMixin:

    def validar_regla(self, regla: ReglaNegocio):
        if not regla.es_valido():
            raise ExcepcionReglaDeNegocio(regla)
