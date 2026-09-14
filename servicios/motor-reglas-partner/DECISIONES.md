# Decisiones de diseño — Entrega 4

Hogar de los Alpes · Prueba de concepto de arquitectura orientada a eventos.

Este documento responde, una por una, las preguntas que el enunciado exige justificar. Cada
decisión trae **qué se decidió, por qué, qué se paga** y **dónde se ve en el código**, porque una
decisión sin precio declarado no es una decisión: es una preferencia.

---

## 0. Los dos flujos del sistema

Antes de los escenarios hay que dejar clara una distincion que es facil de mezclar y que
cambia por completo lo que se mide.

| | **Flujo A — Incorporar un partner** | **Flujo B — Ciclo de vida de un trabajo** |
|---|---|---|
| Naturaleza | **Administrativa**: configurar con quien trabajamos | **Operativa**: alguien necesita un plomero |
| Lo dispara | El area comercial, al firmar un convenio | Un dueno de hogar, o un partner reportando un siniestro |
| Frecuencia | ~30 veces en la historia de la empresa | 12.000/dia hoy · 36.000 proyectados · picos de 4x |
| Comando | `RegistrarPartner` → *Motor reglas partner* | `CrearTrabajo` → *Orquestacion de trabajos* |
| Efecto | Una fila y un evento con la regla completa | Un `Trabajo` y una `Asignacion` |
| Escenario que prueba | **Modificabilidad** | **Escalabilidad** y **disponibilidad** |

**Registrar un partner no crea ningun trabajo.** Son subdominios distintos, con volumenes que
difieren en cuatro ordenes de magnitud. En el modelo esto se ve en que `Partner` no conoce a
`Trabajo`, y `Trabajo` referencia `PartnerId` **por identidad**, nunca al reves.

La relacion entre los dos es de **precondicion, no de secuencia**: cuando llega el primer trabajo
del partner 31, su regla ya esta en la proyeccion local de *Orquestacion*. Y lo decisivo es lo que
**no** ocurre: el flujo B nunca llama al flujo A. Esa ausencia de llamada es la propiedad que
sostiene los tres escenarios, y es la razon por la que un servicio de baja frecuencia como este
jamas aparece en el camino critico de 36.000 trabajos diarios.

Consecuencia practica para la experimentacion, y es donde es facil equivocarse: **la carga se
inyecta sobre `comandos-trabajos`, no sobre `comandos-partner`.** Inyectar 200 partners por
segundo no mide nada del negocio; mide el broker. Los partners se siembran una vez
(`scripts/semilla_partners.py`) y despues se genera volumen de trabajos.

---

## 0.1 Los tres escenarios de calidad que se prueban

El enunciado pide validar un escenario por cada atributo definido en las entregas anteriores.
Los tres atributos priorizados en la Entrega 2 fueron Escalabilidad (H/H), Modificabilidad (H/H)
y Disponibilidad (H/M).

| # | Atributo | Escenario | Cómo se valida |
|---|---|---|---|
| 1 | **Modificabilidad** | Incorporar el partner 31 sin agregar condicionales dentro de *Orquestación de trabajos* | `scripts/demo_esc6.sh`, en **dos fases**: (1) se registra el partner —acto administrativo, no crea ningún trabajo—; (2) llega un trabajo **de ese partner** y se resuelve con su SLA y su red homologada. Se mide: 0 condicionales en el código y 0 imágenes reconstruidas. Sin la fase 2 no se demuestra nada: insertar una fila no prueba modificabilidad |
| 2 | **Disponibilidad** | El sistema sigue creando y asignando trabajos con un componente caído | `scripts/demo_disponibilidad.sh`: se apaga *Motor reglas partner* y los consumidores siguen operando desde su proyección local |
| 3 | **Escalabilidad** | Absorber el pico de 4x de **trabajos** sin perder mensajes ni bloquear al productor | `scripts/semilla_partners.py` una vez, y luego `scripts/carga_escalabilidad.py`: rampa de 10 → 50 → 200 **trabajos**/s sobre `comandos-trabajos`. Se mide backlog, latencia p95 y drenado al agregar réplicas. Además se comprueba que el backlog de `comandos-partner` **permanece en cero**: el flujo administrativo no está en el camino crítico |

**Por qué estos y no otros.** El enunciado advierte contra la mala experimentación: probar que
Pulsar sirve, medir cobertura de pruebas, o medir latencias que al negocio le dan igual. Los tres
de arriba miden propiedades de **la arquitectura**, no de la infraestructura:

