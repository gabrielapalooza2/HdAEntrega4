# Decisiones de arquitectura — Orquestación de Trabajos

Cada decisión con su *por qué* y lo que costó. Están ordenadas de más a menos
estructural.

---

## 1. El event store vive en PostgreSQL, no en Pulsar

**Decisión.** `eventos_trabajo` es la fuente de verdad. Pulsar es transporte.

**Por qué.** El namespace tiene retención infinita, así que en teoría los eventos
ya estarían en el broker. Pero **un tópico retenido no se puede consultar por
agregado**: para reconstruir un trabajo habría que leer el tópico entero
filtrando por `trabajo_id`. La retención de Pulsar cubre el rezago de un
consumidor, no la historia de una entidad.

**Tradeoff.** Dos almacenes que mantener en sincronía, y ese es justamente el
problema que obliga al patrón outbox (§3).

---

## 2. La PK compuesta **es** el control de concurrencia optimista

**Decisión.** `PRIMARY KEY (trabajo_id, secuencia)`. Sin locks, sin
`SELECT FOR UPDATE`.

**Por qué.** Dos escrituras simultáneas sobre el mismo trabajo leen la misma
`secuencia` y calculan la misma siguiente. Las dos intentan insertar la misma
clave y la restricción rechaza a la segunda, que recibe `ConflictoDeConcurrencia`
y vuelve a leer. El conflicto se **detecta al escribir** en vez de
**prevenirse bloqueando**: eso es lo que significa "optimista".

**Por qué sin ORM.** Un ORM mete una sesión con caché de identidad entre el
código y el `INSERT`, y oscurece exactamente el momento en que la escritura
choca. Con SQL crudo, atrapar `psycopg.errors.UniqueViolation` es una línea y se
ve.

**Tradeoff.** Bajo contención alta sobre un mismo agregado habría muchos
reintentos. Aquí no importa: los eventos de un trabajo llegan por `Key_Shared`,
así que un mismo `trabajo_id` cae siempre en el mismo consumidor y la contención
real es casi nula.

---

## 3. Patrón outbox: el evento y el mensaje en la misma transacción

**Decisión.** Nunca se publica desde el camino de escritura. Se **encola** una
fila en la misma transacción y un hilo aparte la drena.

**Por qué.** PostgreSQL y Pulsar no comparten transacción. Publicar primero
dejaría mensajes que anuncian cambios que no ocurrieron; guardar primero dejaría
trabajos de los que nadie se entera. El `COMMIT` es lo que hace que el mensaje
exista.

**`payload` es `BYTEA`, no `JSONB`.** Guarda los bytes Avro **ya codificados**,
para que el relay no vuelva a codificar ni conozca los contratos: solo mueve
bytes a un tópico. La costura sigue siendo el único módulo que sabe serializar.

**Tradeoff.** La garantía es **al menos una vez**: si el relay publica y muere
antes de marcar la fila, republica al reiniciar. Por eso todo consumidor del
sistema es idempotente. Y agrega latencia: el mensaje sale hasta 1 s después del
commit.

---

## 4. Dos mecanismos de idempotencia, porque son dos problemas distintos

| Mecanismo | Protege contra | Cómo |
|---|---|---|
| `mensajes_procesados` | **repetición** — el mismo mensaje dos veces | `INSERT ... ON CONFLICT DO NOTHING`, en la misma transacción que el efecto |
| guarda de versión | **desorden** — un mensaje viejo llegando tarde | `WHERE proyeccion.version < EXCLUDED.version` |

**Por qué hacen falta los dos.** Una versión vieja reentregada llega en un sobre
**distinto**, con `id` distinto: pasa la marca de idempotencia sin problema. Lo
único que la frena es la versión. Y al revés: dos copias del mismo sobre traen la
misma versión, así que la guarda no las distingue.

