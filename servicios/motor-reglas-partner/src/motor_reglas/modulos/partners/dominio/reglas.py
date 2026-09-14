"""Invariantes de la agregación Partner.

Cada regla es una clase con nombre. En la sustentación esto importa: un invariante
con nombre se puede señalar en el código y explicar; un `if` dentro de un método
hay que ir a buscarlo.
"""

from motor_reglas.seedwork.dominio.reglas import ReglaNegocio


class ConvenioDebeTenerVigenciaValida(ReglaNegocio):
    def __init__(self, vigencia, mensaje="El convenio debe tener una vigencia válida"):
        super().__init__(mensaje)
        self.vigencia = vigencia

    def es_valido(self) -> bool:
        return self.vigencia is not None and self.vigencia.desde is not None


class PartnerDebeTenerAlMenosUnaCategoria(ReglaNegocio):
    def __init__(self, cobertura, mensaje="Un partner debe tener al menos una categoría contratada"):
        super().__init__(mensaje)
        self.cobertura = cobertura

    def es_valido(self) -> bool:
        return self.cobertura is not None and len(self.cobertura.categorias) > 0


class ReglaDebePertenecerAlConvenioDelPartner(ReglaNegocio):
    """Este es el invariante que justifica que Partner sea UNA agregación y no tres.

    Una regla no puede existir sin el convenio que la respalda, y las dos cosas
    tienen que quedar consistentes en la misma transacción. Ese es exactamente el
    criterio de Evans para trazar una frontera transaccional.
    """

    def __init__(self, partner, convenio_id, mensaje="La regla debe pertenecer al convenio vigente del partner"):
        super().__init__(mensaje)
        self.partner = partner
        self.convenio_id = convenio_id

    def es_valido(self) -> bool:
        return self.partner.convenio is not None and str(self.partner.convenio.id) == str(self.convenio_id)
