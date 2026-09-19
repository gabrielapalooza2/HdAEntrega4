# Hogar de los Alpes, entrega 4

Cuatro microservicios coordinan el ciclo de respuesta de un siniestro. Cada servicio tiene su propia base PostgreSQL. Toda comunicación entre servicios pasa por un cluster Apache Pulsar en el namespace `persistent://hda/poc`. Ningún microservicio llama a otro por HTTP.

Este archivo es la entrada al monorepo. Dice cómo levantar el sistema, qué hay en cada carpeta, y cómo probar los escenarios de calidad que el código ya demuestra.

## Qué necesitas

- Docker Desktop con Compose v2
- Git Bash o WSL para los scripts `.sh` y para `make`
- Python 3.11 o 3.12 solo si corres pruebas o demos fuera del contenedor
- Postman si quieres recorrer el flujo HTTP de emparejamiento

En PowerShell nativo usa los comandos `docker compose` de abajo. `make` y `scripts/crear_topicos.sh` esperan un shell Unix.

## Cómo desplegar

Trabaja siempre desde la raíz del repositorio. El cluster no es `pulsar standalone`. `docker-compose.yml` arranca ZooKeeper, un bookie y un broker, que es lo que la rúbrica pide como cluster.

### 1. Infraestructura

```bash
docker compose up -d zookeeper pulsar-init bookie broker db-trabajos db-partners db-emparejamiento db-acreditacion
```

El `Makefile` estima unos 40 s la primera vez, hasta que el healthcheck del broker pase.

```bash
docker exec broker bin/pulsar-admin brokers healthcheck
```

Cuando el comando responde sin error, sigue.

Si tienes Make, el mismo paso es `make infra`.

### 2. Tópicos

Corre `scripts/crear_topicos.sh` antes de levantar los microservicios. El script es idempotente. Puedes lanzarlo otra vez sin romper nada. Crea el tenant `hda`, el namespace `hda/poc`, retención infinita, compatibilidad de esquemas `BACKWARD`, y estos tópicos.

| Tópico | Forma | Para qué |
|---|---|---|
| `cmd.trabajos` | 3 particiones | comando `CrearTrabajo` |
| `cmd.emparejamiento` | 3 particiones | comando `AsignarProveedor` |
| `cmd.partners` | 1 partición | `RegistrarPartner`, `ActualizarReglaDePartner` |
| `cmd.proveedores` | 1 partición | `AcreditarProveedor`, `SuspenderProveedor` |
| `evt.trabajos` | 3 particiones | `TrabajoCreado`, `TrabajoRechazado`, `TrabajoAsignado` |
| `evt.asignaciones` | 3 particiones | `AsignacionRechazadaPorHabilitacion` |
| `evt.partners` | compactado, sin particionar | carga de estado de la regla del partner |
| `evt.proveedores` | compactado, sin particionar | carga de estado de habilitación |

```bash
# Git Bash o WSL
./scripts/crear_topicos.sh
```

Con Make, el mismo paso es `make topicos`.

Los tópicos compactados no se particionan. La compactación de Pulsar conserva el último mensaje por clave **dentro de cada partición**. Varias particiones darían una vista parcial al reconstruir una proyección en frío.

### 3. Microservicios

```bash
docker compose up -d --build orquestacion-trabajos motor-reglas-partner emparejamiento-asignacion acreditacion-habilitacion
```

Con Make, el mismo paso es `make servicios`. Los tres pasos juntos son `make todo`.

### 4. Comprobar que está arriba

```bash
docker compose ps
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:8000/health
curl http://localhost:5004/health
curl http://localhost:8080/admin/v2/brokers/health
```

Puertos en el host.

| Qué | Host | Dentro del contenedor |
|---|---|---|
| Orquestación de trabajos | 5001 | 5000 |
| Motor reglas partner | 5002 | 5000 |
| Emparejamiento y asignación | 8000 | 8000 |
| Acreditación y habilitación | 5004 | 5000 |
| Pulsar broker, binario | 6650 | 6650 |
| Pulsar admin HTTP | 8080 | 8080 |
| Postgres de trabajos | 5432 | 5432 |
| Postgres de partners | 5433 | 5432 |
| Postgres de emparejamiento | 5434 | 5432 |
| Postgres de acreditación | 5435 | 5432 |

Las HTTP de los microservicios son para un operador, un BFF o una demostración. No son el canal entre servicios.

### Bajar y limpiar

