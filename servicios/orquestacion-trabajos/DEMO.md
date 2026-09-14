# Guion del video demo — Orquestación de Trabajos

Todos los comandos de este documento están **probados** contra el cluster real.
Duración estimada: **12–14 minutos**.

---

## Antes de grabar (hacelo una vez, sin cámara)

### 0.1 Liberar los puertos

El proyecto anterior (`~/hda`) ocupa 6650, 8080 y 5432. Bajalo:

```bash
docker stop hda-pulsar hda-postgres
```

### 0.2 Arranque limpio del cluster

```bash
cd ~/HdAEntrega4
git checkout master && git pull

docker compose down -v && rm -rf data/   # borra estado viejo del cluster
make infra                               # ZooKeeper + BookKeeper + broker + 4 bases
chmod +x scripts/crear_topicos.sh        # el repo lo trae sin permiso de ejecución
make topicos
docker compose up -d --build --no-deps orquestacion-trabajos emparejamiento-asignacion
```

> **`--no-deps` no es opcional.** Sin él, Compose vuelve a lanzar `pulsar-init`,
> que falla porque los metadatos del cluster ya existen, y te tumba el arranque.

### 0.3 Confirmar que todo está arriba

```bash
docker compose ps
curl -s localhost:5001/health   # {"estado":"vivo",...}
curl -s localhost:8000/health   # {"status":"ok",...}
```

Si `emparejamiento` no responde, dale 30 s más y reintentá: tarda en suscribirse.

### 0.4 Sembrar los datos de la demo

```bash
cd servicios/orquestacion-trabajos
export PULSAR_URL=pulsar://localhost:6650
export PULSAR_LISTENER=external
./scripts/reiniciar_demo.sh
```

Este script **también sirve entre tomas**: borra los datos de los dos servicios
y vuelve a sembrar en segundos, sin rearmar el cluster. Si te equivocás grabando,
corrélo y empezá de nuevo.

### 0.5 Variables para tu terminal de grabación

```bash
cd ~/HdAEntrega4/servicios/orquestacion-trabajos
export PULSAR_URL=pulsar://localhost:6650
export PULSAR_LISTENER=external          # imprescindible desde el host
alias py=./.venv/bin/python
```

### 0.6 Preparar la pantalla

Tres terminales visibles a la vez:

```
┌─────────────────────┬─────────────────────┐
│ A: comandos         │ B: logs de tu       │
│    (donde escribís) │    servicio         │
│                     ├─────────────────────┤
│                     │ C: logs de          │
│                     │    emparejamiento   │
└─────────────────────┴─────────────────────┘
```

En B: `docker logs -f orquestacion-trabajos | grep -v "GET /health"`
En C: `docker logs -f emparejamiento-asignacion | grep emparejamiento.`

---

## El guion

### 1 · La infraestructura (1 min)

```bash
docker compose ps
```

> «Un **cluster** de Pulsar, no `standalone`: ZooKeeper para los metadatos,
> BookKeeper para el almacenamiento y el broker. Y **una base de datos por
> servicio** — ningún servicio lee el almacén de otro.»

```bash
docker exec broker bin/pulsar-admin namespaces get-retention hda/poc
docker exec broker bin/pulsar-admin topics list hda/poc | sort
```

> «Retención infinita y tópico **por agregado**, no por tipo de mensaje. Los
> `evt.*` van particionados en 3 para escalar; `evt.partners` va **sin
> particionar y compactado**, porque es un stream clave-valor donde solo importa
> el último estado de cada partner.»

---

### 2 · La capa anticorrupción (2 min)

Abrí `src/orquestacion/mensajeria/contratos.py` en el editor.

> «Este es el único módulo que conoce el contrato del grupo. Adentro decimos
> `zona`, afuera el contrato dice `ciudad`. Adentro `regla_version`, afuera
> `version_regla`. Toda la traducción vive acá y en ningún otro lado.»

Demostralo con `grep`, que es más convincente que mostrar código:

