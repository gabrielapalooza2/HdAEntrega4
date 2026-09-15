from motor_reglas.seedwork.dominio.excepciones import ExcepcionDominio


class PartnerNoExiste(ExcepcionDominio):
    def __init__(self, partner_id):
        super().__init__(f"No existe un partner con id {partner_id}")


class PartnerIdInvalido(ExcepcionDominio):
    def __init__(self, partner_id):
        super().__init__(
            f"El id de partner debe ser un UUID. Recibido: {partner_id!r}. "
            "Usa el campo id que devuelve POST /partners "
            "(no el partner-31 del flujo de emparejamiento)."
        )


class TipoObjetoNoExisteEnDominioPartnersExcepcion(ExcepcionDominio):
    def __init__(self, mensaje="No existe el tipo de objeto solicitado en el dominio de partners"):
        super().__init__(mensaje)