```bash
docker compose down          # para los contenedores y deja los datos
```

`make limpiar` borra también `data/`. Úsalo solo si quieres un cluster en blanco. Vuelve a crear tópicos después.

## Estructura del proyecto

```
HdAEntrega4/
  docker-compose.yml          cluster Pulsar, 4 Postgres, 4 servicios
  Makefile                    atajos infra, topicos, servicios, demos
  contratos/                  fuente de verdad de los 12 mensajes Avro
    generar.py                regenera los .avsc versionados
    esquemas/                 un .avsc por tipo de mensaje
  scripts/
    crear_topicos.sh          tenant, namespace, tópicos, retención
    logs-pulsar.ps1           logs de ZooKeeper, bookie y broker
    logs-servicios.ps1        logs de microservicios y Postgres
  postman/                    colección y environment locales
  servicios/
    motor-reglas-partner/     dueño del agregado Partner y de su regla
    orquestacion-trabajos/    dueño del agregado Trabajo, event store + CQRS
    emparejamiento-asignacion dueño de la Asignación, matching local
    acreditacion-habilitacion dueño del Proveedor y de su habilitación
```

`contratos/generar.py` define los 12 mensajes. Cada servicio copia solo los Records que produce o consume. No importes `generar.py` desde un servicio. El único acoplamiento que debe existir es el esquema registrado en el broker.

Cada servicio monta `./contratos` como `/app/contratos:ro`. Emparejamiento trae también una copia en `servicios/emparejamiento-asignacion/contratos/esquemas/` para poder correr aislado.

## Qué hace cada servicio

Los cuatro siguen la misma idea. El dominio no importa Pulsar ni SQL. La variabilidad de negocio vive como dato en proyecciones locales. HTTP no cruza la frontera entre servicios.

```
área comercial / BFF
        | HTTP, solo borde
        v
Motor reglas  --evt.partners-->  proyección en Orquestación
                           \-->  proyección en Emparejamiento

CrearTrabajo  --cmd.trabajos-->  Orquestación
                                    | lee regla LOCAL
                                    | evt.trabajos  TrabajoCreado o TrabajoRechazado
                                    v
                              Emparejamiento
                                    | matching LOCAL
                                    | evt.trabajos  TrabajoAsignado
                                    v
                              Acreditación
                                    | dato autoritativo del proveedor
                                    | rechazo si no está habilitado
```

### Motor reglas partner

El servicio vive en `servicios/motor-reglas-partner` y corre Flask. Es el dueño del agregado Partner y de su regla. Registrar un partner o cambiarle la cobertura es un acto administrativo. No crea trabajos.

Consume `cmd.partners` con suscripción Shared. Publica `ReglaDePartnerActualizada` en `evt.partners` con la regla completa, no un aviso. El outbox encola el evento en la misma transacción que la fila.

HTTP en `http://localhost:5002`.

| Método | Ruta | Efecto |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/partners` | registra, 202 |
| GET | `/partners` | lista. `?activos=true` filtra |
| GET | `/partners/{id}` | consulta |
| PUT | `/partners/{id}/regla` | nueva versión de la regla, 202 |

Un `id` que no es UUID en el PUT responde 400.

Detalle del dominio y de las demos. `servicios/motor-reglas-partner/scripts/`.

### Orquestación de trabajos

El servicio vive en `servicios/orquestacion-trabajos` y corre Flask. Es el dueño del agregado Trabajo. El event store append-only está en PostgreSQL. Pulsar es transporte, no la historia del agregado.

Al crear un trabajo lee `proyeccion_regla_partner`. Si Motor reglas está caído, sigue operando con la última regla conocida. El SLA, la versión de la regla y `vence_en` se copian al evento de dominio y quedan congelados. Cambiar la regla después no mueve esos valores.

Si Emparejamiento no responde, un barrido cada 30 s escala los trabajos vencidos. Los eventos no reportan silencio.

HTTP en `http://localhost:5001`.

