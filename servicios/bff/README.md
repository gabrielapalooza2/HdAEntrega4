# BFF — Hogar de los Alpes

Puerta de entrada única al sistema. Traduce peticiones HTTP en comandos sobre Apache Pulsar y responde consultas desde una proyección de lectura propia.

## Lo que este componente NO es

| No es | Por qué |
| --- | --- |
| Un API Gateway | No enruta peticiones hacia servicios; publica comandos en un bus |
| Un orquestador | No decide el orden de los pasos de negocio; eso es la saga |
| Un servicio de dominio | No posee ninguna agregación ni aplica reglas de negocio |
| Un proxy | Su modelo de API es distinto al del bus; traducir es su trabajo |

## Las tres decisiones que lo definen

**Toda escritura devuelve 202, nunca 200.** El BFF publica un comando y responde con un `correlation_id`. El cliente consulta `GET /operaciones/{correlation_id}` para ver el desenlace. Devolver 200 con un cuerpo inventado sería mentir sobre un sistema que es asíncrono por dentro.

**Las lecturas salen de una proyección local, no de llamadas a los servicios.** El BFF se suscribe a los tópicos de eventos y mantiene su propia vista. Cero llamados síncronos entre servicios, y sigue respondiendo consultas aunque los cuatro estén caídos.

**No tiene base de datos.** Los tópicos tienen retención infinita, así que al arrancar se suscribe desde el inicio y reconstruye la vista completa. La fuente de verdad es el log de eventos; esto es una caché derivada. Que se pueda tirar y reconstruir es una propiedad, no una carencia.

El precio de las tres, declarado: consistencia eventual, y una reconstrucción proporcional al tamaño del log al arrancar.

## Endpoints

### Escrituras — publican un comando, devuelven 202

| Método | Ruta | Tópico |
| --- | --- | --- |
| POST | `/partners` | `cmd.partners` |
| PUT | `/partners/{id}/regla` | `cmd.partners` |
| POST | `/proveedores` | `cmd.proveedores` |
| POST | `/proveedores/{id}/suspension` | `cmd.proveedores` |
| POST | `/trabajos` | `cmd.trabajos` |

### Lecturas — salen de la proyección

| Método | Ruta | Qué devuelve |
| --- | --- | --- |
| GET | `/operaciones/{correlation_id}` | ACEPTADA, COMPLETADA o RECHAZADA |
| GET | `/operaciones` | Las últimas operaciones, para seguir la saga |
| GET | `/partners`, `/partners/{id}` | Regla vigente de cada partner |
| GET | `/proveedores`, `/proveedores/{id}` | Estado de habilitación |
| GET | `/trabajos`, `/trabajos/{id}` | **Vista compuesta**: trabajo + partner + asignación + proveedor |
| GET | `/sagas`, `/sagas/{trabajo_id}` | Línea de tiempo de la transacción larga |
| GET | `/proyeccion` | Cuántos eventos ha aplicado |
| GET | `/health` | Sonda de vida |

`GET /trabajos/{id}` es la razón de ser del BFF: una sola llamada donde un cliente sin BFF tendría que hacer tres, a tres servicios distintos, conociendo la topología interna del sistema.

## Cómo correrlo

```bash
# con el resto del sistema arriba
docker compose up -d --build bff
curl -s localhost:8090/health
```

Documentación interactiva en `http://localhost:8090/docs` (Swagger, generada por FastAPI) y el esquema OpenAPI en `/openapi.json`.

## Pruebas

```bash
docker cp tests bff:/app/tests
docker exec bff python -m pytest tests -v
```

25 pruebas, ninguna necesita un broker vivo: el publicador se sustituye por un doble y se comprueba la traducción, que es el trabajo real del BFF. Las dos últimas codifican y releen mensajes contra los `.avsc` reales del equipo.

## Verificar que los contratos no se desviaron

```bash
python scripts/verificar_contratos.py
```

El BFF **no copia** los contratos: lee los `.avsc` montados en `/app/contratos`. Eso elimina el riesgo de una copia desactualizada — cuando el equipo agregó los cuatro eventos de la saga, el BFF los entendió sin recompilar. El script comprueba que los 14 tipos existen, que el sobre CloudEvents es idéntico en todos (de eso depende el truco del prefijo posicional) y que cada uno sobrevive un ida y vuelta.

## Configuración

Todo por variables de entorno; nada escrito en el código. Es lo que permite desplegar en GCP sin recompilar.

| Variable | Por defecto |
| --- | --- |
| `PULSAR_URL` | `pulsar://broker:6650` |
| `PULSAR_TENANT` | `hda` |
| `PULSAR_NAMESPACE` | `poc` |
| `PORT` | `8080` |
| `ESPERA_BROKER_SEGUNDOS` | `60` |
| `CONTRATOS_DIR` | `/app/contratos` |
| `CONECTAR_A_PULSAR` | `true` (las pruebas lo ponen en `false`) |

## Postman

`postman/HdA-BFF.postman_collection.json`. Las peticiones están en orden y cada una guarda en variables lo que la siguiente necesita, así que se puede correr de arriba abajo con el Collection Runner. La carpeta **4. Compensación** recorre el camino infeliz de la saga.


## Formato de cable

Productores y consumidores usan `BytesSchema`, y el payload se codifica aquí con `fastavro` contra los `.avsc`. **No es una preferencia: es la convención del equipo.** Orquestación, Acreditación y Emparejamiento producen así; si el BFF publicara con `AvroSchema(Clase)`, el broker intentaría registrar un esquema AVRO en tópicos donde los demás producen BYTES.

Hace falta además por otra razón: `evt.trabajos` lleva tres tipos de evento y `evt.asignaciones` lleva cuatro. Pulsar valida un esquema por consumidor, así que con `AvroSchema` no se podría leer un tópico multi-tipo.

Verificado contra el código real de los compañeros: el decodificador de Orquestación (`orquestacion.mensajeria.contratos.decodificar`) y el consumidor Avro de Motor reglas leen sin pérdida los bytes que produce este BFF.

## Por qué no hay endpoint de asignación

`cmd.emparejamiento` existe en el contrato pero **nadie lo consume**: Emparejamiento reacciona a `TrabajoCreado` en `evt.trabajos`, y tiene una prueba (`test_sin_asignar_proveedor.py`) que prohíbe que esa cadena aparezca en su código. Un `POST /trabajos/{id}/asignacion` publicaría en el vacío y devolvería 202 sin que pasara nada — peor que no existir.

## El saga log

El saga log **autoritativo** vive en `orquestacion-trabajos`, el coordinador: tablas `saga_asignacion` y `saga_paso`, consultables con SQL y por su `GET /sagas`.

`GET /sagas/{trabajo_id}` del BFF es una línea de tiempo **derivada** de los mismos eventos, construida sin llamar a nadie. No compite con el log del coordinador: le da al cliente la misma historia sin que el BFF tenga que hacer una llamada síncrona entre servicios.