**Por qué un solo `INSERT` y no `SELECT` + `INSERT`.** Entre verificar y marcar
habría una ventana por la que dos hilos o dos réplicas se cuelan los dos. Así la
carrera la resuelve la restricción de unicidad dentro del motor.

**Detalle.** El contrato declara `id` como `string`, no como UUID. Un id
malformado reventaría al insertarlo en una columna UUID → `negative_acknowledge`
→ reentrega infinita: **un mensaje venenoso en bucle**. Se deriva un `uuid5`
determinista del texto, que conserva la idempotencia sin perder el mensaje.

### Dónde NO se usa `mensajes_procesados`, y por qué

El consumidor de `evt.partners` **no marca los sobres**. Es una decisión, no un
olvido, y salió de un fallo observado al probar los dos servicios juntos.

La marca por id de mensaje protege **efectos que no son idempotentes por sí
mismos**: crear un trabajo dos veces crea dos trabajos. Pero la proyección de
reglas es una **proyección pura con guarda de versión**: aplicar la misma regla
dos veces da exactamente el mismo resultado, porque la guarda convierte la
repetición en un no-op. La marca no agrega ninguna seguridad.

Y sí hace daño. `evt.partners` está compactado precisamente para que una réplica
nueva —o una base restaurada— pueda **reconstruir** la proyección releyendo el
tópico desde el inicio. Con la marca puesta, ese replay se descartaría entero
como "ya procesado" y la proyección quedaría **vacía**: la idempotencia habría
bloqueado la reconstrucción.

> **Regla:** idempotencia por **versión** donde el estado converge; idempotencia
> por **id de mensaje** solo donde el efecto no es repetible.

**Salvedad operativa.** `initial_position=Earliest` solo aplica a una suscripción
**nueva**. Si se pierde la base pero la suscripción sobrevive, su cursor ya está
avanzado y no hay replay. Para forzar la reconstrucción:

```bash
docker exec broker bin/pulsar-admin topics reset-cursor \
  persistent://hda/poc/evt.partners \
  --subscription orquestacion-trabajos-reglas --time 1d
```

---

## 5. El congelamiento del SLA ocurre en el event store, no en el cable

**Decisión.** `sla_minutos`, `regla_version` y `vence_en` se copian de la regla
vigente al crear y quedan en el payload del evento de dominio. El evento de
integración **no los lleva**, porque el contrato del grupo no tiene esos campos.

**Por qué no lo rompe.** El event store es append-only: no hay `UPDATE` ni
`DELETE` sobre `eventos_trabajo` en ninguna parte del código (hay una prueba que
lo verifica recorriendo los fuentes). Cambiar la regla mañana **no puede** mover
ese valor. No es que no queramos: es que no se puede.

**Es la distinción entre evento de dominio y evento de integración.** El de
dominio es el hecho completo, en vocabulario propio, y es solo nuestro. El de
integración es una **proyección** de ese hecho, recortada a lo que el contrato
ajeno admite.

**Continuidad con HDA-004.** El modelo táctico de la entrega anterior ya
declaraba la intención en `AcuerdoDeServicio`: *"queda congelado: cambiar la
política no debe alterar acuerdos vigentes"*. Lo que agrega esta entrega es que
el congelamiento pasa de **intención** a **garantía verificable**.

---

## 6. Cero condicionales por partner: la variabilidad es dato

**Decisión.** No existe ningún `if partner_id == ...` ni `switch` por partner.
Toda la variabilidad entre aseguradoras entra por `evt.partners` y vive en
`proyeccion_regla_partner`.

**Por qué.** Es el escenario de **modificabilidad**: agregar una aseguradora o
cambiarle la cobertura es publicar un evento, no editar y redesplegar código.