| Método | Ruta | Efecto |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/trabajos/{id}/estado` | lado Q de CQRS. Header `X-Proyeccion-Secuencia` |

El Dockerfile usa un solo worker de gunicorn. El relay del outbox, los consumidores y el barrido son hilos del mismo proceso. Para escalar se suben réplicas del contenedor, no workers.

Guía local y decisiones. `servicios/orquestacion-trabajos/README.md` y `servicios/orquestacion-trabajos/DECISIONES.md`.

### Emparejamiento y asignación

El servicio vive en `servicios/emparejamiento-asignacion` y corre FastAPI. Hidrata proyecciones desde `evt.partners` y `evt.proveedores`. Reacciona a `TrabajoCreado`. Asigna contra dato local. Publica `TrabajoAsignado` en `evt.trabajos`.

No consume `cmd.emparejamiento`. Un test, `tests/test_sin_asignar_proveedor.py`, exige que esa cadena no aparezca en el código. Ante `AsignacionRechazadaPorHabilitacion` marca `RECHAZADO` y no reasigna.

Matching. proveedor `HABILITADO`, categoría, ciudad exacta, vigencia, y `red_homologada` si no está vacía. La ciudad no se normaliza. `"Bogota"` y `"BOGOTA"` no coinciden.

HTTP en `http://localhost:8000`.

| Método | Ruta | Efecto |
|---|---|---|
| GET | `/health` | estado y conteo de proyecciones |
| GET | `/health/ok` | texto `ok` |
| GET | `/asignaciones/{trabajo_id}` | asignación persistida |
| POST | `/demo/flujo/preparar` | arnés. publica regla y habilitaciones de demo |
| POST | `/demo/flujo/trabajo-creado` | arnés. publica un `TrabajoCreado` y espera `ASIGNADO` |
| POST | `/demo/flujo/rechazo` | arnés. publica un rechazo y espera `RECHAZADO` |

`/demo/flujo/*` no es API de negocio. Publica los mismos Avro que los otros servicios publicarían, para poder recorrer el flujo desde Postman con un solo proceso.

### Acreditación y habilitación

El servicio vive en `servicios/acreditacion-habilitacion` y corre Flask. Es el dueño del agregado Proveedor. Consume `cmd.proveedores` y `TrabajoAsignado` en `evt.trabajos`. Si el proveedor no está disponible, publica `AsignacionRechazadaPorHabilitacion`.

El circuit breaker de `infraestructura/verificacion_externa.py` cubre la consulta a Policía Nacional. Es un stub con latencia. No llama a un sistema real. `fail_max=3`, `reset_timeout=30`. Si el circuito abre, sirve desde cache. Si no hay cache, responde 503.

HTTP en `http://localhost:5004`.

| Método | Ruta | Efecto |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/proveedores` | acreditar por HTTP de laboratorio |
| PATCH | `/proveedores/{id}/suspender` | suspende y publica el cambio de estado |
| GET | `/proveedores/{id}/habilitacion` | consulta de back-office |
| POST | `/proveedores/{id}/verificar-antecedentes` | demo del circuit breaker |
| POST | `/admin/simular-falla-policia` | `{"activa": true}` fuerza timeout en el stub |

El código de Acreditación publica el rechazo en `persistent://hda/poc/evt.habilitaciones`. Orquestación y Emparejamiento lo leen de `evt.asignaciones`, que es el tópico del contrato en `contratos/esquemas/`. `scripts/crear_topicos.sh` no crea `evt.habilitaciones`. Si la demo de rechazo no cierra de punta a punta, mira esa divergencia primero.

## Contratos y mensajería

Sobre común, CloudEvents. Ocho campos se repiten en cada Record. `pulsar.schema.Record` no serializa campos heredados.

`id`, `time`, `ingestion`, `specversion`, `type`, `datacontenttype`, `service_name`, `correlation_id`, más `data`.

Tópico por agregado, no por tipo. `evt.trabajos` lleva tres Records. Pulsar registra un esquema por tópico, así que ese tópico viaja como bytes Avro y el consumidor discrimina por `type`.

Para regenerar los `.avsc` después de editar `generar.py`.

```bash
python contratos/generar.py
```

## Escenarios de calidad a probar

Los escenarios ya tienen script o test. La medida está en el código, no en una narrativa aparte.

### Modificabilidad. incorporar un partner sin redesplegar dominio

**Estímulo.** el área comercial registra un partner nuevo, por ejemplo el 31, con su cobertura y su SLA.

**Respuesta esperada.** Orquestación resuelve un trabajo de ese partner con *su* regla. Un trabajo de una categoría fuera de cobertura se rechaza. Cero `if partner_id == ...` en dominio y aplicación. Ninguna imagen Docker cambia.

**Por qué funciona.** la variabilidad es una fila y un evento con carga de estado, no un condicional.

Con el stack arriba, desde Git Bash o WSL.

