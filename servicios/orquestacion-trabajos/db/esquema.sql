-- Esquema de Orquestacion de Trabajos.
-- Se aplica solo, al arrancar, desde infraestructura/persistencia/bd.py.
-- Todo es IF NOT EXISTS: arrancar dos veces no puede romper nada.

-- ════════════════════════════════════════════════════════════ EVENT STORE ══
-- La FUENTE DE VERDAD del agregado Trabajo. Append-only: nunca UPDATE, nunca
-- DELETE. El estado de un trabajo no se guarda, se DERIVA reproduciendo sus
-- eventos en orden de `secuencia`.
--
-- Por que en PostgreSQL y no en Pulsar: el namespace tiene retencion infinita,
-- asi que en teoria los eventos estarian ahi. Pero un topico retenido no se
-- puede CONSULTAR POR AGREGADO: para reconstruir un trabajo habria que leer el
-- topico entero filtrando. Pulsar es transporte; su retencion cubre el rezago
-- de un consumidor, no la historia de un agregado.
CREATE TABLE IF NOT EXISTS eventos_trabajo (
  trabajo_id     UUID        NOT NULL,
  secuencia      BIGINT      NOT NULL,
  tipo           TEXT        NOT NULL,
  payload        JSONB       NOT NULL,
  ocurrido_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
  correlation_id UUID        NOT NULL,

  -- ESTA PK ES EL CONTROL DE CONCURRENCIA OPTIMISTA.
  -- Dos escrituras simultaneas sobre el mismo trabajo calculan la misma
  -- `secuencia` siguiente, chocan en la clave y una recibe UniqueViolation.
  -- No hay locks ni SELECT FOR UPDATE: el conflicto se DETECTA al escribir en
  -- vez de PREVENIRSE bloqueando, que es lo que significa "optimista".
  PRIMARY KEY (trabajo_id, secuencia)
);

-- ═════════════════════════════════════════════════════════════════ OUTBOX ══
-- Resuelve la atomicidad entre PostgreSQL y Pulsar, que son dos sistemas sin
-- transaccion comun. El evento se guarda, la proyeccion se actualiza y el
-- mensaje saliente se encola EN LA MISMA TRANSACCION. Un hilo aparte drena
-- esta tabla hacia el broker.
--
-- Sin esto, una caida entre el COMMIT y el publish dejaria un trabajo que
-- existe en nuestra base y del que ningun otro servicio se entera jamas.
--
-- La garantia que da es AL MENOS UNA VEZ: si el relay publica y muere antes de
-- marcar la fila, republica al reiniciar. Por eso todo consumidor del sistema
-- tiene que ser idempotente.
CREATE TABLE IF NOT EXISTS outbox (
  id           BIGSERIAL PRIMARY KEY,
  topico       TEXT  NOT NULL,
  clave        TEXT  NOT NULL,

  -- BYTEA y no JSONB: aqui van los bytes Avro YA CODIFICADOS. Asi el hilo
  -- publicador no vuelve a codificar ni necesita conocer los contratos; solo
  -- mueve bytes a un topico. La costura (mensajeria/contratos.py) sigue siendo
  -- el unico lugar que sabe como se serializa un mensaje.
  payload      BYTEA NOT NULL,

  creado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
  publicado_en TIMESTAMPTZ
);

-- Indice PARCIAL: solo indexa lo pendiente. El outbox crece sin limite pero la
-- consulta del relay ("dame lo no publicado") mira un indice que se mantiene
-- pequenio, porque las filas ya publicadas salen de el.
CREATE INDEX IF NOT EXISTS ix_outbox_pendientes
  ON outbox (id) WHERE publicado_en IS NULL;

