# Reporte de corrida `RUN-E2`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:04:41-0500  Fin: 2026-11-07T09:05:26-0500

## Cabecera

- `runId`: RUN-E2
- `repeticiones`: {'E2': 1}
- `cantidades`: {'E2': {'totalAlterados': 50, 'conteoPorForma': {'byte': 13, 'metadatos': 16, 'reemplazo': 21}}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge 1.9.0
- `params`:
  - `seleccion`: e2
  - `totalAlterados`: 50
  - `pinata`: real(subida)+local(verificacion)
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E2 | E2 — Integridad del certificado off-chain | **PASS** |

### E2 — E2 — Integridad del certificado off-chain

- Veredicto: **PASS**
- Metricas:
  - `tasaDeteccion`: 1.0
  - `deteccionesPorForma`: {'byte': 13, 'metadatos': 16, 'reemplazo': 21}
  - `falsosPositivos`: 0
  - `p95VerificacionSegundos`: 0.006028

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R3.1 | Dataset de 50 alterados con >=1 por forma | **PASS** | 50 alterados; >=1 por forma ('byte', 'metadatos', 'reemplazo') | 50 alterados; conteo {'byte': 13, 'metadatos': 16, 'reemplazo': 21} |
| R3.6 | Tasa de deteccion de alteraciones = 100% | **PASS** | 100% (todos los alterados -> ALTERADO) | 50/50 detectados (100.0%) |
| R3.8 | Falsos positivos = 0 (ningun integro marcado ALTERADO) | **PASS** | 0 falsos positivos | 0 falsos positivos; 50/50 integros OK |
| R3.10 | Latencia_p95 de verificacion <= 3 s | **PASS** | p95 <= 3.0 s | p95 = 0.0060 s sobre 100 verificaciones |

## Evidencia on-chain

_Sin eventos on-chain observados en esta corrida._