```bash
./servicios/motor-reglas-partner/scripts/demo_flujo_completo.sh
```

Esa corrida registra el partner, espera a `evt.partners`, manda un trabajo de `PLOMERIA` y uno de `CARPINTERIA`, y cuenta condicionales e imágenes.

`make demo-modificabilidad` corre la demo corta `servicios/motor-reglas-partner/scripts/demo_esc6.sh`.

Pruebas que cubren la misma invariante sin cluster.

```bash
cd servicios/orquestacion-trabajos
PYTHONPATH=src python -m pytest tests/test_dominio.py tests/test_integracion.py -q
cd ../emparejamiento-asignacion
PYTHONPATH=. python -m pytest tests/test_sin_switch_partner.py -q
cd ../motor-reglas-partner
PYTHONPATH=src python -m pytest tests/test_dominio_partner.py -q
```

Qué debes ver en la demo completa.

1. `POST /partners` responde 202 y un UUID.
2. La fila en `db-partners` tiene `sla_minutos=120` y cobertura `PLOMERIA`, `ELECTRICIDAD`.
3. El `TrabajoCreado` de plomería sale con SLA 120.
4. El de carpintería sale `TrabajoRechazado`.
5. `docker ps` no muestra imágenes nuevas.

### Disponibilidad. Motor reglas caído, el flujo operativo sigue

**Estímulo.** detienes `motor-reglas-partner` después de que las reglas ya viajaron a `evt.partners`.

**Respuesta esperada.** Orquestación y Emparejamiento siguen resolviendo con la proyección local. Un consumidor nuevo reconstruye el estado leyendo el tópico compactado desde el inicio.

```bash
./servicios/motor-reglas-partner/scripts/demo_disponibilidad.sh
```

El script para el contenedor, te deja disparar carga a mano, y al Enter lo vuelve a levantar. El outbox drena lo pendiente al volver.

Prueba de unidad del mismo criterio. `test_partner_desconocido_no_llama_a_nadie_y_rechaza` en `servicios/orquestacion-trabajos/tests/test_integracion.py`. Sin regla local no hay llamada de red. Se rechaza con `PARTNER_DESCONOCIDO`.

### Escalabilidad. el pico son trabajos, no partners

**Estímulo.** rampa de `CrearTrabajo` sobre `cmd.trabajos`. El enunciado habla de 12.000 trabajos al día, proyección 36.000, picos 4x en 48 horas. Incorporar un partner ocurre unas treinta veces en la historia de la empresa. Inyectar partners a 200 por segundo no mide el negocio.

**Respuesta esperada.** `cmd.trabajos` absorbe el pico. El backlog de `cmd.partners` permanece en cero. Motor reglas no está en el camino crítico de cada trabajo, porque la regla ya vive en la proyección del consumidor.

```bash
make demo-escalabilidad
```

A mano, desde `servicios/motor-reglas-partner`, con Motor reglas y Orquestación arriba.

```bash
python scripts/semilla_partners.py --cantidad 30 --api http://localhost:5002
python scripts/carga_escalabilidad.py --rps 10 50 200 --segundos 30
docker exec broker bin/pulsar-admin topics stats persistent://hda/poc/cmd.trabajos
docker exec broker bin/pulsar-admin topics stats persistent://hda/poc/cmd.partners
```

Mira `msgBacklog` y el throughput. El tópico administrativo no debe moverse durante la rampa operativa.

Para escalar un servicio, sube réplicas del contenedor. No subas workers de gunicorn. Los Dockerfiles de Orquestación y Motor reglas lo dejan escrito. Varios workers competirían por las mismas filas del outbox.

### Dependencia externa. circuit breaker y cache

**Estímulo.** Acreditación consulta Policía Nacional y esa fuente deja de responder.

**Respuesta esperada.** tras 3 fallos el circuito abre. Las siguientes consultas salen de cache. Si no hay cache, HTTP 503. Al cerrar el circuito, el stub vuelve a responder.

