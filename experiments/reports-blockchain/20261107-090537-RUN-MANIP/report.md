# Reporte de corrida `RUN-MANIP`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:05:37-0500  Fin: 2026-11-07T09:05:37-0500

## Cabecera

- `runId`: RUN-MANIP
- `repeticiones`: {'MANIP': 1}
- `cantidades`: {'MANIP': {}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge 1.9.0
- `params`:
  - `seleccion`: manip
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| MANIP | Pruebas negativas de manipulacion on-chain | **PASS** |

### MANIP — Pruebas negativas de manipulacion on-chain

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| CertificadoYaAnclado | reanclar otro CID sobre compra ya anclada | **PASS** | revierte (CertificadoYaAnclado) | ('0x15742b510000000000000000000000000000000000000000000000000000000000000033', '0x15742b510000000000000000000000000000000000000000000000000000000000000033') |
| SoloPlataforma | emitir desde cuenta no autorizada | **PASS** | revierte (SoloPlataforma) | ('0xfe550097', '0xfe550097') |
| OfertaNoDisponible | comprar una oferta ya vendida | **PASS** | revierte (OfertaNoDisponible) | ('0xe0d675580000000000000000000000000000000000000000000000000000000000000034', '0xe0d675580000000000000000000000000000000000000000000000000000000000000034') |

## Evidencia on-chain

_Sin eventos on-chain observados en esta corrida._