```bash
grep -rn "cobertura_contratada\|sla_vence_en" src/orquestacion/dominio/ \
  && echo "FUGA" || echo "el dominio no conoce los nombres de afuera"
```

> «Y el dominio no importa infraestructura:»

```bash
grep -rn "^import\|^from" src/orquestacion/dominio/*.py | grep -E "psycopg|pulsar|flask" \
  || echo "cero dependencias de infraestructura"
```

---

### 3 · Reglas de partner: la variabilidad es dato (1 min)

```bash
py scripts/seed.py
```

Mirá la terminal B: las cuatro reglas entrando.

```bash
docker exec db-trabajos psql -U trabajos -d trabajos \
  -c "SELECT partner_id, regla_version, sla_minutos, activo, categorias_cubiertas FROM proyeccion_regla_partner ORDER BY partner_id;"
```

> «Cero condicionales por partner: toda la diferencia entre aseguradoras está en
> estas filas, que llegaron como eventos. Agregar una aseguradora no toca una
> línea de código.»

---

### 4 · Crear un trabajo y el congelamiento del SLA (2 min)

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA
```

Copiá el `trabajo_id` del log de la terminal B y mostrá el event store:

```bash
docker exec db-trabajos psql -U trabajos -d trabajos \
  -c "SELECT secuencia, tipo, payload->>'sla_minutos' sla, payload->>'regla_version' regla, payload->>'vence_en' vence FROM eventos_trabajo ORDER BY ocurrido_en DESC LIMIT 3;"
```

> «Acá está el corazón del escenario de modificabilidad. `sla_minutos` y
> `regla_version` se copiaron de la regla vigente y quedaron **congelados en el
> payload del evento**. El event store es append-only: no hay un solo `UPDATE`
> ni `DELETE` sobre esta tabla en todo el servicio.»

```bash
grep -rni "UPDATE eventos_trabajo\|DELETE FROM eventos_trabajo" src/ || echo "ninguno"
```

> «No es que no queramos cambiarlo. Es que no se puede.»

---

### 5 · Rechazo: un hecho de negocio, no un error (1 min)

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_BETA --categoria PLOMERIA --zona BOGOTA
py scripts/publicar.py CrearTrabajo --partner-id PARTNER_DORMIDO --categoria PLOMERIA --zona BOGOTA
```

> «`SEGUROS_BETA` no cubre plomería y `PARTNER_DORMIDO` está inactivo. El rechazo
> **se guarda y se publica**, no se lanza una excepción: la aseguradora tiene
> derecho a enterarse y a saber por qué. Fijate que lo decidió leyendo la
> proyección local — **no llamamos a Motor de Reglas por red**. Si ese servicio
> está caído, este sigue operando.»

---

### 6 · Idempotencia (1 min)

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria ELECTRICIDAD --duplicar 3
```

> «El **mismo** sobre, con el mismo `id`, tres veces: es lo que hace Pulsar al
> reentregar. Se aplica uno y se descartan dos.»

```bash
docker exec db-trabajos psql -U trabajos -d trabajos \
  -c "SELECT count(*) FROM eventos_trabajo WHERE tipo='TrabajoCreado';"
```

> «Y hay un **segundo** mecanismo, para un problema distinto: el desorden. Un
> mensaje viejo que llega tarde trae un `id` distinto, así que pasa la marca de
> idempotencia. Lo frena la guarda de versión.»

---

### 7 · CQRS y el rezago visible (1 min)

```bash
curl -D- localhost:5001/trabajos/<TRABAJO_ID>/estado
```

> «Lee **solo** la proyección: una consulta por clave primaria, sin reproducir
> eventos ni abrir transacción sobre el agregado. Y mirá el header
> `X-Proyeccion-Secuencia`: en CQRS la proyección va siempre por detrás del event
> store. Exponerlo hace ese rezago **observable** en vez de esconderlo.»

---

### 8 · El único punto orquestado (2 min)

```bash
for P in PROV_1 PROV_2 PROV_3; do
  py scripts/publicar.py AsignacionRechazadaPorHabilitacion --trabajo-id <TRABAJO_ID> --proveedor-id $P
