# Contratos vendidos (solo lo que este MS necesita)

Copias bit-a-bit de hogaralpes `entrega4/contratos/esquemas/` para los tópicos que Emparejamiento produce o consume. No se muta la semántica Avro. No se copia `generar.py` ni el resto de comandos/eventos de los otros MS.

| Tópico | Record | Uso |
|---|---|---|
| `evt.partners` | `ReglaDePartnerActualizada` | consume (proyección) |
| `evt.proveedores` | `EstadoDeHabilitacionCambiado` | consume (proyección) |
| `evt.trabajos` | `TrabajoCreado` | consume |
| `evt.trabajos` | `TrabajoAsignado` | produce (único productor) |
| `evt.trabajos` | `TrabajoRechazado` | filtra y descarta |
| `evt.asignaciones` | `AsignacionRechazadaPorHabilitacion` | consume (marca RECHAZADO) |
| `cmd.emparejamiento` | `AsignarProveedor` | **no se consume** (E5); el `.avsc` queda para no inventar el contrato |
