# Despliegue en GCP

Una VM de Compute Engine corriendo el mismo `docker-compose.yml` del repo.

**Por que una VM y no Kubernetes ni Cloud Run**, en una linea cada uno:

- **Kubernetes:** `scripts/crear_topicos.sh` y las demos de calidad corren
  `docker exec broker bin/pulsar-admin ...`. En K8s eso hay que reescribirlo como
  Job de bootstrap y `kubectl exec`, ademas de publicar las cuatro imagenes en
  Artifact Registry, porque GKE no construye desde el repo.
- **Cloud Run:** los servicios corren hilos de fondo dentro del proceso —el relay
  del outbox, los consumidores de Pulsar y el barrido de SLA cada 30 s—. Cloud Run
  estrangula la CPU fuera de las peticiones HTTP y escala a cero: un consumidor de
  Pulsar ahi deja de consumir.
- **VM + Compose:** el `docker-compose.yml` ES la arquitectura. Moverlo tal cual
  no cambia ni una linea de codigo, ni un script, ni una demo.

---

## 1. En tu maquina

```bash
brew install --cask google-cloud-sdk      # macOS
gcloud auth login
gcloud config set project TU_PROYECTO
gcloud services enable compute.googleapis.com
```

## 2. Crear la VM

```bash
gcloud compute instances create hda-entrega4 \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=60GB \
  --boot-disk-type=pd-balanced \
  --tags=hda
```

`e2-standard-4` (4 vCPU / 16 GB) no es holgura de mas: el compose **no fija
limites de memoria**, asi que broker y bookie toman los defaults de la imagen de
Pulsar, que son generosos, y encima van cuatro Postgres y cuatro procesos Python.

### IP estatica

Sin esto, apagar la VM cambia la IP y se caen las URLs del documento de entrega.

```bash
gcloud compute addresses create hda-ip --region=us-central1
gcloud compute instances delete-access-config hda-entrega4 --zone=us-central1-a \
  --access-config-name="external-nat"
gcloud compute instances add-access-config hda-entrega4 --zone=us-central1-a \
  --access-config-name="external-nat" \
  --address=$(gcloud compute addresses describe hda-ip --region=us-central1 --format='get(address)')
```

## 3. Firewall: solo las APIs

```bash
gcloud compute firewall-rules create hda-http \
  --allow=tcp:5001,tcp:5002,tcp:5004,tcp:8000,tcp:8080 \
  --target-tags=hda \
  --source-ranges=0.0.0.0/0
```

**No abras 5432-5435.** El compose publica los cuatro Postgres al host con
credenciales triviales (`trabajos/trabajos`, `partners/partners`...). GCP niega
todo el ingreso por defecto, asi que mientras no exista una regla que los abra
quedan inalcanzables desde afuera.

El 8080 es el admin de Pulsar y **no tiene autenticacion**. Si quieres apretar,
crea una regla aparte para ese puerto con `--source-ranges=TU_IP/32`.

## 4. Instalar Docker en la VM

```bash
gcloud compute ssh hda-entrega4 --zone=us-central1-a
```

Ya adentro:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git make
sudo usermod -aG docker $USER
exit
```

Hay que **salir y volver a entrar** para que la sesion tome el grupo `docker`.

## 5. Levantar

```bash
gcloud compute ssh hda-entrega4 --zone=us-central1-a

git clone https://github.com/gabrielapalooza2/HdAEntrega4.git
cd HdAEntrega4
make todo
```

`make todo` encadena `infra` -> `topicos` -> `servicios`. La construccion de las
cuatro imagenes tarda varios minutos la primera vez.

> Si clonaste antes del commit que marco los `.sh` como ejecutables, `make
> topicos` falla con `Permission denied` y **no se crea ningun topico**. Se
> arregla con `chmod +x scripts/*.sh servicios/*/scripts/*.sh`.

## 6. Verificar

```bash
IP=$(gcloud compute instances describe hda-entrega4 --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

curl http://$IP:5001/health    # orquestacion de trabajos
curl http://$IP:5002/health    # motor de reglas de partner
curl http://$IP:8000/health    # emparejamiento y asignacion
curl http://$IP:5004/health    # acreditacion y habilitacion
curl http://$IP:8080/admin/v2/brokers/health
```

---

## Re-desplegar un servicio

```bash
cd ~/HdAEntrega4 && git pull
docker compose up -d --build --no-deps orquestacion-trabajos
```

**`--no-deps` no es opcional en un re-despliegue.** Sin el, Compose relanza
`pulsar-init`, que vuelve a correr `initialize-cluster-metadata` sobre un cluster
ya inicializado, falla con `exit 137` y aborta el arranque.

## Apagar cuando no se usa

```bash
gcloud compute instances stop hda-entrega4 --zone=us-central1-a
```

Son del orden de USD 0.13/hora. Los datos viven en `./data/` dentro del disco de
la VM y sobreviven al apagado.

## Postman

`postman/HdA-Entrega4.postman_environment.json` apunta a `localhost`. Hay que
cambiar los hosts por la IP de la VM.

## Clientes Pulsar desde afuera

El compose anuncia `external:pulsar://127.0.0.1:6650`, que sirve para un cliente
corriendo **dentro de la VM**. Para conectar un cliente desde tu portatil —por
ejemplo `escuchar.py`— hay que poner ahi la IP publica y abrir el 6650. Las demos
de calidad no lo necesitan: pegan por HTTP a 5001 y 5002.

---

## Fallos conocidos

| Sintoma | Causa | Arreglo |
|---|---|---|
| `make topicos` da `Permission denied` | clon anterior al fix del bit ejecutable | `chmod +x scripts/*.sh servicios/*/scripts/*.sh` |
| `pulsar-init` sale con `exit 137` | Compose relanzo las dependencias | `docker compose up -d --no-deps <servicio>` |
| `Error while recovering ledger` en el broker | estado inconsistente en `data/` | `docker compose down -v && rm -rf data/`, despues `make infra` y `make topicos` |
| Un servicio no conecta al broker | `advertisedListeners` mal | dentro de la red de Docker debe resolver a `broker:6650` |
| `curl` a la IP no responde | falta la regla de firewall o la VM esta apagada | revisar `gcloud compute firewall-rules list` |
