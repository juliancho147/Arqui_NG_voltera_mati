# Reporte de corrida `RUN-E3-CONTROL`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T08:58:35-0500  Fin: 2026-11-07T08:58:35-0500

## Cabecera

- `runId`: RUN-E3-CONTROL
- `repeticiones`: {'E3-CONTROL': 1}
- `cantidades`: {'E3-CONTROL': {}}

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E3-CONTROL | E3 control — mercado SIN escrow (demuestra doble venta) | **PASS** |

### E3-CONTROL — E3 control — mercado SIN escrow (demuestra doble venta)

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| CTRL-1 | Mercado sin escrow produce doble venta bajo concurrencia | **PASS** | >1 venta (defecto esperado sin la guarda del contrato) | 10 ventas de la misma oferta con 10 compras concurrentes |

## Evidencia on-chain

_Sin eventos on-chain observados en esta corrida._
