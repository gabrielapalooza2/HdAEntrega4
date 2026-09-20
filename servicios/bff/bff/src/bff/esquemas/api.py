"""Modelos de la API publica del BFF.

ESTOS NO SON LOS CONTRATOS DEL BUS. Son el lenguaje que el BFF le ofrece a sus
clientes, y estan pensados para que sea comodo llamarlos desde Postman o desde
una aplicacion movil: fechas en ISO-8601 en vez de milisegundos, montos en pesos
en vez de centavos, y campos opcionales con valores razonables por defecto.

Que sean distintos a los del bus ES el punto del patron: el BFF traduce entre el
modelo de la interfaz y el modelo del dominio. Si fueran identicos, el BFF no
estaria aportando nada y seria un proxy.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DineroEntrada(BaseModel):
    monto: float = Field(..., description="Monto en unidades mayores, p. ej. 500000.00 pesos")
    moneda: str = Field("COP", description="Codigo ISO-4217")

    def a_centavos(self) -> int:
        return int(round(self.monto * 100))


class ReglaEntrada(BaseModel):
    cobertura_contratada: list[str] = Field(..., examples=[["PLOMERIA", "ELECTRICIDAD"]])
    sla_minutos: int = Field(..., ge=1, examples=[120])
    monto_maximo_sin_aprobacion: DineroEntrada
    pasos_de_aprobacion: list[str] = Field(default_factory=list)
    red_homologada: list[str] = Field(default_factory=list)


class RegistrarPartnerEntrada(BaseModel):
    nombre: str = Field(..., examples=["Aseguradora Andina"])
    tipo_partner: str = Field(..., examples=["ASEGURADORA"],
                              description="ASEGURADORA | BANCO | COMERCIO")
    convenio_numero: str = Field(..., examples=["CONV-2026-031"])
    vigencia_desde: datetime
    vigencia_hasta: datetime | None = None
    porcentaje_comision: float = 0.0
    moneda_tarifa: str = "COP"
    regla: ReglaEntrada


class ActualizarReglaEntrada(BaseModel):
    cobertura_contratada: list[str]
    sla_minutos: int = Field(..., ge=1)
    monto_maximo_sin_aprobacion: DineroEntrada
    pasos_de_aprobacion: list[str] = Field(default_factory=list)
    red_homologada: list[str] = Field(default_factory=list)


class AcreditarProveedorEntrada(BaseModel):
    nombre: str = Field(..., examples=["Plomeria Express SAS"])
    categorias: list[str] = Field(..., examples=[["PLOMERIA"]])
    ciudades: list[str] = Field(..., examples=[["BOGOTA"]])
    vigente_hasta: datetime | None = None


class SuspenderProveedorEntrada(BaseModel):
    motivo: str = Field(..., examples=["Poliza de responsabilidad civil vencida"])


class CrearTrabajoEntrada(BaseModel):
    partner_id: str
    categoria: str = Field(..., examples=["PLOMERIA"])
    ciudad: str = Field(..., examples=["BOGOTA"])
    descripcion: str = Field("", examples=["Fuga en el bano principal"])
    urgencia: str = Field("NORMAL", examples=["NORMAL"], description="NORMAL | ALTA")
    mercado_id: str = ""
    monto_estimado: DineroEntrada | None = None


class OperacionAceptada(BaseModel):
    """Lo que devuelve TODA escritura. 202, nunca 200."""

    correlation_id: str
    estado: str = "ACEPTADA"
    tipo: str
    topico: str
    consultar_en: str = Field(..., description="URL del recurso de estado de esta operacion")
    recurso_id: str | None = Field(
        None,
        description=(
            "Identificador que el BFF genero para el recurso creado. Se devuelve "
            "de inmediato para que el cliente pueda encadenar llamadas sin esperar "
            "a que el comando se procese."
        ),
    )


def a_millis(momento: datetime | None) -> int:
    return int(momento.timestamp() * 1000) if momento else 0