- El escenario 1 mide **cuántos artefactos hay que tocar**, que depende de dónde pusimos la
  variabilidad, no de qué broker usamos.
- El escenario 2 mide **si el acoplamiento es al tópico o al servicio**, que es una decisión de
  diseño de eventos.
- El escenario 3 mide **si el consumo escala horizontalmente**, que depende del tipo de
  suscripción y del particionado que elegimos, no de la capacidad bruta del broker.

---

## 1. Formato de mensajes: **Avro**

**Decisión.** Avro, con el registro de esquemas nativo de Apache Pulsar.

**Por qué, frente a las alternativas:**

| Opción | Por qué no |
|---|---|
| **JSON** | No hay esquema que el broker pueda hacer cumplir. La compatibilidad queda en la disciplina del equipo, que es exactamente lo que falla cuando hay cuatro personas y una semana. |
| **Protobuf** | Técnicamente válido y con mejor tamaño en el cable. Se descartó porque su compatibilidad se apoya en **números de campo**, que un humano tiene que administrar sin equivocarse, y porque obliga a un paso de compilación (`protoc`) en el pipeline de cada servicio. |
| **Parquet** | Es un formato columnar para análisis en lote, no para mensajería. |

**Por qué Avro sí:**

1. **El esquema viaja con el dato.** Un consumidor puede leer un mensaje escrito con otra versión
   resolviendo esquema de escritura contra esquema de lectura. Eso es lo que hace que la evolución
   funcione sin coordinar despliegues entre los cuatro servicios.
2. **La compatibilidad la aplica el broker, no el equipo.** Pulsar rechaza al conectar a un
   productor cuyo esquema viole la política del namespace. El contrato deja de ser una
   recomendación del README.
3. **Se resuelve por nombre de campo, no por número.** No hay un número de etiqueta que alguien
   pueda reutilizar por accidente y corromper los mensajes en silencio.
4. **Es lo que el curso usa** (`pulsar.schema.Record` + `AvroSchema`), así que el tutor puede leer
   el código sin traducir convenciones.

**Qué se paga.** Más bytes que Protobuf. Medido en este servicio: **187 bytes** para el evento
completo con carga de estado. Irrelevante frente a los 25 M de peticiones/día del caso.

**Dónde se ve:** `src/motor_reglas/modulos/partners/infraestructura/schema/v1/`.

---

## 2. Versionamiento y evolución de esquemas

**Decisión.** Tres mecanismos apilados, del más automático al más manual.

### a) Política `BACKWARD` en el namespace, aplicada por el broker

```bash
pulsar-admin namespaces set-schema-compatibility-strategy hda/poc --compatibility BACKWARD
```

`BACKWARD` = un consumidor con el esquema nuevo puede leer mensajes escritos con el viejo. Se
eligió sobre `FORWARD` porque en nuestro flujo **los consumidores se despliegan antes que los
productores**: *Orquestación* y *Emparejamiento* ya existen cuando *Motor reglas partner* empieza a
publicar un campo nuevo.

| Permitido | Prohibido |
|---|---|
| Agregar campo opcional con `default` | Agregar campo obligatorio |
| Eliminar campo que tenía `default` | Renombrar un campo |
| Ampliar documentación | Cambiar el tipo de un campo |

Verificado ejecutablemente en `tests/test_evolucion_esquema.py`: tres pruebas que comprueban que
lo permitido funciona y que lo prohibido rompe. Corriéndolas en integración continua, la regla de
compatibilidad falla el build en vez de fallar en producción.

### b) Versión en el sobre: `specversion` y `type`

Dos ejes independientes. `specversion` versiona el **sobre** (la estructura CloudEvents);
`type` identifica el **contenido**. Se pueden evolucionar por separado.

### c) Event Stream Versioning para los cambios incompatibles

Cuando un cambio no cabe en `BACKWARD` —renombrar, cambiar un tipo, partir un campo— **no se
versiona el esquema: se crea un tipo nuevo**.

1. Se publica `ReglaDePartnerActualizadaV2` en paralelo con el V1.
2. Los consumidores migran uno a uno, a su ritmo, sin coordinación.
3. Cuando ninguna suscripción consume el V1, se retira.

**Por qué así y no con un `upcaster` en el consumidor:** un upcaster pone la traducción del lado
de quien lee, así que cada uno de los N consumidores tiene que escribirla y mantenerla. Publicar
los dos tipos pone el costo una vez, del lado del productor, que es quien tomó la decisión de
cambiar.

