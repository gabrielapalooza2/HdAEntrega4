# Guion del video — comandos + qué decir

Todo se escribe en la **terminal A**. Las B y C solo se miran.
Duración: ~13 min.

---

## LA FORMA FACIL: que el script conduzca

En vez de tipear cada comando, corré:

```bash
./scripts/demo.sh
```

Te muestra el comando, espera que aprietes **Enter**, lo corre, y espera otro
Enter para seguir. No tipeás ni pegás nada durante la grabación: hablás y
apretás Enter. Además **captura solo el `trabajo_id`**, que es donde más fácil
se traba una toma.

```bash
./scripts/demo.sh        # todas las escenas, en orden
./scripts/demo.sh 4      # arranca desde la escena 4
./scripts/demo.sh 4 6    # de la 4 a la 6, para ensayar una parte
```

El texto a decir en cada escena está más abajo en este mismo documento.

---

## ANTES DE GRABAR

```bash
cd ~/HdAEntrega4/servicios/orquestacion-trabajos
export PULSAR_URL=pulsar://localhost:6650
export PULSAR_LISTENER=external
alias py=./.venv/bin/python
./scripts/reiniciar_demo.sh
```

### Las tres terminales

**Terminal A** es la unica donde se escribe. **B y C solo miran logs**: no se
corre ningun comando de la demo en ellas.

**Terminal B** — tu servicio:

```bash
docker logs -f --tail 1000 orquestacion-trabajos 2>&1 | grep --line-buffered -E "orquestacion\.(aplicacion|infraestructura)"
```

**Terminal C** — Emparejamiento:

```bash
docker logs -f --tail 1000 emparejamiento-asignacion 2>&1 | grep --line-buffered -E "emparejamiento\.(application|pulsar)"
```

> **`--tail 1000` no es exagerado, es lo minimo.** El cliente nativo de Pulsar
> escupe estadisticas de consumidor cada minuto: con `--tail 30` las ultimas
> treinta lineas son TODAS ruido, el filtro no deja pasar nada y la terminal se
> ve vacia, como si estuviera rota. Medido: con 30 hay cero coincidencias, con
> 1000 hay decenas.
>
> **`--line-buffered` tampoco sobra:** sin el, grep acumula la salida en un
> buffer y las lineas nuevas aparecen a los saltos en vez de en el momento.

Las dos arrancan mostrando actividad reciente, asi confirmas que estan
enganchadas antes de grabar. Si salen vacias, algo esta mal.

Limpiá las tres pantallas (`clear`) y empezá.

---

## 0 · APERTURA

```bash
find src/orquestacion -maxdepth 2 -type d -not -path '*__pycache__*' | sort
```

> «Hola, soy Sofía. Voy a mostrar **Orquestación de Trabajos**, el microservicio
> del que soy responsable en Hogar de los Alpes. Es el dueño del agregado
> `Trabajo`, implementado con **Event Sourcing y CQRS**, y se comunica con los
> otros servicios **únicamente por Apache Pulsar**: no hay una sola llamada
> síncrona entre microservicios.
>
> Esta es la estructura. Arquitectura hexagonal en tres capas: `dominio` es
> Python puro, `aplicacion` orquesta las transacciones, `infraestructura` tiene
> lo que habla con el mundo. Y `mensajeria` aparte, que es la costura donde vive
> toda la traducción de contratos. Voy a demostrar que esas fronteras se
> respetan, no solo afirmarlo.»

---

## 1 · EL CLUSTER

```bash
docker compose ps
```

> «Un **cluster** de Pulsar, no `standalone`. ZooKeeper guarda los metadatos,
> BookKeeper el almacenamiento, el broker atiende a los clientes. Y abajo, **una
> base de datos por servicio**: ningún servicio lee el almacén de otro.»

```bash
docker exec broker bin/pulsar-admin namespaces get-retention hda/poc
```

> «Retención infinita, en tiempo y en tamaño. Sin esto, un mensaje confirmado por
> todas las suscripciones se borra, y un servicio nuevo no podría reconstruir su
> proyección leyendo desde el inicio.»

```bash
docker exec broker bin/pulsar-admin topics list hda/poc | sort
```

