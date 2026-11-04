# Reporte de corrida `RUN-E3-10x10`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-03T22:35:23-0500  Fin: 2026-11-03T22:35:23-0500

## Cabecera

- `runId`: RUN-E3-10x10
- `repeticiones`: {'E3': 10}
- `cantidades`: {'E3': {'comprasPorOferta': 10}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge Version: 1.9.0
- `params`:
  - `seleccion`: e3
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
| E3 | Emitido | EnergyToken | 0x856bd0c35d4d3357f1b78f0068d1faa4c35fc0c5c090cc1c79005871d9ae44df | 3 | 248388 |
| E3 | Compra | MarketEscrow | 0xe44423a762861ace831f390148f964f5446234a6644349bcd5a445dd128a5874 | 5 | 277526 |
| E3 | Emitido | EnergyToken | 0x3515c95580b3c1d01aa26aeb810dfa17ee0ee1f6c1a8ad0f6074c74c4a9d3b59 | 7 | 248388 |
| E3 | Compra | MarketEscrow | 0x39329a8a3e081d400b6b39632fa8f6b96f9e20f70e04ded6401bb65c48868614 | 9 | 277526 |
| E3 | Emitido | EnergyToken | 0x6c7845d0c8d65d190b5c20c38a0773f6a0327620ef25cd867e537d02aa6c57e5 | 11 | 248388 |
| E3 | Compra | MarketEscrow | 0x28f32d437ad054415cf0bc6a94e51ff5b15b0b08f913cdf42711df4483b74eaa | 13 | 277526 |
| E3 | Emitido | EnergyToken | 0x2c26e9e0338a3af52a31321ac3c98f625dc048d93fa17526537f0c2130faf349 | 15 | 248388 |
| E3 | Compra | MarketEscrow | 0xaa46b29078cda894975a17d417acd9879c692ec57b843149e2f860e05f3b8e41 | 17 | 277526 |
| E3 | Emitido | EnergyToken | 0xaa34be90dd38276cc81c37fc22ceafae98e62eabcfb8651cde0b773dff422f30 | 20 | 248388 |
| E3 | Compra | MarketEscrow | 0xc31a65750dc74740d2945ca5f11d0a0f23dcc296973a85e1e405c5c7b3edd62f | 22 | 277526 |
| E3 | Emitido | EnergyToken | 0x7aea7bd9b366077efd0aa14aee99de90224e0317c8d2faa59ad58cceba1e2270 | 24 | 248388 |
| E3 | Compra | MarketEscrow | 0xeb49e00a788f374eb1e3bbcf09184dd84788f81bfe11f0d8d6242e5ace33d578 | 26 | 277526 |
| E3 | Emitido | EnergyToken | 0x81ab575ed8615234bbc1e041c0a757081eeefe0bf878c4a9d2271feba228aa2d | 30 | 248388 |
| E3 | Compra | MarketEscrow | 0x484e3cd99a70adf6195782656352c53dc22efb8f4f7a223be35489f284f30c30 | 32 | 277526 |
| E3 | Emitido | EnergyToken | 0x4d57170da89ffd70c471fcd0aea070b993e8367d77c3d71666fb38d961ebdd5a | 35 | 248388 |
| E3 | Compra | MarketEscrow | 0x80bcd2c2b3bae6e84b11ad88eda8dc8187d797b39ab204b022d98cb0dcdeb5b5 | 37 | 277526 |
| E3 | Emitido | EnergyToken | 0x0abb547a3203e740b80d021db811fd25c6b649979d721987ea1e08d8876da81a | 40 | 248388 |
| E3 | Compra | MarketEscrow | 0x3bce2832fbe2d1ad32a23317dc4a2532d51d8ab61282559ec7862c7a19930267 | 42 | 277514 |
| E3 | Emitido | EnergyToken | 0x2c0a92af2b0ef1a95a88e4e3781288e6609d4aacddfb1878c1a7209f0d4695a6 | 46 | 248388 |
| E3 | Compra | MarketEscrow | 0xd9a17bc72896fa2f82abb523aa224cb8a2bcb89852d0f9d983bbc210d878cd78 | 48 | 277526 |