**El paquete de contratos como artefacto generado.** Los `.avsc` de `contratos/` los produce
`scripts/generar_avsc.py` a partir de los `Record`. Una sola fuente de verdad, y el diff del
contrato es revisable en un pull request antes de que el broker lo acepte.

---

## 3. Tipos de evento: integración vs. carga de estado

**Decisión.** Los dos, y cada uno donde corresponde. La elección **la dicta el escenario de
calidad**, que es justo lo que el enunciado pide argumentar.

| Evento | Tipo | Por qué |
|---|---|---|
| `TrabajoCreado`, `TrabajoAsignado` | **integración delgado** | Notifican un hecho. Quien necesite el detalle lo pide. Mantenerlos delgados evita que el modelo interno de *Orquestación* se convierta en contrato público. |
| `ReglaDePartnerActualizada` | **carga de estado** | Lleva la regla completa. |
| `EstadoDeHabilitacionCambiado` | **carga de estado** | Ídem. |

### Por qué `ReglaDePartnerActualizada` lleva carga de estado

Es una decisión tomada **por el escenario de disponibilidad**, no por comodidad.

Si el evento fuera delgado —`{partner_id, version}`— el consumidor tendría que venir a preguntar
por la regla completa. Esa consulta es acoplamiento de disponibilidad por la puerta de atrás: con
*Motor reglas partner* caído, *Orquestación* no podría resolver ningún trabajo, y el escenario 2
fallaría. Con carga de estado, el consumidor ya tiene todo lo que necesita en su proyección local.

**Qué se paga:** mensajes más grandes (187 bytes contra ~60), almacenamiento duplicado en cada
consumidor y consistencia eventual. Aceptable: una regla de partner cambia rara vez y tolera
segundos de retraso.

**Dónde se ve:** `ReglaDePartnerActualizadaPayload` en `schema/v1/eventos.py`, con el porqué
escrito en el docstring de la clase.

---

## 4. Topología de datos: **híbrida**

**Decisión.** Híbrida, y el agrupamiento es explícito.

El enunciado pide elegir entre descentralizada e híbrida y ser claro sobre cómo se agrupa.

- **Descentralizada** (una base de datos por servicio, sin excepción) es el ideal de
  modificabilidad, pero deja sin resolver las consultas que cruzan dominios.
- **Híbrida** = descentralizada para la escritura + almacenes de lectura compartidos por grupo,
  alimentados por eventos.

**Cómo agrupamos:**

| Grupo | Qué contiene | Almacén |
|---|---|---|
| **Escritura** | Cada uno de los 4 servicios | Una instancia de PostgreSQL **propia y exclusiva**. Nadie lee ni escribe la ajena. |
| **Lectura** | Proyecciones locales de datos de otros | Tablas **dentro de la misma base del consumidor**, alimentadas por sus suscripciones |

La segunda fila es lo que hace a la topología híbrida y no puramente descentralizada: hay copias
del mismo dato en varios almacenes. La diferencia con compartir una base de datos es **quién
escribe**: una proyección la escribe únicamente el consumidor que la posee, aplicando eventos, y
nunca otro servicio.

**Por qué no puramente descentralizada.** Sin proyecciones, *Orquestación* tendría que preguntar
por la regla de cada partner en cada trabajo. Eso es una llamada síncrona —prohibida por el
enunciado— o un acoplamiento de disponibilidad. La copia local es el precio de no tener ninguna
de las dos cosas.

**Qué se paga:** consistencia eventual y almacenamiento duplicado. El riesgo real, declarado: que
alguien escriba directamente en una proyección. En ese momento hay dos dueños del mismo dato y la
arquitectura se rompió sin que ningún diagrama lo muestre.

---

## 5. Patrón de almacenamiento: **CRUD aquí, Event Sourcing en Orquestación**

**Decisión.** Mixta, por servicio, según lo que cada uno necesite recordar.

| Servicio | Patrón | Por qué |
|---|---|---|
| **Motor reglas partner** | **CRUD** | Lo que importa es la regla **vigente**. Nadie pregunta «¿qué SLA tenía este partner en marzo?». La versión de la regla (`regla_version`) da la trazabilidad que se necesita sin el costo de reconstruir estado desde un log. |
| **Orquestación de trabajos** | **Event Sourcing** | Lo contrario: el **historial** del trabajo *es* el negocio. Creado → asignado → en ejecución → cerrado → pagado, con quién y cuándo, es lo que hay que poder auditar frente a una aseguradora en una disputa. |
| Emparejamiento, Acreditación | CRUD | Solo interesa el estado actual. |

