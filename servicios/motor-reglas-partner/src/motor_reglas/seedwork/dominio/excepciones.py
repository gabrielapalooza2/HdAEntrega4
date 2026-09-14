class ExcepcionDominio(Exception):
    """Raíz de todas las excepciones de dominio."""


class ExcepcionReglaDeNegocio(ExcepcionDominio):
    def __init__(self, regla):
        self.regla = regla
        super().__init__(str(regla))


class IdDebeSerInmutableExcepcion(ExcepcionDominio):
    def __init__(self, mensaje="El identificador de una entidad es inmutable"):
        super().__init__(mensaje)


class ExcepcionFabrica(ExcepcionDominio):
    ...