-- ══════════════════════════════════════════ PROYECCION: REGLAS DE PARTNER ══
-- Copia local de las reglas que publica el Motor de Reglas de Partner.
--
-- Es la pieza que hace posible la regla dura "cero condicionales por partner":
-- toda la variabilidad entre aseguradoras vive AQUI COMO DATO. Validar un
-- trabajo es leer esta tabla, no ejecutar un if por cliente.
--
-- Y es lo que nos permite NO llamar a nadie por red al crear un trabajo: si
-- Motor de Reglas esta caido, esta tabla sigue teniendo la ultima regla
-- conocida y Orquestacion sigue operando. Eso es el escenario de
-- disponibilidad.
CREATE TABLE IF NOT EXISTS proyeccion_regla_partner (
  partner_id           TEXT PRIMARY KEY,

  -- Version de la regla, tal como la emite el partner. Es el mecanismo de
  -- idempotencia contra el DESORDEN: una reentrega tardia trae una version
  -- menor a la aplicada y se descarta, para que el estado no RETROCEDA.
  regla_version        BIGINT NOT NULL,

  activo               BOOLEAN NOT NULL DEFAULT TRUE,
  sla_minutos          INT    NOT NULL,
  categorias_cubiertas TEXT[] NOT NULL,
  monto_max            NUMERIC(18,2),
  moneda               TEXT,
  actualizado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════ PROYECCION: TRABAJOS (Q) ══
-- El lado de LECTURA de CQRS. Es estado DERIVADO: si se borrara entera, se
-- podria reconstruir releyendo eventos_trabajo. La fuente de verdad es el
-- event store; esto es una cache consultable.
--
-- Existe porque responder "en que estado va el trabajo X" reproduciendo N
-- eventos es caro, y la API tiene que contestar en una sola consulta.
CREATE TABLE IF NOT EXISTS proyeccion_trabajo (
  trabajo_id            UUID PRIMARY KEY,
  estado                TEXT NOT NULL,
  partner_id            TEXT NOT NULL,
  proveedor_id          TEXT,
  categoria             TEXT NOT NULL,
  zona                  TEXT NOT NULL,
  sla_minutos           INT,

  -- Congelado al crear el trabajo. Cambiar la regla del partner manana NO
  -- mueve este valor: es el escenario de modificabilidad.
  vence_en              TIMESTAMPTZ,

  intentos              INT  NOT NULL DEFAULT 0,
  proveedores_excluidos TEXT[] NOT NULL DEFAULT '{}',

  -- Hasta que evento del event store refleja esta fila. Sirve para dos cosas:
  -- descartar reentregas viejas, y exponerla en X-Proyeccion-Secuencia para
  -- que el rezago de la proyeccion sea VISIBLE en vez de estar escondido.
  secuencia             BIGINT NOT NULL,
  actualizado_en        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indice PARCIAL para el barrido de SLA: solo interesan los trabajos en estado
-- no terminal. Los ASIGNADO/RECHAZADO/ESCALADO_MANUAL ni siquiera entran al
-- indice, asi que el barrido no crece con el historico.
CREATE INDEX IF NOT EXISTS ix_trabajo_sla_pendiente
  ON proyeccion_trabajo (vence_en)
  WHERE estado NOT IN ('ASIGNADO', 'RECHAZADO', 'ESCALADO_MANUAL');

-- ═══════════════════════════════════════════════════════════ IDEMPOTENCIA ══
-- Pulsar entrega AL MENOS UNA VEZ: recibir el mismo mensaje dos veces es
-- normal, no excepcional.
--
-- El INSERT aqui va en la MISMA TRANSACCION que el efecto del mensaje. Eso
-- cierra la ventana entre "verificar si ya lo procese" y "marcarlo como
-- procesado": o se aplican los dos o no se aplica ninguno.
--
-- Protege contra la REPETICION. El desorden lo cubre el numero de version
-- (secuencia / regla_version). Son problemas distintos y hacen falta los dos.
CREATE TABLE IF NOT EXISTS mensajes_procesados (
  message_id   UUID PRIMARY KEY,
  procesado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ══════════════════════════════════════════════════════════════ SAGA LOG ══
-- Proyeccion OBSERVADORA de la transaccion larga de asignacion.
-- No es un orquestador: no emite comandos. Vive en esta base porque el
-- identificador de la saga ES el trabajo_id, y este servicio ya reconstruye
-- esa historia. Un quinto microservicio solo para el log anadiria un
-- deployable que no es dueño de ningun agregado.
--
-- saga_asignacion  una fila por transaccion larga (estado actual)
-- saga_paso        append-only: cada mensaje de la coreografia y cada
--                  compensacion, para que un tutor pueda seguir el workflow
--                  con SQL.
CREATE TABLE IF NOT EXISTS saga_asignacion (
  saga_id        UUID PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  estado         TEXT NOT NULL,
  partner_id     TEXT,
  proveedor_id   TEXT,
  asignacion_id  TEXT,
  paso_actual    TEXT NOT NULL,
  motivo         TEXT,
  iniciada_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
  actualizada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  cerrada_en     TIMESTAMPTZ,
  CONSTRAINT saga_asignacion_estado_chk CHECK (estado IN (
    'INICIADA', 'EN_CURSO', 'COMPLETADA', 'COMPENSADA', 'FALLIDA'
  ))
);

CREATE TABLE IF NOT EXISTS saga_paso (
  id           BIGSERIAL PRIMARY KEY,
  saga_id      UUID NOT NULL REFERENCES saga_asignacion (saga_id),
  secuencia    INT  NOT NULL,
  servicio     TEXT NOT NULL,
  tipo_mensaje TEXT NOT NULL,
  rol          TEXT NOT NULL,
  resultado    TEXT NOT NULL,
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  ocurrido_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT saga_paso_rol_chk CHECK (rol IN (
    'PASO', 'COMPENSACION', 'CIERRE'
  )),
  CONSTRAINT saga_paso_unico UNIQUE (saga_id, secuencia)
);

CREATE INDEX IF NOT EXISTS ix_saga_asignacion_estado
  ON saga_asignacion (estado, actualizada_en DESC);

CREATE INDEX IF NOT EXISTS ix_saga_paso_timeline
  ON saga_paso (saga_id, secuencia);
