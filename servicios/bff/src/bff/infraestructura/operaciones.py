import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Estados posibles de una operacion.
ACEPTADA = "ACEPTADA"      
COMPLETADA = "COMPLETADA" 
RECHAZADA = "RECHAZADA"    


@dataclass
class Operacion:
    correlation_id: str
    tipo: str
    topico: str
    estado: str = ACEPTADA
    aceptada_en: float = field(default_factory=time.time)
    resuelta_en: float | None = None
    resultado: dict[str, Any] | None = None
    motivo: str | None = None

    def como_dict(self) -> dict:
        d = {
            "correlation_id": self.correlation_id,
            "tipo": self.tipo,
            "topico": self.topico,
            "estado": self.estado,
            "aceptada_en": self.aceptada_en,
        }
        if self.resuelta_en is not None:
            d["resuelta_en"] = self.resuelta_en
            d["duracion_ms"] = round((self.resuelta_en - self.aceptada_en) * 1000)
        if self.resultado is not None:
            d["resultado"] = self.resultado
        if self.motivo is not None:
            d["motivo"] = self.motivo
        return d


class RegistroDeOperaciones:


    def __init__(self, maximo: int = 5000):
        self._ops: dict[str, Operacion] = {}
        self._orden: list[str] = []
        self._maximo = maximo
        self._candado = threading.Lock()

    def registrar(self, tipo: str, topico: str) -> Operacion:
        op = Operacion(correlation_id=str(uuid.uuid4()), tipo=tipo, topico=topico)
        with self._candado:
            self._ops[op.correlation_id] = op
            self._orden.append(op.correlation_id)
            while len(self._orden) > self._maximo:
                self._ops.pop(self._orden.pop(0), None)
        return op

    def resolver(self, correlation_id: str, estado: str,
                 resultado: dict | None = None, motivo: str | None = None):
        """La llama la proyeccion cuando llega un evento con ese correlation_id."""
        if not correlation_id:
            return
        with self._candado:
            op = self._ops.get(correlation_id)
            if op is None or op.estado != ACEPTADA:
                return         
            op.estado = estado
            op.resultado = resultado
            op.motivo = motivo
            op.resuelta_en = time.time()

    def obtener(self, correlation_id: str) -> Operacion | None:
        with self._candado:
            return self._ops.get(correlation_id)

    def listar(self, limite: int = 50) -> list[dict]:
        with self._candado:
            ids = list(reversed(self._orden))[:limite]
            return [self._ops[i].como_dict() for i in ids if i in self._ops]


registro = RegistroDeOperaciones()
