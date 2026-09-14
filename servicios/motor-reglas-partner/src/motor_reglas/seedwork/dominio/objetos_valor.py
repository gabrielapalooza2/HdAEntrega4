from dataclasses import dataclass


@dataclass(frozen=True)
class ObjetoValor:
    ...


@dataclass(frozen=True)
class Dinero(ObjetoValor):
    monto: int    
    moneda: str  

    def __post_init__(self):
        if self.monto < 0:
            raise ValueError("Un monto no puede ser negativo")
        if not self.moneda or len(self.moneda) != 3:
            raise ValueError("La moneda debe ser un código ISO-4217 de 3 letras")

    def _misma_moneda(self, otro: "Dinero"):
        if self.moneda != otro.moneda:
            raise ValueError(
                f"No se pueden operar montos de monedas distintas: {self.moneda} y {otro.moneda}"
            )

    def __add__(self, otro: "Dinero") -> "Dinero":
        self._misma_moneda(otro)
        return Dinero(self.monto + otro.monto, self.moneda)

    def __gt__(self, otro: "Dinero") -> bool:
        self._misma_moneda(otro)
        return self.monto > otro.monto

    def __str__(self) -> str:
        return f"{self.monto / 100:.2f} {self.moneda}"
