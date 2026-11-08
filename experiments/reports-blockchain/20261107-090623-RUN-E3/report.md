# Reporte de corrida `RUN-E3`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:06:13-0500  Fin: 2026-11-07T09:06:13-0500

## Cabecera

- `runId`: RUN-E3
- `repeticiones`: {'E3': 10}
- `cantidades`: {'E3': {'comprasPorOferta': 10}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge 1.9.0
- `params`:
  - `seleccion`: e3
  - `ofertas`: 10
  - `comprasPorOferta`: 10
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
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | **PASS** | 10 ofertas publicadas | 10 publicadas, 0 fallidas |
| R4.4 | Exactamente 1 evento Compra por oferta | **PASS** | 1 venta por oferta en todas las ofertas | 10/10 ofertas con exactamente 1 venta |
| R4.5 | Conteo total de dobles ventas igual a 0 | **PASS** | 0 dobles ventas | 0 dobles ventas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | **PASS** | diff absoluta 0 kWh (conservacion 100%) | tokenizados=1000, validados=1000, diff=0, conservacion=100.00% |
| R4.7 | Gas consumido registrado por operacion on-chain | **PASS** | gasUsed por operacion | 20 operaciones con gas, gasTotal=5259128 |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E3 | Emitido | EnergyToken | 0x76a7252433da10151c14ab90d2b51a5444f496ddb9ac6011952ca55960a89608 | 410 | 248388 |
| E3 | Compra | MarketEscrow | 0x9704c283b3ecaac71f4813738510d975328c305caf582b68fba1ecc6eabdeb83 | 412 | 277526 |
| E3 | Emitido | EnergyToken | 0x9703b340df99ebe4637b6e31ddc1dd1c0f1c4a507b3876ac347131c38eb6e847 | 416 | 248388 |
| E3 | Compra | MarketEscrow | 0x3ca34c3f06a9723850cc515ae282efb729ce5922907b8edb903d051b09692daa | 418 | 277526 |
| E3 | Emitido | EnergyToken | 0x70faa85c050dad76894c7236cebb66dbea3e0c79d70ed26d7656d8bb1a6293d1 | 421 | 248388 |
| E3 | Compra | MarketEscrow | 0x4319b5174ba7276b5fe78498bffba621d58af854b7a5e09691bb3607d3a1ecef | 423 | 277526 |
| E3 | Emitido | EnergyToken | 0xd58d4d354f0ab084d1c20ebcd30d1db29b5a2b78df00d0fb4baad9370ebf9ab9 | 426 | 248376 |
| E3 | Compra | MarketEscrow | 0xddebc626a8eb54dcc10d024e1130c363d2e2f4248775d73f30f18839590632ad | 428 | 277526 |
| E3 | Emitido | EnergyToken | 0xfecf623e1f4550b5531115a974a92d432e70713d57b9bfeddd625dd858f7dcaf | 433 | 248388 |
| E3 | Compra | MarketEscrow | 0xa8e251199fbae99e55e1862c96e5e1d22aae41febb647e4cd81cbe26f72203c5 | 435 | 277526 |
| E3 | Emitido | EnergyToken | 0x404c14b82440b00583075f10824cd82e32115b20a1efd487f9490df9404e7c84 | 440 | 248388 |
| E3 | Compra | MarketEscrow | 0xac31f0df6d050489f04277c2a7643184a2acd9ff87f9085dd04bfd9e77aa318f | 442 | 277526 |
| E3 | Emitido | EnergyToken | 0xa284b8de2b7e1b37068e8b53695f89c2a1d1025b0a912fdbfd0a371fb38b1b54 | 445 | 248388 |
| E3 | Compra | MarketEscrow | 0xd73cede09c7e7c172c5167b05c71647565c6d716cde03d833b59eb361bd3976e | 447 | 277526 |
| E3 | Emitido | EnergyToken | 0xab1b831d832b0db1378ffc671d98d1dd51f553ae9dd185fd74fb9d3c47f66a32 | 451 | 248388 |
| E3 | Compra | MarketEscrow | 0xf0b147a08916ebc7689184207ca89cd1f4462aa75026ccfb203b2efbfbccf4b2 | 453 | 277526 |
| E3 | Emitido | EnergyToken | 0x3441642d98c840f05191ce7cbaefc8365577d2c56fff019ae8337e028a16bc2f | 457 | 248388 |
| E3 | Compra | MarketEscrow | 0x8264f0952eeec4c72dd6477ebcdac5211d42168ccbff4bda20300fdc3b4f39a6 | 459 | 277526 |
| E3 | Emitido | EnergyToken | 0x9a8616c4da2e6f5e3f9c0fc4b574b8f286d01a8bbd2b3d1cbb3cd1695acc6a9e | 462 | 248388 |
| E3 | Compra | MarketEscrow | 0x65235ce6a13a36ad1490b26e33e324d8de34901c618bbc519951e84dc126abb8 | 464 | 277526 |
