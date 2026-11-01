# Voltera · Etapa 3: mercado P2P de energía con blockchain

> Guía para que cualquier integrante del grupo (o una IA que lea este repositorio) pueda instalar los requisitos y reproducir lo que existe hasta hoy. Fecha de esta versión: **2026-11-01**.
> La etapa anterior (facturación por eventos en AWS) está cerrada y se documenta en [`README.md`](README.md) y [`REDESPLIEGUE.md`](REDESPLIEGUE.md). Esta guía cubre solo la etapa 3.

## 1. Estado actual

| Pieza | Estado |
|---|---|
| Clúster Kubernetes local (kind) con Anvil, DynamoDB Local e IPFS | **Hecho y verificado** |
| Contratos `EnergyToken` y `MarketEscrow` (Solidity, Foundry) | **Hechos**, 16 pruebas pasando, desplegados en Anvil local |
| Kafka/Strimzi local, microservicios `ms_*`, experimentos E1–E3 | **Pendiente** |
| Istio (service mesh) | **Pendiente** (no está instalado, ni siquiera en la etapa anterior) |
| Despliegue en AWS de la etapa 3 y en Sepolia (red pública) | **Pendiente**, se hará después de validar en local |

Todo lo hecho corre **en la máquina local**. No consume AWS y no cuesta dinero.

## 2. Qué se construye (resumen para entender el código)

Mercado P2P de energía: quien genera energía recibe tokens (1 kWh = 1 unidad) y puede venderlos a otro participante.

**Dos contratos** (carpeta [`blockchain/`](blockchain/)):

| Contrato | Responsabilidad |
|---|---|
| [`EnergyToken`](blockchain/src/EnergyToken.sol) | Token ERC-1155. El id es *fuente + época*; la cantidad son kWh. Guarda el precio por kWh de cada id (lo calcula la plataforma fuera de la cadena) y el identificador de la lectura que originó cada emisión. |
| [`MarketEscrow`](blockchain/src/MarketEscrow.sol) | Publica ofertas (bloquea los tokens), ejecuta la compra de forma atómica, emite el evento `Compra(ofertaId, vendedor, comprador, id, kwh, total)` y guarda el CID del certificado PDF (`anclar`). |

**Decisiones de diseño que no son obvias** (no las cambie sin consultarlo):

- **Modelo custodial.** La plataforma firma todas las transacciones con una sola llave. Los participantes son direcciones seudónimas *distintas* que se pasan como parámetros; el contrato no usa `msg.sender` para saber quién vende o compra. `EnergyToken` reconoce a la plataforma y al contrato de mercado como operadores de cualquier participante.
- **El precio vive en el token, por id.** La primera emisión de un id fija el precio; una emisión posterior con otro precio se revierte. Un precio nuevo (por ejemplo por temporada) corresponde a otra época y por tanto a otro id.
- **Las lecturas del medidor NO se guardan en la cadena.** `ms_oraculo` las valida y las guarda en su propia base; la cadena solo recibe el identificador de la lectura dentro del evento de emisión.
- **El pago es simulado** y ocurre fuera de la cadena (lo gestiona `ms_compra`). No hay criptomonedas de valor.
- **Cada microservicio tendrá su propia base DynamoDB** (patrón *database per service*).
- **Experimentos a escala funcional**, no de carga: E1 (lectura inválida rechazada, sin tokens), E2 (certificado alterado detectado), E3 (dos compras simultáneas de la misma oferta: una se confirma, otra se revierte, los kWh se conservan).

Microservicios previstos (nombres `ms_*`): `ms_identidad`, `ms_lecturas`, `ms_oraculo`, `ms_energia`, `ms_venta`, `ms_compra`, `ms_certificado`, `ms_facturacion`. Diagrama: [`docs/voltera_arquitectura_aws.drawio`](docs/voltera_arquitectura_aws.drawio), pestaña **Blockchain P2P · Compacto** (abrir con draw.io; el diagrama aún lista cuatro contratos y debe actualizarse a dos).

## 3. Requisitos

### 3.1 Para ejecutar lo que existe hoy (todo local)