**Evolución respecto de HDA-004.** Allá el SLA salía de `Urgencia.horas_sla()`,
un diccionario `{BAJA: 72, ALTA: 8, ...}` **cableado en el código**. Ese método
se eliminó: dejarlo sería tener dos fuentes de verdad para el mismo número. Por
la misma razón se quitó el `CATALOGO` cerrado de `CategoriaDeServicio`: qué
categorías existen lo dice la regla del partner, no una constante nuestra.

---

## 7. Leer la proyección local en vez de llamar al Motor de Reglas

**Decisión.** Validar un trabajo lee una tabla local. Ninguna llamada de red a
otro microservicio, ni HTTP ni gRPC.

**Por qué.** Es el escenario de **disponibilidad**. Si Motor de Reglas está
caído, aquí sigue estando la última regla conocida y Orquestación sigue operando.
Una llamada síncrona habría acoplado la disponibilidad de los dos servicios.

**Tradeoff.** Consistencia eventual: durante unos milisegundos podemos decidir
con una regla vieja. Aceptable, y de todos modos el trabajo se evalúa con la
regla vigente **en su momento de creación**, que es precisamente lo que §5
congela.

---

## 8. `BytesSchema` y no `AvroSchema`

**Decisión.** Se codifica Avro a mano con `fastavro` y se publica como bytes
crudos.

**Por qué.** `evt.trabajos` lleva **tres** tipos (`TrabajoCreado`,
`TrabajoRechazado`, `TrabajoAsignado`) y Pulsar registra **un solo esquema por
tópico**: ninguna política de compatibilidad admite los tres a la vez.

**Cómo discrimina el consumidor.** El sobre es un **prefijo posicional** idéntico
en los siete esquemas, y Avro binario no lleva nombres de campo en el cable. Así
que se lee solo el prefijo con un esquema de ocho campos, se mira `type`, y recién
entonces se decodifica entero con el esquema correcto. El discriminador viaja
dentro del propio mensaje.

**Tradeoff.** Se pierde la validación de esquema que el broker haría por
nosotros. A cambio, un tópico por agregado en vez de uno por tipo de mensaje.

---

## 9. Toda la traducción en un solo módulo

**Decisión.** `mensajeria/contratos.py` es la única costura. Ningún otro archivo
construye un mensaje, conoce los nombres del contrato ajeno ni sabe en qué tópico
va nada.

| Adentro | Afuera |
|---|---|
| `zona` | `ciudad` |
| `regla_version` | `version_regla` |
| `categorias_cubiertas` | `cobertura_contratada` |
| `monto_max` + `moneda` | `monto_maximo_sin_aprobacion{monto, moneda}` |
| `proveedores_excluidos` | `excluir_proveedores` |
| `vence_en` | `sla_vence_en` (long de ms) |

**Por qué.** Es literalmente el patrón *capa anticorrupción*: el dominio no se
deforma para parecerse al contrato ajeno, y el contrato ajeno puede cambiar sin
tocar el dominio. Se verifica con `grep`: si en `dominio/` o `aplicacion/`
apareciera `cobertura_contratada`, la capa se rompió.

**Se usa `fastavro` y no `pulsar.schema`** para que la costura sea lógica pura:
sus 14 pruebas corren sin broker ni base de datos.

---

## 10. Liberal al recibir, estricto al emitir

**Decisión.** El decodificador acepta JSON además de Avro. El codificador emite
**solo** Avro.

**Por qué.** `cmd.trabajos` tiene retención infinita y conserva `CrearTrabajo` en
JSON de antes de que el grupo publicara el `.avsc`. Un consumidor que lea desde
el inicio los va a encontrar, y dejarlos caer en silencio sería perder comandos
reales.

---

## 11. El `trabajo_id` lo genera este servicio, derivado del sobre

**Decisión.** `trabajo_id = uuid5(namespace_propio, sobre.id)`.

**Por qué.** El contrato del grupo **no trae `trabajo_id`** en el payload de
`CrearTrabajo`. La identidad del agregado la genera su dueño. Se **deriva** del
`id` del sobre en vez de sortear un `uuid4` para que el mismo comando apunte
siempre al mismo agregado: así la PK del event store es una **segunda línea de
defensa** contra duplicados, por si `mensajes_procesados` fallara.