**Por qué no Event Sourcing en todo.** Porque cuesta: hay que versionar los eventos del store,
resolver *snapshots* cuando el flujo crece, y reconstruir el agregado en cada lectura. Pagar eso
donde nadie va a consultar el historial es complejidad sin contraparte. Elegir por servicio, y
poder decir por qué en cada caso, es más defendible que aplicar el patrón de moda en todos.

**Qué se paga:** dos modelos mentales en el mismo sistema. Se mitiga con el `seedwork` compartido,
que hace que las dos mitades se escriban con las mismas abstracciones.

---

## 6. Patrón Outbox

**Decisión.** Outbox transaccional para publicar eventos.

**El problema.** Guardar en PostgreSQL y publicar en Pulsar son dos sistemas distintos y no hay
transacción que abarque a los dos:

- Publicar **antes** del commit → un rollback deja un evento que describe algo que no ocurrió.
- Publicar **después** → una caída entre el commit y el publish pierde el evento para siempre.

**La solución.** El evento se **inserta en la tabla `outbox` dentro de la misma transacción** que
el cambio de dominio. Un relay separado la drena hacia Pulsar y marca las filas.

**Qué garantiza:** entrega **al menos una vez**. Si el relay publica y muere antes de marcar, el
evento se republica. Por eso todo consumidor es idempotente, y por eso existe la tabla
`mensajes_procesados`.

**Qué se paga:** latencia de hasta un segundo entre el commit y la publicación, y un proceso más
que vigilar. A cambio, «publicamos eventos» se convierte en «no perdemos eventos».

**Dónde se ve:** `infraestructura/outbox.py` y la tabla `Outbox` en `infraestructura/dto.py`.
`tests/test_aplicacion_e2e.py` verifica que la fila del outbox existe en la misma transacción,
incluso sin broker levantado.

---

## 7. Coreografía u orquestación

**Decisión para la Entrega 4: coreografía.** El criterio es uno solo: **¿hay que compensar?**

En el flujo crear → asignar no hay nada que deshacer: si la asignación falla, el trabajo se queda
en estado `Creado` esperando. No hay dinero retenido ni invariante repartido. Coreografía basta y
cuesta mucho menos acoplamiento.

**Una aclaración de nombre que conviene tener lista:** el servicio *Orquestación de trabajos* usa
**coreografía**. No es contradicción: el nombre viene del lenguaje ubicuo del negocio —orquestar
el ciclo de vida de un trabajo— y no del patrón de coordinación entre servicios.

**Lo que cambió por la prohibición de llamadas síncronas.** El diseño original protegía el
invariante de habilitación con una consulta síncrona en el momento de asignar. El enunciado lo
prohíbe, así que el invariante se resuelve ahora con **asignación optimista + compensación**:

1. *Emparejamiento* asigna leyendo su proyección local y publica `TrabajoAsignado`.
2. *Acreditación*, único dueño del dato autoritativo, verifica.
3. Si el proveedor no estaba habilitado, publica `AsignacionRechazadaPorHabilitacion` y se reasigna.

Eso convirtió un invariante de consistencia inmediata en una **transacción larga con
compensación** — que es exactamente el material de la saga de la **Entrega 5**. La restricción del
enunciado no fue un obstáculo: fue lo que reveló dónde estaba la transacción larga.

---

## 8. Plataforma de despliegue

**Decisión para la Entrega 4: Docker Compose sobre una sola máquina.**

**Por qué.** Lo que hay que demostrar es que **la arquitectura** escala y degrada bien, no que
sabemos operar Kubernetes. Compose permite las tres demostraciones sin nada más:

- `docker compose up --scale motor-reglas-partner=3` → escalado horizontal, escenario 3.
- `docker stop motor-reglas-partner` → falla de componente, escenario 2.
- Reconstruir una sola imagen → despliegue independiente, escenario 1.

**Qué se paga y se declara:** una sola máquina no prueba tolerancia a fallo de zona, y el cluster
de Pulsar corre con `ensembleSize=1` y `writeQuorum=1`, o sea **sin réplica real de datos**. Para
la Entrega 5, tumbar una región completa de brokers —como sugiere el enunciado— exige subir esos
valores a 3 y desplegar en un orquestador de verdad.

