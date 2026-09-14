"""Pruebas del DOMINIO: sin base de datos, sin broker, sin Flask.

Que estas pruebas corran sin infraestructura ES la evidencia de que la inversión
de dependencias está bien hecha. Si el dominio necesitara una base de datos para
probarse, no sería un dominio: sería una capa de acceso a datos con nombre bonito.
"""
from datetime import datetime, timedelta

import pytest

from motor_reglas.modulos.partners.dominio.entidades import Convenio, Partner, ReglaDePartner
from motor_reglas.modulos.partners.dominio.objetos_valor import (
    AcuerdoDeServicio, Categoria, CoberturaContratada, RedHomologada, Tarifa, TipoPartner, Vigencia)
from motor_reglas.seedwork.dominio.excepciones import ExcepcionReglaDeNegocio
from motor_reglas.seedwork.dominio.objetos_valor import Dinero


def construir_partner(categorias=(Categoria.PLOMERIA,), red=()):
    p = Partner(nombre="Aseguradora Andina", tipo=TipoPartner.ASEGURADORA)
    convenio = Convenio(numero="CONV-2026-031",
                        vigencia=Vigencia(desde=datetime.utcnow() - timedelta(days=1)),
                        tarifa=Tarifa(12.5, "COP"))
    p.firmar_convenio(convenio)
    p.definir_regla(ReglaDePartner(
        cobertura=CoberturaContratada(tuple(categorias)),
        acuerdo=AcuerdoDeServicio(120, Dinero(50_000_00, "COP"), ("ANALISTA",)),
        red_homologada=RedHomologada(tuple(red)),
    ), convenio.id)
    return p


def test_dinero_no_suma_monedas_distintas():
    """El objeto valor Dinero es la defensa contra el error silencioso al abrir
    un mercado nuevo: sumar COP con MXN falla en el dominio."""
    with pytest.raises(ValueError):
        Dinero(1000, "COP") + Dinero(1000, "MXN")


def test_partner_nuevo_no_requiere_codigo_nuevo():
    """ESCENARIO 6: la variabilidad entre partners es DATO."""
    p = construir_partner(categorias=(Categoria.PLOMERIA, Categoria.ELECTRICIDAD))
    assert p.puede_solicitar(Categoria.PLOMERIA) is True
    assert p.puede_solicitar(Categoria.CARPINTERIA) is False   # fuera de cobertura, sin un solo `if` por partner


def test_partner_sin_categorias_viola_invariante():
    p = Partner(nombre="X", tipo=TipoPartner.BANCO)
    convenio = Convenio(numero="C1", vigencia=Vigencia(desde=datetime.utcnow()))
    p.firmar_convenio(convenio)
    with pytest.raises(ExcepcionReglaDeNegocio):
        p.definir_regla(ReglaDePartner(
            cobertura=CoberturaContratada(()),
            acuerdo=AcuerdoDeServicio(60, Dinero(100, "COP")),
        ), convenio.id)


def test_definir_regla_sube_version_y_emite_evento():
    p = construir_partner()
    assert p.regla.version == 1
    assert len(p.eventos) == 1
    p.limpiar_eventos()
    p.definir_regla(ReglaDePartner(
        cobertura=CoberturaContratada((Categoria.PINTURA,)),
        acuerdo=AcuerdoDeServicio(90, Dinero(100_00, "COP")),
    ), p.convenio.id)
    assert p.regla.version == 2
    assert p.eventos[0].version_regla == 2


def test_convenio_vencido_deshabilita_al_partner():
    p = construir_partner()
    p.convenio.vigencia = Vigencia(desde=datetime.utcnow() - timedelta(days=10),
                                   hasta=datetime.utcnow() - timedelta(days=1))
    assert p.puede_solicitar(Categoria.PLOMERIA) is False


def test_red_homologada_filtra_proveedores():
    p = construir_partner(red=("prov-001", "prov-002"))
    assert p.regla.admite_proveedor("prov-001") is True
    assert p.regla.admite_proveedor("prov-999") is False


def test_baja_no_borra_sino_que_publica():
    """En un tópico compactado la ausencia de mensaje no borra nada: la baja
    tiene que viajar como un mensaje con activo=False."""
    p = construir_partner()
    p.limpiar_eventos()
    p.dar_de_baja("terminación de convenio")
    assert p.activo is False
    assert any(e.__class__.__name__ == "ReglaDePartnerActualizada" for e in p.eventos)


def test_acuerdo_decide_si_requiere_aprobacion():
    p = construir_partner()
    assert p.regla.acuerdo.requiere_aprobacion(Dinero(60_000_00, "COP")) is True
    assert p.regla.acuerdo.requiere_aprobacion(Dinero(10_000_00, "COP")) is False