**Consecuencia que hay que saber.** Reenviar el mismo sobre no crea un segundo
trabajo. Enviar dos sobres distintos con contenido idéntico **sí** crea dos
trabajos — y es correcto: son dos siniestros.

---

## 12. `Failover` en `evt.partners`, desviándose del diseño inicial

**Decisión.** La especificación decía `Shared`. Se usa `Failover` con
`read_compacted`.

**Por qué.** Pulsar **rechaza** `read_compacted` sobre una suscripción `Shared`
(`InvalidConfiguration`; verificado contra el broker). Sin `read_compacted`, la
compactación del tópico no sirve de nada: un arranque en frío tendría que releer
el histórico entero en vez de la última regla por partner.

**Qué se gana.** Una réplica nueva o una base recién creada **reconstruye sola**
la proyección de reglas.

**Qué no se pierde.** El tópico no está particionado y los cambios de regla son
administrativos y raros: no hay volumen que repartir.

---

## 13. Consumir nuestro propio tópico — deuda aceptada

**Decisión.** Se consume `evt.trabajos`, que es nuestro tópico de salida,
descartando todo sobre con `service_name` propio.

**Por qué.** Emparejamiento publica `TrabajoAsignado` ahí y **no existe ningún
`ProveedorAsignado`** en otro tópico. Para enterarnos de una asignación no hay
otra forma.

**Por qué está mal.** El dueño de un agregado debería ser el único productor de
su tópico. Esto es un ciclo.

**Deuda registrada.** Pedir a Emparejamiento que publique también en
`evt.asignaciones` y mover el consumidor allí.

---

## 14. Un solo punto orquestado; todo lo demás es coreografía

**Decisión.** El reintento acotado ante `AsignacionRechazadaPorHabilitacion` es
el único lugar donde este servicio **manda un comando** en vez de publicar un
hecho.

**Por qué se orquesta ahí y solo ahí.** El reintento acotado necesita **memoria**
—cuántas veces ya se intentó— y esa memoria tiene que vivir en algún lado. Vive
en el agregado, que es su dueño natural. Todo lo demás es coreografía: cada
servicio reacciona a lo que ve y nadie dirige.

**`proveedores_excluidos` viaja en el comando** porque Emparejamiento no puede
leer nuestra base. En una arquitectura de eventos, el estado necesario para
decidir va **en el mensaje**.

---

## 15. El barrido de SLA, porque los eventos no reportan silencio

**Decisión.** Un hilo cada 30 s escala los trabajos vencidos en estado no
terminal.

**Por qué.** **Los eventos te dicen lo que pasó, nunca lo que NO pasó.** En
coreografía nadie espera: si Emparejamiento jamás responde, no llega ningún
mensaje que diga "no respondí", y sin el barrido el trabajo se queda quieto para
siempre. El paso del tiempo es el único estímulo que ningún broker puede
entregar.

**Detalle.** El barrido reevalúa contra el **event store**, no contra la
proyección: entre la consulta del lote y el momento de escalar pudo llegar la
asignación. La fuente de verdad manda.

**`ASIGNADO` detiene el reloj** porque el SLA es de **respuesta**, no de
ejecución.

---

## 16. El rezago de la proyección se expone, no se esconde

**Decisión.** `GET /trabajos/{id}/estado` devuelve
`X-Proyeccion-Secuencia: <n>`.

**Por qué.** En CQRS la proyección va **siempre** por detrás del event store,
aunque sea por milisegundos. Exponer hasta qué evento refleja la respuesta hace
ese rezago observable: quien consulta puede saber si está viendo un estado viejo.

---

## 17. Alcance recortado respecto de HDA-004

