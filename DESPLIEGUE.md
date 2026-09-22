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
sudo mkdir -p data/zookeeper data/bookkeeper
sudo chown -R 10000:10000 data/zookeeper data/bookkeeper
make todo
```

**El `chown` no es opcional en Linux.** Las imagenes de Pulsar corren como un
usuario sin privilegios (uid `10000`), pero Docker crea las carpetas montadas
como `root`. Sin esto ZooKeeper muere con `Unable to create data directory
data/zookeeper/version-2` y todo lo demas queda esperandolo. En macOS no pasa
porque Docker Desktop traduce los permisos de los volumenes.

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
| `zookeeper is unhealthy`, log dice `Unable to create data directory` | permisos de `data/` en Linux | `sudo chown -R 10000:10000 data/zookeeper data/bookkeeper` |
| `make topicos` da `Permission denied` | clon anterior al fix del bit ejecutable | `chmod +x scripts/*.sh servicios/*/scripts/*.sh` |
| `pulsar-init` sale con `exit 137` | Compose relanzo las dependencias | `docker compose up -d --no-deps <servicio>` |
| `Error while recovering ledger` en el broker | estado inconsistente en `data/` | `docker compose down -v && rm -rf data/`, despues `make infra` y `make topicos` |
| Un servicio no conecta al broker | `advertisedListeners` mal | dentro de la red de Docker debe resolver a `broker:6650` |
| `curl` a la IP no responde | falta la regla de firewall o la VM esta apagada | revisar `gcloud compute firewall-rules list` |

---

## Azure: el despliegue que esta en uso

El despliegue publico (ver el README) se hizo en **Azure for Students**, no en
GCP: la prueba gratuita de GCP pide prepago en Colombia. Los pasos 4 a 6 de
arriba son identicos; cambia solo como se crea la VM. Todo desde **Azure Cloud
Shell** (icono `>_` del portal), que ya viene autenticado.

```bash
az account set --subscription "Azure for Students"

# Una suscripcion nueva NO trae registrado el proveedor de maquinas virtuales.
# Sin esto, `az vm list-usage` devuelve vacio y parece que no hay cuota.
az provider register -n Microsoft.Compute

az group create -n hda-rg -l eastus
az vm create -g hda-rg -n hda-entrega4 --location westus \
  --image Canonical:ubuntu-24_04-lts:server-arm64:latest \
  --size Standard_B4ps_v2 --os-disk-size-gb 60 \
  --admin-username azureuser --generate-ssh-keys --public-ip-sku Standard
az vm open-port -g hda-rg -n hda-entrega4 --port 5001,5002,5004,8000,8080 --priority 900
```

Por que esa region y ese tamano, que es lo que costo encontrar:

| Restriccion | Efecto |
|---|---|
| Politica de regiones de la suscripcion | `eastus` y `eastus2` rechazadas con `RequestDisallowedByAzure`; `westus` permitida |
| Cuota por familia | 0 en las series D v6/v7; 4-10 en las B |
| Capacidad fisica en `westus` | sin maquinas x86 libres de las familias con cuota (`SkuNotAvailable`) |

La unica combinacion con region permitida, cuota **y** capacidad fue
`Standard_B4ps_v2`, que es **ARM64**. Se verifico antes que todo el stack tiene
version ARM: las imagenes `apachepulsar/pulsar:3.2.0`, `postgres:16-alpine` y
`python:3.1x-slim`, y ruedas `aarch64` de `pulsar-client`, `fastavro`, `psycopg`
y `psycopg2-binary`.

Para diagnosticar cuota y capacidad en otra suscripcion:

```bash
az vm list-usage -l westus -o table
az vm list-skus -l westus --resource-type virtualMachines --all \
  --query "[?length(restrictions)==\`0\`].name" -o tsv
```

Apagar sin perder la IP ni los datos (con `stop` Azure sigue cobrando el computo):

```bash
az vm deallocate -g hda-rg -n hda-entrega4
az vm start      -g hda-rg -n hda-entrega4
```

Al volver a prenderla los contenedores no arrancan solos: entrar por SSH y
`cd ~/HdAEntrega4 && docker compose up -d --no-deps`.