| Requisito | Versión probada | Notas |
|---|---|---|
| Docker Desktop (macOS/Windows) o Docker Engine (Linux) | 29.x | **Mínimo 8 GB de RAM asignados a Docker** recomendado; en la máquina de referencia había 7,75 GB y funcionó. El clúster usa ≈ 1 GB. |
| [kind](https://kind.sigs.k8s.io/) | 0.33 | `brew install kind` (macOS); otros sistemas, ver su documentación. |
| kubectl | 1.3x | Cualquier versión cercana a la del clúster. |
| Node.js + npm | 24.x | Solo para descargar OpenZeppelin (`npm install`). |
| git | cualquiera | Para clonar `forge-std`. |
| Foundry | **no se instala** | Se ejecuta con la imagen Docker `ghcr.io/foundry-rs/foundry:latest`. |

Sistemas: probado en macOS (Apple Silicon). En Windows use WSL2. En Linux, `host.docker.internal` no existe por defecto: agregue `--add-host=host.docker.internal:host-gateway` a los `docker run` de la sección 4.4.

**No se necesita** cuenta de AWS, ETH, llaves ni cuentas de terceros para esta parte.

### 3.2 Para fases posteriores (aún no ejecutadas)

| Requisito | Para qué |
|---|---|
| Cuenta de AWS propia con permisos para EKS, DynamoDB, Secrets Manager, ECR, IAM, VPC | Desplegar los servicios en la nube. La etapa anterior usa la cuenta `767397902469`, región `us-east-1`; **otro usuario debe usar su propia cuenta** y ajustar los `*.tfvars` de [`infra/terraform/`](infra/terraform/). Ver [`REDESPLIEGUE.md`](REDESPLIEGUE.md) para AWS CLI, Terraform ≥ 1.6, alertas de costo y apagado. |
| Billetera de prueba propia (no usar una con dinero real) | Firmar en Sepolia. La llave va a Secrets Manager o a un archivo local ignorado por git; **nunca** al repositorio ni a un chat. |
| ETH de prueba de un faucet de Sepolia (≈ 0,1 ETH basta) | Pagar el gas de los despliegues y de las pocas transacciones de los experimentos. |
| Nodo RPC de Sepolia (cuenta gratuita en Alchemy o Infura) | Conectarse a la red pública. |
| Cuenta de pinning de IPFS (por ejemplo Pinata, plan gratuito) | Guardar los certificados PDF fuera de la cadena. En local se usa un nodo Kubo. |

## 4. Reproducir lo que existe (paso a paso)

Todos los comandos se ejecutan desde la carpeta `codigo_fuente_voltera/`.

### 4.1 Crear el clúster local
```bash
kind create cluster --config k8s/local/kind-config.yaml --kubeconfig "$HOME/.kube/voltera-local.yaml" --wait 120s
export KUBECONFIG="$HOME/.kube/voltera-local.yaml"     # en cada terminal nueva
kubectl get nodes                                       # voltera-local-control-plane Ready
```

### 4.2 Desplegar Anvil, DynamoDB Local e IPFS
```bash
kubectl apply -f k8s/local/00-infra-apoyo.yaml
kubectl -n voltera rollout status deploy/anvil deploy/dynamodb-local deploy/ipfs --timeout=240s
```
Anvil usa el chain-id de Sepolia (11155111) y queda accesible en `http://localhost:8545`:
```bash
curl -s -X POST localhost:8545 -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'     # {"result":"0xaa36a7"}
```

### 4.3 Preparar y probar los contratos
```bash
cd blockchain
npm install
git clone --depth 1 --branch v1.9.4 https://github.com/foundry-rs/forge-std.git lib/forge-std
docker run --rm -v "$PWD":/app -w /app ghcr.io/foundry-rs/foundry:latest "forge test -vv"
```
Resultado esperado: `16 tests passed, 0 failed`.

### 4.4 Desplegar los contratos en Anvil
```bash
# PK = cuenta 0 de Anvil: llave PÚBLICA de prueba, sin valor. Solo sirve en la cadena local.
PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
docker run --rm -v "$PWD":/app -w /app ghcr.io/foundry-rs/foundry:latest \
  "forge script script/Desplegar.s.sol --rpc-url http://host.docker.internal:8545 --private-key $PK --broadcast"
```
Imprime las direcciones de `EnergyToken` y `MarketEscrow`. Con un Anvil nuevo salen siempre las mismas porque la cuenta y el orden son los mismos: `EnergyToken 0x5FbDB2315678afecb367f032d93F642f64180aa3`, `MarketEscrow 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512`.

### 4.5 Reiniciar o borrar
```bash
kubectl -n voltera rollout restart deploy/anvil   # Anvil guarda todo en memoria: hay que repetir 4.4
kind delete cluster --name voltera-local          # borra todo el clúster local
```
La base DynamoDB Local también es en memoria: se pierde al reiniciar su pod.

## 5. Reglas para quien opere este repositorio (personas e IAs)

1. **Use siempre `KUBECONFIG="$HOME/.kube/voltera-local.yaml"`** para el clúster local. El contexto por defecto de `~/.kube/config` puede apuntar a un clúster **real de AWS**; no ejecute `kubectl apply/delete` sin confirmar el contexto con `kubectl config current-context`.
2. **No suba llaves privadas, `.env` ni archivos de estado de Terraform.** Los `*.tfvars` de [`infra/terraform/base/`](infra/terraform/base/) ya estaban en el repositorio desde la etapa anterior; no agregue datos sensibles en ellos.
3. La llave de la sección 4.4 es pública y solo vale en Anvil. Para Sepolia se usa una billetera propia, distinta.
4. No toque contenedores de Docker que no sean de este proyecto: la máquina de referencia tenía otros en ejecución.
5. Para los contratos use Foundry por Docker; los comentarios del código están en español y explican cada función.
6. Si cambia el diseño de los contratos o de los servicios, actualice esta guía y el diagrama.

## 6. Mapa de archivos de la etapa 3

| Ruta | Contenido |
|---|---|
| [`blockchain/`](blockchain/) | Contratos, pruebas, script de despliegue y su [README](blockchain/README.md). |
| [`k8s/local/`](k8s/local/) | `kind-config.yaml` y `00-infra-apoyo.yaml` (Anvil, DynamoDB Local, IPFS). |
| [`docs/voltera_arquitectura_aws.drawio`](docs/voltera_arquitectura_aws.drawio) | Copia del diagrama de arquitectura (el original vive fuera del repositorio; puede diferir). |

## 7. Próximos pasos previstos

1. Kafka (Strimzi) local con un solo broker.
2. Servicios `ms_oraculo` y `ms_energia` → experimento E1.
3. `ms_venta` y `ms_compra` → experimento E3.
4. `ms_certificado` con IPFS → experimento E2.
5. Chain Event Listener y adaptación de `ms_facturacion`.
6. Istio, y luego despliegue en AWS y en Sepolia (también puede probarse antes en Remix: <https://remix.ethereum.org>).
