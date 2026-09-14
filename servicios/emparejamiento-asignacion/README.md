# Emparejamiento y asignación — Entrega 4

Hexágono `dominio/ aplicacion/ infraestructura/` (misma convención que `modulos/trabajos`, `cumplimiento` y `seguimiento`). Matching optimista contra proyecciones locales. Cero HTTP/gRPC a otros MS. No implementa Orquestación, Motor reglas, Acreditación ni ACL. No muta Avro.

Este directorio es un **microservicio FastAPI + Pulsar aparte** del Flask de orquestación de trabajos (Entrega 3). El guion en el nombre coincide con `service_name=emparejamiento-asignacion`; se corre con `PYTHONPATH` apuntando aquí, no como `import hda.modulos.emparejamiento-asignacion`.

Contratos: CloudEvents (`id`, `time`, `ingestion`, `specversion`, `type`, `datacontenttype`, `service_name`, `correlation_id`) + `data`. Fuente original: hogaralpes `entrega4/contratos/`. Este servicio copia los Record que produce/consume en `infraestructura/schema/v1/` y lee los `.avsc` vendidos en `contratos/esquemas/` tal cual (solo los tópicos que consume o produce).

## Hexágono

```
dominio/                 Asignacion + emparejar()  (sin Pulsar ni SQL)
aplicacion/              casos de uso (sobre CloudEvents)
infraestructura/http     FastAPI GET /asignaciones/{trabajo_id}  GET /health
infraestructura/persistencia   SQLAlchemy (CRUD)
infraestructura/mensajeria     Pulsar Avro (esquemas oficiales)
infraestructura/schema/v1      Record copiados (no se importa generar.py)
infraestructura/         config, DB, bootstrap Pulsar
contratos/esquemas/      .avsc necesarios para correr (copia, semántica intacta)
```

## Qué hace

1. Hidrata `proyeccion_regla_partner` desde `persistent://hda/poc/evt.partners` (compactado, Shared + Earliest). Usa `data.red_homologada`; `data.vigencia_hasta=0` = sin fin.
2. Hidrata `proyeccion_habilitacion` desde `persistent://hda/poc/evt.proveedores` (compactado).
3. Consume `TrabajoCreado` en `evt.trabajos` (filtra `type`; ack+skip de `TrabajoAsignado` y `TrabajoRechazado`).
4. Persiste `Asignacion`, publica `TrabajoAsignado` (único productor). Clave `data.trabajo_id`. `service_name=emparejamiento-asignacion`. `correlation_id` del creado. `data.origen_habilitacion=PROYECCION_LOCAL`. `data.partner_id` y `data.sla_vence_en` salen del trabajo congelado. `verificado_en` queda en el agregado local (lectura de proyecciones); ya no viaja en el evento de bus.
5. Consume `AsignacionRechazadaPorHabilitacion`: marca `RECHAZADO`. No reasigna. No publica otro `TrabajoAsignado`. **No implementa `AsignarProveedor`** (comando opcional E4 / saga E5).

Matching: `HABILITADO` + categoría + ciudad + `vigente_hasta` 0/null/futuro; luego `red_homologada` si no está vacía; `proveedor_id` ordenado. Sin candidatos: log + `asignacion_fallida`, no publica.

Suscripciones: `Shared` (carga de estado) y `Key_Shared` (por `trabajo_id`). Nunca `Exclusive`. No hay consumidor de `cmd.emparejamiento`.

## Levantar

Desde la **raíz del repo** `hda` (compose compartido; este servicio no arranca los otros MS):

```bash
docker compose up -d --build
docker compose --profile sim run --rm simulador
```

Pruebas unitarias del módulo:

```bash
pip install -r src/hda/modulos/emparejamiento-asignacion/requirements.txt
make pruebas-emparejamiento
```

Env: `PULSAR_URL`, `PULSAR_ADMIN_URL`, `DATABASE_DSN`, `CONTRATOS_DIR` (ver `.env.example`). Sin secretos.

API local: `http://localhost:8000/health` y `GET /asignaciones/{trabajo_id}`.

## Contratos

Lee `contratos/esquemas/**/*.avsc` de este módulo. No los modifica. Semántica idéntica a hogaralpes `entrega4/contratos/esquemas/` para los records que este MS usa.

`evt.trabajos` lleva tres records Avro distintos. El schema registry nativo de Pulsar guarda un esquema por tópico (`BACKWARD`). Este servicio registra Avro en los tópicos de un solo tipo y, en `evt.trabajos`, serializa/deserializa con los `.avsc` oficiales (bytes Avro) filtrando por `type`.
