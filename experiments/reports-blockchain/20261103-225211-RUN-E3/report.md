# Reporte de corrida `RUN-E3`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-03T22:52:01-0500  Fin: 2026-11-03T22:52:01-0500

## Cabecera

- `runId`: RUN-E3
- `repeticiones`: {'E3': 3}
- `cantidades`: {'E3': {'comprasPorOferta': 5}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge Version: 1.9.0
- `params`:
  - `seleccion`: e3
  - `ofertas`: 3
  - `comprasPorOferta`: 5
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E3 | E3 — Tokenizacion sin doble venta | **PASS** |

### E3 — E3 — Tokenizacion sin doble venta

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | **PASS** | 3 ofertas publicadas | 3 publicadas, 0 fallidas |
| R4.4 | Exactamente 1 evento Compra por oferta | **PASS** | 1 venta por oferta en todas las ofertas | 3/3 ofertas con exactamente 1 venta |
| R4.5 | Conteo total de dobles ventas igual a 0 | **PASS** | 0 dobles ventas | 0 dobles ventas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | **PASS** | diff absoluta 0 kWh (conservacion 100%) | tokenizados=300, validados=300, diff=0, conservacion=100.00% |
| R4.7 | Gas consumido registrado por operacion on-chain | **PASS** | gasUsed por operacion | 6 operaciones con gas, gasTotal=959685 |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E3 | Emitido | EnergyToken | 0xf0eeb90d7cd0ef72cd1890e63dfb205093d3c385ffcfa694a93adafce56f9e3f | 80 | 140289 |
| E3 | Compra | MarketEscrow | 0xe68c9461c3d98125adcbe090db3ed3aaa4b256d2322113b0d54e5e970086a47a | 82 | 179606 |
| E3 | Emitido | EnergyToken | 0x947f00346cc2364777b553c954de98c2613a821964c9902a6b1992bd2ed0553e | 84 | 140289 |
| E3 | Compra | MarketEscrow | 0xb500f214f683470ab9f51b44ac8781ba28a4a1cd7a40e489ec1eb7d48e00bf9d | 86 | 179606 |
| E3 | Emitido | EnergyToken | 0x2464fd134518e9fc8c4266a618c400ceccd05ad2ef9721303fb696ee326d93cc | 90 | 140289 |
| E3 | Compra | MarketEscrow | 0xd8e67cc5ec9e41fa64455f5243b5588cd8f0bc3053a83d9390b810b102fb5aab | 92 | 179606 |
