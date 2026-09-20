from fastapi import APIRouter, HTTPException

from ..infraestructura.operaciones import registro
from ..infraestructura.proyeccion import proyeccion

router = APIRouter(tags=["Consultas"])


@router.get("/operaciones/{correlation_id}", summary="Estado de una operacion asincrona")
def estado_de_operacion(correlation_id: str):

    op = registro.obtener(correlation_id)
    if op is None:
        raise HTTPException(404, f"no hay ninguna operacion con id {correlation_id}")
    return op.como_dict()


@router.get("/operaciones", summary="Ultimas operaciones, para seguir la saga en vivo")
def listar_operaciones(limite: int = 50):
    return {"operaciones": registro.listar(limite)}


@router.get("/partners", summary="Partners conocidos")
def listar_partners():
    return {"partners": list(proyeccion.partners.values())}


@router.get("/partners/{partner_id}", summary="Un partner con su regla vigente")
def obtener_partner(partner_id: str):
    p = proyeccion.partners.get(partner_id)
    if p is None:
        raise HTTPException(404, f"partner {partner_id} no esta en la proyeccion")
    return p


@router.get("/proveedores", summary="Proveedores y su estado de habilitacion")
def listar_proveedores():
    return {"proveedores": list(proyeccion.proveedores.values())}


@router.get("/proveedores/{proveedor_id}", summary="Un proveedor")
def obtener_proveedor(proveedor_id: str):
    p = proyeccion.proveedores.get(proveedor_id)
    if p is None:
        raise HTTPException(404, f"proveedor {proveedor_id} no esta en la proyeccion")
    return p


@router.get("/trabajos", summary="Trabajos y su estado")
def listar_trabajos(estado: str | None = None):
    trabajos = list(proyeccion.trabajos.values())
    if estado:
        trabajos = [t for t in trabajos if t.get("estado") == estado.upper()]
    return {"trabajos": trabajos}


@router.get("/trabajos/{trabajo_id}", summary="Vista compuesta: trabajo + partner + asignacion")
def obtener_trabajo(trabajo_id: str):

    vista = proyeccion.trabajo_compuesto(trabajo_id)
    if vista is None:
        raise HTTPException(404, f"trabajo {trabajo_id} no esta en la proyeccion")
    return vista


@router.get("/sagas/{trabajo_id}", summary="Linea de tiempo de la saga de un trabajo")
def saga_de_un_trabajo(trabajo_id: str):

    vista = proyeccion.saga(trabajo_id)
    if vista["estado"] == "DESCONOCIDA":
        raise HTTPException(404, f"no hay eventos de saga para el trabajo {trabajo_id}")
    return vista


@router.get("/sagas", summary="Sagas conocidas y su estado")
def listar_sagas(estado: str | None = None):
    todas = [proyeccion.saga(t) for t in proyeccion.sagas]
    if estado:
        todas = [s for s in todas if s["estado"] == estado.upper()]
    return {"sagas": todas}


@router.get("/proyeccion", summary="Cuantos eventos ha aplicado el BFF")
def estado_de_la_proyeccion():
    """Util en la demostracion: prueba que la vista se construyo del bus."""
    return proyeccion.estadisticas()