```bash
# 1. acredita un proveedor
curl -sS -X POST http://localhost:5004/proveedores \
  -H "Content-Type: application/json" \
  -d "{\"proveedor_id\":\"prov-demo\",\"nombre\":\"Demo\",\"categorias\":[\"PLOMERIA\"],\"ciudades\":[\"Bogota\"]}"

# 2. primera verificación, llena cache, desde_cache=false
curl -sS -X POST http://localhost:5004/proveedores/prov-demo/verificar-antecedentes \
  -H "Content-Type: application/json" \
  -d "{\"fuente\":\"policia_nacional\"}"

# 3. fuerza timeout en el stub
curl -sS -X POST http://localhost:5004/admin/simular-falla-policia \
  -H "Content-Type: application/json" \
  -d "{\"activa\":true}"

# 4. tres llamadas más abren el circuito. las siguientes deben servir cache
curl -sS -X POST http://localhost:5004/proveedores/prov-demo/verificar-antecedentes \
  -H "Content-Type: application/json" \
  -d "{\"fuente\":\"policia_nacional\"}"
```

En la respuesta mira `desde_cache` y `latencia_ms`. Apaga la falla con `{"activa": false}` cuando termines.

### SLA congelado y reasignación acotada

No hay un script de demo único. Las pruebas de Orquestación cubren el comportamiento.

- Cambiar la regla no altera un trabajo ya creado. `test_cambiar_la_regla_no_toca_el_trabajo_ya_creado`.
- Tres rechazos de habilitación. el tercero escala. Tope `MAX_INTENTOS_ASIGNACION=3`.
- El barrido pasa a `ESCALADO_MANUAL` cuando vence el SLA y el estado no es terminal.

Orquestación publica `AsignarProveedor` en `cmd.emparejamiento`. Emparejamiento no lo consume. La rama de reasignación no cierra de punta a punta hasta que ese comando tenga dueño. El camino feliz sí cierra. `CrearTrabajo` → `TrabajoCreado` → matching → `TrabajoAsignado` → estado `ASIGNADO`.

## Cómo correr las pruebas

Desde la raíz, con Make y Python en el PATH.

```bash
make pruebas
```

El target entra a cada carpeta de `servicios/` y corre `pytest`. Acreditación no tiene carpeta `tests/`. Ese directorio imprime `sin pruebas`.

A mano.

```bash
cd servicios/orquestacion-trabajos && PYTHONPATH=src python -m pytest tests -q
cd servicios/motor-reglas-partner && PYTHONPATH=src python -m pytest tests -q
cd servicios/emparejamiento-asignacion && PYTHONPATH=. python -m pytest tests -q
```

Las pruebas de Orquestación que tocan PostgreSQL se saltan solas si no hay base. Las de costura Avro no necesitan broker.

## Postman

Importa `postman/HdA-Entrega4.postman_collection.json` y `postman/HdA-Entrega4.postman_environment.json`.

El environment apunta a `http://localhost:8000`, `http://localhost:5002` y `http://localhost:8080`.

Carpetas.

- Flujo completo de emparejamiento. health, carga de estado, `TrabajoCreado`, GET asignación, rechazo
- Salud
- Consultas sueltas
- Motor reglas partner. listar, registrar, GET, PUT regla
- Pulsar. health del broker, clusters, tópicos particionados

Corre la carpeta de flujo con Collection Runner después de `make todo`. Los POST `/demo/flujo/*` hidratan proyecciones publicando Avro. Emparejamiento no llama a Motor reglas ni a Acreditación por HTTP.

## Logs

PowerShell, desde la raíz.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\logs-servicios.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\logs-pulsar.ps1
```

Con Make. `make logs` sigue los cuatro microservicios. `make estado` lista el compose.

Para inspeccionar un tópico sin robarle mensajes al consumidor real, Orquestación trae `servicios/orquestacion-trabajos/scripts/escuchar.py`. Usa una suscripción de nombre aleatorio.

## Credenciales locales

Son de laboratorio. Están en `docker-compose.yml`. No las uses fuera de esta máquina.

| Base | Usuario | Clave | Base |
|---|---|---|---|
| `db-trabajos` | `trabajos` | `trabajos` | `trabajos` |
| `db-partners` | `partners` | `partners` | `partners` |
| `db-emparejamiento` | `emparejamiento` | `emparejamiento` | `emparejamiento` |
| `db-acreditacion` | `acreditacion` | `acreditacion` | `acreditacion` |

## Lectura por servicio

Cuando ya tienes el sistema arriba y quieres el *por qué* de una decisión, entra al README del servicio, no copies este archivo.

- Orquestación, operación y deudas. `servicios/orquestacion-trabajos/README.md`
- Orquestación, diecisiete decisiones. `servicios/orquestacion-trabajos/DECISIONES.md`
- Emparejamiento, hexágono y matching. `servicios/emparejamiento-asignacion/README.md`
