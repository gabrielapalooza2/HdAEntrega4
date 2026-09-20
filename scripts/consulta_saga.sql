-- Saga log de asignación. Correr contra db-trabajos:
--   docker exec -i db-trabajos psql -U trabajos -d trabajos < scripts/consulta_saga.sql
--
-- El log es append-only en saga_paso. saga_asignacion es el estado actual.
-- Coordinador de sagas: orquestacion-trabajos (columna coordinador).
-- Deben verse CUATRO servicios en saga_paso.servicio.

\echo '=== coordinador de sagas (no es un quinto microservicio) ==='
SELECT DISTINCT coordinador FROM saga_asignacion;

\echo '=== participantes en el log (se esperan 4 servicios) ==='
SELECT servicio, count(*) AS pasos
  FROM saga_paso
 GROUP BY servicio
 ORDER BY servicio;

\echo '=== transacciones largas (estado actual) ==='
SELECT saga_id,
       coordinador,
       estado,
       partner_id,
       proveedor_id,
       paso_actual,
       motivo,
       iniciada_en,
       cerrada_en,
       ROUND(EXTRACT(EPOCH FROM (COALESCE(cerrada_en, now()) - iniciada_en))::numeric, 2)
         AS duracion_segundos
  FROM saga_asignacion
 ORDER BY iniciada_en DESC;

\echo '=== timeline: pasos, confirmaciones y compensaciones ==='
SELECT s.saga_id,
       s.estado AS estado_saga,
       p.secuencia,
       p.servicio,
       p.tipo_mensaje,
       p.rol,
       p.resultado,
       p.payload,
       p.ocurrido_en
  FROM saga_asignacion s
  JOIN saga_paso p ON p.saga_id = s.saga_id
 ORDER BY s.iniciada_en DESC, p.secuencia;

\echo '=== solo compensaciones (el camino de fallo) ==='
SELECT p.saga_id,
       p.secuencia,
       p.tipo_mensaje,
       p.payload->>'proveedor_id' AS proveedor_id,
       p.payload->>'motivo'       AS motivo,
       p.payload->>'estado_trabajo' AS estado_trabajo,
       p.ocurrido_en
  FROM saga_paso p
 WHERE p.rol = 'COMPENSACION'
 ORDER BY p.ocurrido_en;

\echo '=== camino feliz cerrado ==='
SELECT saga_id, proveedor_id, cerrada_en
  FROM saga_asignacion
 WHERE estado = 'COMPLETADA'
 ORDER BY cerrada_en DESC;

\echo '=== camino compensado ==='
SELECT saga_id, proveedor_id, motivo, cerrada_en
  FROM saga_asignacion
 WHERE estado IN ('COMPENSADA', 'FALLIDA')
 ORDER BY cerrada_en DESC;