> «Tópico **por agregado**, no por tipo de mensaje: los hechos de un mismo
> trabajo van por el mismo tópico con la misma clave de partición, y Pulsar me
> preserva el orden. El consumidor discrimina por el campo `type` del sobre.
>
> Los de flujo operativo van **particionados en tres** para escalar el consumo.
> Pero fíjense en `evt.partners` y `evt.proveedores`: **no están particionados**,
> y es a propósito. Son streams clave-valor donde solo importa el último estado
> de cada partner, y están **compactados**. La compactación conserva el último
> mensaje por clave dentro de cada partición: con varias particiones, un
> consumidor en frío obtendría una vista parcial.»

---

## 2 · LA CAPA ANTICORRUPCIÓN

```bash
grep -n "zona\|ciudad" src/orquestacion/mensajeria/contratos.py | head -12
```

> «Nuestro grupo se llama *Capa Anticorrupción*, así que empiezo por ahí. Este
> módulo es el **único** que conoce el contrato del grupo. Adentro digo `zona`;
> afuera el contrato dice `ciudad`. Adentro `regla_version`; afuera
> `version_regla`. Los nombres **no coinciden**, y esa es exactamente la razón de
> que la capa exista: mi dominio no se deforma para parecerse al contrato ajeno,
> y el contrato ajeno puede cambiar sin que yo toque el dominio.
>
> No se los pido de palabra, se los muestro.»

```bash
grep -rn "cobertura_contratada\|sla_vence_en\|excluir_proveedores" src/orquestacion/dominio/ || echo "el dominio NO conoce los nombres de afuera"
```

> «Cero resultados.»

```bash
grep -rn "^import\|^from" src/orquestacion/dominio/*.py | grep -E "psycopg|pulsar|flask" || echo "cero dependencias de infraestructura"
```

> «Y el dominio tampoco importa infraestructura. Por eso las pruebas de dominio
> corren sin levantar base de datos ni broker.»

---

## 3 · LAS REGLAS COMO DATO

```bash
docker exec db-trabajos psql -U trabajos -d trabajos -c \
"SELECT partner_id, regla_version, sla_minutos, activo, categorias_cubiertas FROM proyeccion_regla_partner ORDER BY partner_id;"
```

> «Esta es la proyección local de reglas de partner. Cada aseguradora con su
> cobertura, su SLA y su estado, y todo eso **llegó como eventos** por
> `evt.partners`.
>
> Esto sostiene una regla dura del diseño: **cero condicionales por partner**. No
> hay ni un `if partner_id igual a...` en todo el servicio. Agregar una
> aseguradora nueva es publicar un evento, no editar código y redesplegar.
>
> Y hay algo más importante: validar un trabajo **lee esta tabla**, no llama al
> Motor de Reglas por red. Si ese servicio está caído, yo sigo operando con la
> última regla conocida. Ese es el escenario de disponibilidad.»

---

## 4 · EL CONGELAMIENTO DEL SLA ⭐

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA
```

> «Creo un trabajo para SEGUROS_ALFA, categoría plomería.»

**📋 COPIÁ el `trabajo_id` de la terminal B — lo necesitás en las escenas 7 y 8.**

```bash
docker exec db-trabajos psql -U trabajos -d trabajos -c \
"SELECT secuencia, tipo, payload->>'sla_minutos' sla, payload->>'regla_version' regla, payload->>'vence_en' vence FROM eventos_trabajo ORDER BY ocurrido_en DESC LIMIT 3;"
```

> «Acá está el corazón del escenario de **modificabilidad**. `sla_minutos` y
> `regla_version` se copiaron de la regla vigente en ese instante y quedaron
> **congelados dentro del payload del evento**.
>
> Si mañana el partner cambia su regla a quince minutos, este trabajo **sigue con
> ciento veinte**. Y no es que no queramos cambiarlo: es que **no se puede**.»

```bash
grep -rni "UPDATE eventos_trabajo\|DELETE FROM eventos_trabajo" src/ || echo "NINGUNO"
```

> «Cero. No hay un solo `UPDATE` ni `DELETE` sobre el event store en todo el
> servicio. El congelamiento no es una promesa, es una **garantía estructural**.
>
> Un detalle: `regla_version` y `vence_en` **no viajan** en el mensaje que sale a
> Pulsar, porque el contrato del grupo no tiene esos campos. Y no importa: el
> congelamiento se prueba acá, en el event store, que es la fuente de verdad y es
> solo mía. El evento de integración es una **proyección recortada** del evento
> de dominio.»

---

## 5 · LOS RECHAZOS

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_BETA --categoria PLOMERIA --zona BOGOTA
py scripts/publicar.py CrearTrabajo --partner-id PARTNER_DORMIDO --categoria PLOMERIA --zona BOGOTA
```