**Decisión.** Se conservan los nombres del modelo táctico ya sustentado
(`Urgencia`, `CategoriaDeServicio`, `AcuerdoDeServicio`) y se dejan fuera
`Diagnostico`, `Novedad`, `Ejecucion`, `VentanaDeAtencion` y `Canal`.

**Por qué.** Esta entrega modela el ciclo de **respuesta**, que es el que la
coreografía entre microservicios recorre. El ciclo de **ejecución** de HDA-004
—diagnóstico, novedades, ejecución en sitio— no lo dispara ningún evento del
sistema hoy: portarlo sería superficie sin ejercitar.

Correspondencia de estados:

| HDA-004 | Esta entrega |
|---|---|
| `REGISTRADO` | `CREADO` |
| `ASIGNADO` | `ASIGNADO` |
| `CANCELADO` | `RECHAZADO` |
| — | `ESCALADO_MANUAL` (nuevo) |
| `EN_EJECUCION`, `COMPLETADO` | fuera de alcance |

---

## Pendientes con el grupo

| # | Tema | Impacto |
|---|---|---|
| 1 | **Nadie consume `cmd.emparejamiento`**. Emparejamiento tiene un test, `test_sin_asignar_proveedor.py`, que **exige** no consumirlo (`assert "cmd.emparejamiento" not in texto`). No es un olvido: es una decisión blindada. | La rama de **reasignación** publica al vacío. El camino principal sí cierra (ver abajo) |
| 1b | `candidatos_habilitados` de Emparejamiento compara ciudad con `in` exacto, sin normalizar: `"BOGOTA" != "Bogota"`. | Un trabajo válido puede quedar sin candidatos por diferencia de mayúsculas. Acordar la normalización |
| 2 | El ciclo de `evt.trabajos` (§13) | Mitigado, no resuelto |
| 3 | `monto` es `long` en el contrato: ¿unidades enteras o centavos? | Si son centavos, todo monto queda 100× |
| 4 | `motor-reglas-partner` publica en `eventos-partner` y consume `comandos-partner`; el script de tópicos crea `evt.partners` y `cmd.partners` | **Los nombres no coinciden**: ese servicio no se comunica con nadie |
| 5 | `emparejamiento-asignacion` y `acreditacion-habilitacion` están en el compose pero no existen en `servicios/` | `make servicios` falla |

Entrega 5 (saga): Acreditación publica confirmación y rechazo en
`evt.asignaciones`. El saga log es una proyección en `db-trabajos`, no un
quinto servicio. Detalle en `docs/entrega5/arquitectura-saga.md`.



---

## Integración verificada con Emparejamiento y Asignación

El camino principal **cierra de punta a punta**, en coreografía pura y sin que
ningún servicio llame a otro:

```
12:42:42,097  orquestacion-trabajos      CrearTrabajo -> TrabajoCreado
12:42:42,205  emparejamiento-asignacion  reacciona, asigna PROV_ALFA -> TrabajoAsignado
12:42:42,212  orquestacion-trabajos      consume el ajeno -> estado ASIGNADO
```

115 ms, el mismo `trabajo_id` en los tres pasos y el **mismo `correlation_id`**
propagado a través de los dos servicios.

Lo verificado en concreto:

- Nuestro Avro es legible por Emparejamiento: lee `ciudad`, `mercado_id`,
  `urgencia` y `sla_minutos` de nuestro `TrabajoCreado`.
- Su `service_name` es `emparejamiento-asignacion`, así que nuestro filtro
  anti-eco **no** lo descarta.
- Él ignora `TrabajoAsignado` y `TrabajoRechazado` por tipo, así que tampoco
  reacciona a su propio eco.
- Las dos proyecciones de reglas de partner convergen al mismo estado leyendo el
  mismo tópico compactado.

Lo que **no** cierra es la rama de reasignación (`AsignarProveedor` sobre
`cmd.emparejamiento`), por la deuda #1.
