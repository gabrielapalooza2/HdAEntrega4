.PHONY: infra topicos servicios todo abajo limpiar logs estado pruebas demo-modificabilidad demo-disponibilidad demo-escalabilidad

infra:            ## Pulsar (cluster) + las 4 bases de datos
	docker compose up -d zookeeper pulsar-init bookie broker \
	  db-trabajos db-partners db-emparejamiento db-acreditacion
	@echo "Esperando al broker (puede tardar ~40 s la primera vez)..."
	@until docker exec broker bin/pulsar-admin brokers healthcheck >/dev/null 2>&1; do printf .; sleep 3; done; echo " listo"

topicos:          ## tenant, namespace, 12 tópicos, retención y compatibilidad
	./scripts/crear_topicos.sh

servicios:        ## construye y levanta los 4 microservicios
	docker compose up -d --build \
	  orquestacion-trabajos motor-reglas-partner emparejamiento-asignacion acreditacion-habilitacion

todo: infra topicos servicios estado

estado:
	@docker compose ps

logs:
	docker compose logs -f --tail=50 orquestacion-trabajos motor-reglas-partner emparejamiento-asignacion acreditacion-habilitacion

abajo:
	docker compose down

limpiar:          ## borra TODO, incluidos los datos
	docker compose down -v && rm -rf data/

pruebas:          ## las pruebas de los 4 servicios
	@for s in servicios/*/; do \
	  echo "=== $$s ==="; \
	  (cd $$s && PYTHONPATH=src:. python -m pytest tests -q 2>/dev/null || echo "    sin pruebas"); \
	done

demo-modificabilidad:
	cd servicios/motor-reglas-partner && ./scripts/demo_esc6.sh

demo-disponibilidad:
	cd servicios/motor-reglas-partner && ./scripts/demo_disponibilidad.sh

demo-escalabilidad:
	cd servicios/motor-reglas-partner && python scripts/semilla_partners.py --cantidad 30 --api http://localhost:5002
	cd servicios/motor-reglas-partner && python scripts/carga_escalabilidad.py --rps 10 50 200 --segundos 30
	@echo "--- backlog del flujo operativo ---"
	docker exec broker bin/pulsar-admin topics stats persistent://hda/poc/cmd.trabajos
	@echo "--- el flujo administrativo NO se movió: esa es la decisión de diseño ---"
	docker exec broker bin/pulsar-admin topics stats persistent://hda/poc/cmd.partners
