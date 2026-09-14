from motor_reglas.seedwork.dominio.excepciones import ExcepcionDominio


class PartnerNoExiste(ExcepcionDominio):
    def __init__(self, partner_id):
        super().__init__(f"No existe un partner con id {partner_id}")


class TipoObjetoNoExisteEnDominioPartnersExcepcion(ExcepcionDominio):
    def __init__(self, mensaje="No existe el tipo de objeto solicitado en el dominio de partners"):
        super().__init__(mensaje)
