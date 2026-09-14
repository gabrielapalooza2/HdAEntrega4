# Orquestación de Trabajos

Microservicio dueño del agregado `Trabajo`. **Event Sourcing + CQRS**, comunicado
con el resto del sistema únicamente por Apache Pulsar.

Vive dentro del monorepo `HdAEntrega4`. El `docker-compose.yml` y el
`scripts/crear_topicos.sh` de la **raíz** son compartidos por los cuatro
servicios; este directorio solo contiene lo propio.

## Estado

| Fase | Qué | Estado |
|---|---|---|
| 1 | Andamiaje: esquema SQL, costura de contratos, herramientas | ✅ |
| 2 | Consumidor de `evt.partners` → proyección de reglas | pendiente |
| 3 | `CrearTrabajo` → `TrabajoCreado` / `TrabajoRechazado` | ✅ |
| 4 | API `GET /trabajos/{id}/estado` | ✅ |
| 5 | Reasignación con tope de 3 intentos | ✅ |
| 6 | Barrido de SLA | ✅ |
| 7 | Pruebas de los escenarios | ✅ |

## Levantar

Desde la **raíz** del repo:

```bash
make infra      # Pulsar (cluster) + las 4 bases de datos
make topicos    # tenant, namespace, 12 tópicos, retención, compatibilidad
```

> `make topicos` es idempotente y **debe correrlo un solo servicio**. El
> namespace lo comparten los cuatro: si cada uno lo creara con políticas
> distintas, ganaría el que arranque primero.

## Desarrollo local sin contenedor

```bash
cd servicios/orquestacion-trabajos
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# base de pruebas desechable (el 5432 suele estar ocupado)
docker run -d --name orq-test-pg -e POSTGRES_DB=trabajos \
  -e POSTGRES_USER=trabajos -e POSTGRES_PASSWORD=trabajos \
  -p 55432:5432 postgres:16-alpine

export PULSAR_URL=pulsar://localhost:6650
export DATABASE_DSN=postgresql://trabajos:trabajos@localhost:55432/trabajos
export PUERTO_API=5099          # en macOS AirPlay ocupa el 5000

PYTHONPATH=src ./.venv/bin/python -m pytest tests -q
PYTHONPATH=src ./.venv/bin/python -u -m orquestacion.main
```

Las pruebas que tocan PostgreSQL se **saltan solas** si no hay base; las de la
costura no necesitan nada.

## Demo de punta a punta

```bash
# 1. sembrar reglas (PUBLICA en evt.partners; no hace INSERT)
./.venv/bin/python scripts/seed.py

# 2. camino feliz: SEGUROS_ALFA cubre PLOMERIA
./.venv/bin/python scripts/publicar.py CrearTrabajo \
  --partner-id SEGUROS_ALFA --categoria PLOMERIA

# 3. rechazo: SEGUROS_BETA NO cubre PLOMERIA
./.venv/bin/python scripts/publicar.py CrearTrabajo \
  --partner-id SEGUROS_BETA --categoria PLOMERIA

# 4. rechazo: partner inactivo
./.venv/bin/python scripts/publicar.py CrearTrabajo \
  --partner-id PARTNER_DORMIDO --categoria PLOMERIA

# 5. ver lo que salió
./.venv/bin/python scripts/escuchar.py evt.trabajos --desde-el-inicio --maximo 5

# 6. consultar el estado (mirá el header X-Proyeccion-Secuencia)
curl -D- http://localhost:5099/trabajos/<TRABAJO_ID>/estado

# 7. reasignación: tres rechazos de habilitación -> escala al tercero
for P in PROV_1 PROV_2 PROV_3; do
  ./.venv/bin/python scripts/publicar.py AsignacionRechazadaPorHabilitacion \
    --trabajo-id <TRABAJO_ID> --proveedor-id $P
done

# 8. los comandos que salieron (solo DOS, el tercero escaló)
./.venv/bin/python scripts/escuchar.py cmd.emparejamiento --desde-el-inicio --maximo 3

# 9. barrido de SLA: ASISTENCIA_GAMMA tiene SLA de 1 minuto
./.venv/bin/python scripts/publicar.py CrearTrabajo \
  --partner-id ASISTENCIA_GAMMA --categoria PLOMERIA
# esperar ~1 min y volver a consultar: queda en ESCALADO_MANUAL
```

> **La cadena se corta en el paso 8.** Emparejamiento tiene un test que
> **exige** no consumir `cmd.emparejamiento`, así que el comando sale bien
> formado pero nadie lo recoge. Es deuda del grupo, no de este servicio.

## Demo con Emparejamiento y Asignación

Con los dos servicios levantados, el camino principal cierra en coreografía
pura:

```
orquestacion-trabajos      CrearTrabajo -> TrabajoCreado
emparejamiento-asignacion  reacciona, asigna -> TrabajoAsignado
orquestacion-trabajos      consume el ajeno -> ASIGNADO
```

Emparejamiento necesita proveedores habilitados, que publica Acreditación
(todavía no existe). Hasta que exista, se simulan publicando
`EstadoDeHabilitacionCambiado` en `evt.proveedores`.

> **Cuidado con las mayúsculas.** Emparejamiento compara la ciudad con `in`
> exacto y no normaliza: si sus proveedores están en `"Bogota"` y el trabajo va
> con `zona="BOGOTA"`, no encuentra candidatos. Hay que acordar la
> normalización con el grupo.

## Reconstruir la proyección de reglas

`evt.partners` está compactado para poder reconstruir la proyección releyéndolo.
Pero `initial_position=Earliest` solo aplica a una suscripción **nueva**: si se
pierde la base y la suscripción sobrevive, su cursor ya está avanzado y no hay
replay. Para forzarla:

```bash
docker exec broker bin/pulsar-admin topics reset-cursor \
  persistent://hda/poc/evt.partners \
  --subscription orquestacion-trabajos-reglas --time 1d
```

Al reiniciar, el servicio rehace la proyección solo. El consumidor de reglas
**no** usa `mensajes_procesados` justamente para que ese replay funcione; ver
DECISIONES.md §4.

## Verificar las reglas duras

```bash
# cero condicionales por partner (solo debe haber comentarios)
grep -rn "if partner_id ==" src/

# el dominio no importa infraestructura
grep -rn "^from\|^import" src/orquestacion/dominio/*.py | grep -E "psycopg|pulsar|flask"

# nunca UPDATE ni DELETE sobre el event store
grep -rni "UPDATE eventos_trabajo\|DELETE FROM eventos_trabajo" src/
```

## Demo: los dos mecanismos de idempotencia

```bash
# REPETICION: el mismo sobre 3 veces -> se aplica 1, se descartan 2
./.venv/bin/python scripts/publicar.py ReglaDePartnerActualizada \
  --partner-id SEGUROS_ALFA --regla-version 9 --sla-minutos 45 --duplicar 3

# DESORDEN: una version vieja despues -> pasa la marca, la frena la guarda
./.venv/bin/python scripts/publicar.py ReglaDePartnerActualizada \
  --partner-id SEGUROS_ALFA --regla-version 4 --sla-minutos 999
```

## Herramientas

Los otros tres microservicios no siempre están levantados, así que cada mensaje
de entrada se puede simular a mano.

```bash
# publicar cualquier mensaje de entrada, con valores de ejemplo
./.venv/bin/python scripts/publicar.py ReglaDePartnerActualizada --partner-id SEGUROS_ANDES
./.venv/bin/python scripts/publicar.py CrearTrabajo --categoria PLOMERIA

# el MISMO sobre N veces, para probar idempotencia
./.venv/bin/python scripts/publicar.py CrearTrabajo --duplicar 3

# ver el sobre sin publicar
./.venv/bin/python scripts/publicar.py TrabajoAsignado --solo-mostrar

# mirilla sobre cualquier tópico (suscripción de nombre aleatorio: no le roba
# mensajes al consumidor real)
./.venv/bin/python scripts/escuchar.py evt.trabajos
./.venv/bin/python scripts/escuchar.py cmd.trabajos --desde-el-inicio --maximo 5
```

`publicar.py` firma los mensajes con un `service_name` **ajeno** a propósito
(`portal-aseguradora`, `motor-reglas-partner`, …). Si firmara como
`orquestacion-trabajos`, el filtro anti-ciclo de `evt.trabajos` los descartaría.

## Mensajería

Namespace `persistent://hda/poc`. Tópico **por agregado**, no por tipo de
mensaje: el consumidor discrimina por el campo `type` del sobre.

**Consume**

| Tópico | Mensaje | Particiones | Suscripción |
|---|---|---|---|
| `cmd.trabajos` | `CrearTrabajo` | 3 | Failover |
| `evt.partners` | `ReglaDePartnerActualizada` | 0, compactado | **Failover** (ver abajo) |
| `evt.trabajos` | `TrabajoAsignado` | 3 | Key_Shared |
| `evt.asignaciones` | `AsignacionRechazadaPorHabilitacion` | 3 | Shared |

**Publica**

| Tópico | Mensajes | Clave |
|---|---|---|
| `evt.trabajos` | `TrabajoCreado`, `TrabajoRechazado` | `trabajo_id` |
| `cmd.emparejamiento` | `AsignarProveedor` | `trabajo_id` |

Todo se publica con `BytesSchema`, nunca con `AvroSchema`: `evt.trabajos` lleva
tres tipos y Pulsar registra un solo esquema por tópico.

### Por qué `evt.partners` usa Failover y no Shared

El diseño inicial decía `Shared`, pero Pulsar **rechaza `read_compacted` sobre
una suscripción `Shared`** (`InvalidConfiguration`, verificado contra el broker).
Y sin `read_compacted` la compactación del tópico no sirve de nada: un arranque
en frío tendría que releer el histórico entero en vez de la última regla por
partner.

Con `Failover` + `read_compacted` + `Earliest`, una réplica nueva o una base
recién creada **reconstruye sola** la proyección de reglas. No se pierde
escalabilidad: el tópico no está particionado y los cambios de regla son
administrativos y raros, así que no hay volumen que repartir.

## Deudas y pendientes con el grupo

| # | Tema |
|---|---|
| 1 | **Ciclo en `evt.trabajos`**: Emparejamiento publica en el tópico de *nuestro* agregado y no existe `ProveedorAsignado`, así que consumimos nuestro propio tópico. Mitigado descartando los sobres con `service_name` propio. Pedir que publique también en `evt.asignaciones`. |
| 2 | Nadie consume `cmd.emparejamiento` (Emparejamiento lo declara "no se consume (E5)"). La reasignación se implementa igual, pero la demo de punta a punta se corta ahí. |
| 3 | `monto` es `long` en el contrato. Se asume **unidades enteras** de la moneda. Si fueran centavos, todo monto queda 100×. |
| 4 | `motor-reglas-partner` publica en `eventos-partner` y consume `comandos-partner`, pero el script de tópicos crea `evt.partners` y `cmd.partners`. **Los nombres no coinciden**: hay que alinearlos o ese servicio no se comunica con nadie. |
| 5 | `cmd.trabajos` tiene retención infinita y conserva `CrearTrabajo` en **JSON** de antes de que saliera el `.avsc`. La costura los acepta al leer; este servicio solo emite Avro. |