> «El mismo comando, pero SEGUROS_BETA **no cubre plomería**, y PARTNER_DORMIDO
> está inactivo.
>
> Dos cosas. El rechazo **se guarda en el event store y se publica**: no lanzo una
> excepción, porque un trabajo que la regla no cubre **no es un error técnico, es
> una decisión de negocio**. La aseguradora tiene derecho a enterarse y a saber
> por qué. Por eso lleva un `motivo` con código estable, para que una máquina
> reaccione, y un `detalle` en texto, para que una persona entienda.
>
> Y lo segundo: es el **mismo código** que aceptó el trabajo anterior. Lo único
> que cambió fue el dato de la regla.»

---

## 6 · IDEMPOTENCIA

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria ELECTRICIDAD --duplicar 3
```

> «Pulsar entrega **al menos una vez**. Recibir el mismo mensaje dos veces no es
> excepcional: es lo normal. Mando el **mismo sobre**, con el mismo
> identificador, tres veces.
>
> Se aplicó uno y se descartaron dos. Eso lo hace la tabla
> `mensajes_procesados`, y el insert va **en la misma transacción que el
> efecto**: no hay ventana entre verificar y marcar.
>
> Pero hay un **segundo** mecanismo, para un problema distinto. Si un mensaje
> **viejo** llega tarde, trae un identificador distinto, así que pasa limpio la
> marca de idempotencia. Lo que lo frena es la **guarda de versión**: la
> proyección descarta todo lo menor a lo ya aplicado.
>
> Uno protege contra la **repetición**, el otro contra el **desorden**. Son
> problemas distintos y hacen falta los dos.»

---

## 7 · CQRS Y EL REZAGO VISIBLE

```bash
curl -D- localhost:5001/trabajos/PEGA_EL_TRABAJO_ID/estado
```

> «Consulto el estado por HTTP. Esta es la **única excepción síncrona** de todo
> el sistema, y es hacia afuera: un operador preguntando. Nunca hacia otro
> microservicio.
>
> Lee **solo la proyección**: una consulta por clave primaria, sin reproducir
> eventos ni abrir transacción sobre el agregado. Ese es el punto de tener el
> lado de lectura separado.
>
> Y miren este header: **`X-Proyeccion-Secuencia`**. En CQRS la proyección va
> **siempre** por detrás del event store, aunque sea por milisegundos. Exponerlo
> hace ese rezago **observable** en vez de esconderlo.»

---

## 8 · EL ÚNICO PUNTO ORQUESTADO ⭐

```bash
for P in PROV_1 PROV_2 PROV_3; do
  py scripts/publicar.py AsignacionRechazadaPorHabilitacion --trabajo-id PEGA_EL_TRABAJO_ID --proveedor-id $P