done
```

> «Esta es la compensación: Emparejamiento asignó de forma optimista y
> Acreditación descubrió que el proveedor no estaba habilitado. No hay
> transacción distribuida que deshaga eso; hay un mensaje que dice que salió mal
> y alguien que reacciona.
>
> Y este es el **único punto orquestado del sistema**. Todo lo demás es
> coreografía. Se orquesta acá porque el reintento acotado necesita **memoria**
> —cuántas veces ya lo intentamos— y esa memoria vive en el agregado.»

```bash
docker exec db-trabajos psql -U trabajos -d trabajos \
  -c "SELECT secuencia, tipo, payload->>'proveedor_id' proveedor, payload->>'motivo' motivo FROM eventos_trabajo WHERE trabajo_id='<TRABAJO_ID>' ORDER BY secuencia;"
```

> «Siete eventos que cuentan **por qué** este trabajo terminó escalado. Una tabla
> de estado con un contador no te da eso.»

```bash
py scripts/escuchar.py cmd.emparejamiento --desde-el-inicio --maximo 2
```

> «Salieron **dos** comandos, no tres: al tercero escala en vez de reintentar.»

---

### 9 · El barrido de SLA (1 min)

```bash
py scripts/publicar.py CrearTrabajo --partner-id ASISTENCIA_GAMMA --categoria PLOMERIA --zona BOGOTA
```

> «Este partner tiene SLA de un minuto. Mientras esperamos: este barrido existe
> porque **los eventos te dicen lo que pasó, nunca lo que NO pasó**. En
> coreografía nadie espera. Si Emparejamiento jamás responde, no llega ningún
> mensaje que diga "no respondí". El paso del tiempo es el único estímulo que
> ningún broker puede entregar.»

Esperá ~90 s (o cortá y retomá) y mostrá el estado en `ESCALADO_MANUAL`.

---

### 10 · Punta a punta con Emparejamiento (2 min) ← el cierre

```bash
py scripts/publicar.py CrearTrabajo --partner-id SEGUROS_ALFA --categoria PLOMERIA --zona BOGOTA
```

Mostrá las tres terminales a la vez:

```
orquestacion       CrearTrabajo -> TrabajoCreado
emparejamiento     reacciona, asigna PROV_ALFA -> TrabajoAsignado
orquestacion       consume el ajeno -> ASIGNADO
```

> «Dos microservicios, **cero llamadas síncronas entre ellos**, todo por eventos.
> Y el `correlation_id` es el mismo en los dos, así que la historia completa es
> trazable.
>
> Un detalle de diseño: `evt.trabajos` es **nuestro** tópico y Emparejamiento
> también publica ahí, así que consumimos nuestro propio tópico. Eso es un ciclo
> y no es como debería estar modelado. Se mitiga descartando todo sobre con
> nuestro propio `service_name`. Está documentado como deuda.»

---

## Si algo falla grabando

| Síntoma | Causa | Arreglo |
|---|---|---|
| `Connection refused` a `127.0.0.1:6650` | falta `PULSAR_LISTENER=external` | exportalo |
| `PARTNER_DESCONOCIDO` en todo | la proyección de reglas está vacía | `py scripts/seed.py` |
| Emparejamiento dice `sin_candidatos` | no hay proveedores, o la ciudad no coincide | `py scripts/sembrar_proveedores.py` |
| Te equivocaste en una toma | — | `./scripts/reiniciar_demo.sh` y volvé a empezar |
| `pulsar-init` exit 137 | Compose relanzó las dependencias | usá `--no-deps` |
| El broker no levanta | estado viejo en `data/` | `docker compose down -v && rm -rf data/` |

## Qué NO prometer en el video

- **`cmd.emparejamiento` no tiene consumidor.** Emparejamiento tiene un test que
  *exige* no consumirlo. Mostrá que el comando sale bien formado y decí que la
  integración de esa rama es deuda del grupo.
- **Acreditación y Habilitación no existe.** Los proveedores se simulan
  publicando en `evt.proveedores`.