**Camino a producción, para poder contestarlo:** las imágenes ya son autocontenidas y se
configuran por variables de entorno, así que el paso a Kubernetes es escribir manifiestos, no
cambiar código. El único cambio real de código sería sacar el relay del outbox y el consumidor a
procesos separados, que hoy son hilos dentro del proceso de Flask.

---

## 9. DDD: qué se aplicó y qué no

El enunciado advierte contra aplicar todo lo visto solo por demostrarlo. Lo aplicado y por qué:

| Aplicado | Dónde | Por qué era necesario |
|---|---|---|
| **Agregación** | `Partner` como raíz, con `Convenio` y `ReglaDePartner` dentro | Una regla sin convenio vigente es un estado inválido: los dos tienen que quedar consistentes en la misma transacción. Ese es el criterio de Evans, no una preferencia estética. |
| **Entidad vs. objeto valor** | `Convenio` es entidad; `Vigencia`, `Tarifa`, `Dinero` son objetos valor inmutables | Dos convenios con los mismos términos son convenios distintos. Dos `Dinero` de 1000 COP son el mismo dinero. |
| **Reglas de negocio como clases** | `dominio/reglas.py` | Un invariante con nombre se puede señalar en el código y explicar. Un `if` hay que ir a buscarlo. |
| **Inversión de dependencias / cebolla** | El dominio declara `RepositorioPartners`; la infraestructura lo implementa | Verificable: `grep -r "sqlalchemy\|pulsar" dominio/` devuelve 0. Es lo que permite probar el dominio sin infraestructura. |
| **CQRS** | `aplicacion/comandos/` y `aplicacion/queries/` | La lectura va directo al DTO y no reconstruye la agregación: el agregado existe para proteger escrituras. |
| **Repositorio + Mapeador + Fábrica** | `infraestructura/` | Separan el modelo de dominio del esquema de base de datos y del contrato público. Sin ellos, un `ALTER TABLE` sería un cambio de contrato. |
| **Referencia por identidad** | `Trabajo` referencia `PartnerId` | Si `Trabajo` embebiera la regla, cambiarla obligaría a migrar todos los trabajos vivos. |

**Lo que se dejó fuera a propósito:** Specification, Shared Kernel, Unit of Work explícita con
savepoints y event sourcing en este servicio. Ninguno resolvía un problema que tuviéramos aquí, y
agregarlos habría sido complejidad para la foto.

---

## 10. Resumen de puntos de sensibilidad y tradeoffs

| Decisión | Punto de sensibilidad | Tradeoff |
|---|---|---|
| Una base de datos por servicio | Número de servicios que acceden a un mismo almacén = **1** | Modificabilidad ↑ / consultas transversales y almacenamiento ↓ |
| Evento con carga de estado | Tamaño del payload y latencia de propagación | Disponibilidad y desacople ↑ / consistencia ↓ |
| Tópico compactado con clave `partner_id` | Un solo tipo de mensaje por clave | Arranque en frío instantáneo ↑ / se pierde el historial de cambios ↓ |
| Suscripción `Shared` | Tipo de suscripción | Escalado horizontal ↑ / orden global ↓ (se recupera con `Key_Shared`) |
| Outbox | Intervalo del relay (1 s) | No se pierden eventos ↑ / latencia de publicación ↓ |
| CRUD en este servicio | Que nadie pida el historial de reglas | Simplicidad ↑ / auditoría histórica ↓ |
| Cluster con `writeQuorum=1` | Réplica de datos del broker | Arranque rápido para la POC ↑ / tolerancia a fallos ↓ — **a corregir en la Entrega 5** |

---

## 11. Lo que falta para la Entrega 5

1. **Saga** de la transacción larga cierre → pago → liquidación, con compensaciones explícitas.
   El esqueleto ya existe: `AsignacionRechazadaPorHabilitacion` es la primera compensación.
2. **BFF** con endpoint REST o GraphQL, y colección de Postman para el tutor.
3. **Cluster real**: `ensembleSize=3`, `writeQuorum=3`, varios brokers, para poder tumbar una
   región y medir de verdad.
4. **Refinar el mapa de contextos y las vistas** con lo aprendido en la experimentación. En
   particular, el defecto ya detectado: en la vista C&C de la Entrega 2, `:Motor reglas partner`
   aparece solo como `Sub` y esta implementación demuestra que es `Pub/Sub`.