done
```

> «Ahora la compensación. Emparejamiento asignó un proveedor de forma optimista,
> y Acreditación descubrió después que **no estaba habilitado**. No hay
> transacción distribuida que deshaga eso: hay un mensaje que dice que salió mal
> y alguien que reacciona.
>
> Al primero y al segundo pidió otro proveedor. Al **tercero escaló a revisión
> manual** en vez de seguir reintentando. Sin ese tope, un proveedor mal
> habilitado y un Emparejamiento que lo reasigna harían un bucle infinito.
>
> Este es el **único punto orquestado del sistema**. Todo lo demás es
> coreografía: cada servicio reacciona a lo que ve y nadie dirige. Acá no: acá
> hay alguien que decide y que **lleva la cuenta**. Se orquesta porque el
> reintento acotado necesita **memoria** —cuántas veces ya lo intentamos— y esa
> memoria vive en el agregado, que es su dueño natural.»

```bash
docker exec db-trabajos psql -U trabajos -d trabajos -c \
"SELECT secuencia, tipo, payload->>'proveedor_id' proveedor, payload->>'motivo' motivo FROM eventos_trabajo WHERE trabajo_id='PEGA_EL_TRABAJO_ID' ORDER BY secuencia;"
```

> «Y miren lo que me da Event Sourcing: **siete eventos que cuentan por qué** este
> trabajo terminó escalado. Qué proveedor falló, en qué intento, por qué motivo.
> Una tabla de estado con un contador no me da eso.»

```bash
py scripts/escuchar.py cmd.emparejamiento --desde-el-inicio --maximo 2
```

> «Salieron **dos** comandos, no tres: al tercero escaló. Y fíjense que
> `excluir_proveedores` se acumula y viaja **dentro del mensaje**, porque
> Emparejamiento no puede leer mi base de datos. En una arquitectura de eventos,
> el estado necesario para decidir va en el mensaje.
>
> Y acá una honestidad: hoy **nadie consume este tópico**. Emparejamiento tiene
> un test que exige no consumirlo. El comando sale bien formado, pero esa rama de
> la integración es deuda del grupo y está documentada.»

---

## 9 · EL BARRIDO DE SLA

```bash
py scripts/publicar.py CrearTrabajo --partner-id ASISTENCIA_GAMMA --categoria PLOMERIA --zona BOGOTA
```

> «Creo un trabajo para ASISTENCIA_GAMMA, que tiene SLA de **un minuto**.
> Mientras esperamos, explico por qué existe este barrido.
>
> **Los eventos te dicen lo que pasó, nunca lo que NO pasó.** En coreografía
> nadie espera. Si Emparejamiento jamás responde, no llega ningún mensaje que
> diga "no respondí", y sin este barrido el trabajo se queda quieto para siempre.
>
> **El paso del tiempo es el único estímulo que ningún broker puede entregar.**
> Por eso hay un hilo que cada treinta segundos busca trabajos vencidos en estado
> no terminal y los escala.
>
> Y un detalle: `ASIGNADO` **detiene el reloj**, porque el SLA es de
> **respuesta**, no de ejecución. Se cumple cuando hay un técnico asignado, no
> cuando el técnico termina.»

*(esperá ~90 s)*

```bash
docker exec db-trabajos psql -U trabajos -d trabajos -c \
"SELECT left(trabajo_id::text,8) id, estado, partner_id, sla_minutos FROM proyeccion_trabajo WHERE partner_id='ASISTENCIA_GAMMA';"
```

> «Ahí está: escalado por SLA vencido, sin que nadie se lo pidiera.»

---

## 10 · PUNTA A PUNTA ⭐ (el cierre)

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA
```

> «Para terminar, el sistema completo. Un solo comando, y miren las tres
> terminales.
>
> Mi servicio recibió el comando y publicó el hecho. **Emparejamiento**, que es
> otro microservicio hecho por otro compañero, reaccionó solo, eligió un
> proveedor y publicó `TrabajoAsignado`. Y mi servicio lo consumió y cerró el
> trabajo.
>
> **Ciento quince milisegundos. Cero llamadas síncronas.** Nadie le pidió nada a
> nadie: cada uno reaccionó a lo que vio en el bus. Y el `correlation_id` es el
> mismo en los dos servicios, así que la historia completa es trazable de punta a
> punta.
>
> Una cosa que quiero señalar porque **no está bien modelada**: `evt.trabajos` es
> el tópico de **mi** agregado, y Emparejamiento también publica ahí. O sea que
> para enterarme de una asignación tengo que **consumir mi propio tópico**. Eso
> es un ciclo: el dueño de un agregado debería ser el único productor de su
> tópico. Lo mitigo descartando todo mensaje que lleve mi propio `service_name`,
> y está registrado como deuda: pedirle a Emparejamiento que publique en
> `evt.asignaciones` y mover el consumidor allá.»

---

## 11 · CIERRE

```bash
open DECISIONES.md
```
*(o mostralo en el editor)*

> «Todas estas decisiones están documentadas con sus tradeoffs: el event store en
> PostgreSQL porque un tópico retenido no se puede consultar por agregado; la
> clave primaria compuesta **como** control de concurrencia optimista, sin locks;
> el patrón outbox para que el evento y el mensaje salgan en la misma
> transacción; y toda la traducción de contratos en un solo módulo.
>
> Son diecisiete decisiones, cada una con lo que costó. Gracias.»

---

## SI ALGO FALLA

| Síntoma | Arreglo |
|---|---|
| `Connection refused` a `127.0.0.1:6650` | falta `export PULSAR_LISTENER=external` |
| Todo sale `PARTNER_DESCONOCIDO` | `./scripts/reiniciar_demo.sh` |
| `sin_candidatos` en Emparejamiento | `py scripts/sembrar_proveedores.py` |
| Te equivocaste en una toma | `./scripts/reiniciar_demo.sh` y volvé a empezar |

## NO PROMETAS

- `cmd.emparejamiento` **no tiene consumidor** — decilo en la escena 8.
- **Acreditación no existe** — los proveedores los simula un script.

## MULETILLAS

*«y esto importa porque…»* · *«el tradeoff acá es…»*
