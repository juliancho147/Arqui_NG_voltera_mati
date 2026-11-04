# ms_energia

Microservicio de emisión de la experimentación blockchain local (spec
`experimentos-blockchain-local`, R5.2). A partir de una generación validada emite tokens
llamando a `EnergyToken.emitir(a, id, kwh, precio, lecturaId)` **exactamente una vez por
`lecturaId`** (idempotencia por lectura). Firma con la llave custodial de la plataforma vía
el `chain_client` común y espera la confirmación on-chain con tope de 30 s, sin reintento
(R5.9, R5.10).

## Endpoints

- `POST /emisiones` — recibe una generación validada y emite (idempotente por `lecturaId`).
- `GET /healthz` — salud del servicio (patrón `health.py` del repo).

### Cuerpo de `POST /emisiones`

```json
{
  "a": "0x....",          // dirección del participante (requerido)
  "id": 7,                // id del token (uint256); o usar "fuente"+"epoca"
  "fuente": "solar",      // alternativa a "id": se deriva calcularId(fuente, epoca)
  "epoca": 202610,
  "kwh": 100,             // > 0
  "precio": 5,            // precio por kWh, > 0
  "lecturaId": "lect-1"   // clave de idempotencia; bytes32 hex o texto (keccak)
}
```

Respuesta: `{lecturaId, emitida, estado, transactionHash, gasUsed, blockNumber, error, duplicada}`.
`estado` es `confirmada | revertida | timeout`. Una reentrega del mismo `lecturaId` devuelve
`duplicada: true` sin lanzar una segunda transacción (exactamente un `Emitido` por lectura).

## Configuración (entorno)

- `PLATAFORMA_PRIVATE_KEY` — llave custodial de la plataforma (nunca en el repo).
- `RPC_URL` — endpoint de la Cadena_Local (por defecto `http://localhost:8545`).
- `DEPLOYMENT_PATH` — ruta de `deployment.json` (por defecto `ROOT/deployment.json`).
- `HEALTH_PORT` — puerto HTTP (por defecto `8080`).
- `CONFIRM_TIMEOUT_SECONDS` — tope de confirmación (por defecto `30`).

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```
