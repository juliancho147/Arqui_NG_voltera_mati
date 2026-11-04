# Implementation Plan: experimentos-blockchain-local

## Overview

Plan de implementación del MVP de validación experimental blockchain (punto 07, Entrega 4) contra una cadena local Anvil. La construcción es incremental: primero el cliente de cadena común y el orquestador del entorno (`deployment.json`), luego los cinco microservicios que tocan la cadena, después el `Lector_Eventos`, luego cada experimento (E1, E2, E3) con su generación de casos y medición, y finalmente el runner CLI y el `Reporte_Resultados` con el cableado extremo a extremo.

Todo el código nuevo es Python 3.14 (según el diseño), reutiliza los contratos Foundry ya desplegados en `blockchain/` sin modificarlos, carga el ABI desde `blockchain/out/<Contrato>.sol/<Contrato>.json`, habla con la cadena vía `web3.py` y escribe los microservicios siguiendo el patrón de `services/` y el runner siguiendo el patrón de `experiments/runner/`. El nuevo paquete runner vive en `experiments/runner-blockchain/`. Las pruebas basadas en propiedades usan Hypothesis (≥100 iteraciones por propiedad, etiqueta `Feature: experimentos-blockchain-local, Property N: ...`).

## Tasks

- [x] 1. Preparar el esqueleto del proyecto y el cliente de cadena común
  - [x] 1.1 Crear la estructura del paquete runner blockchain y dependencias
    - Crear `experiments/runner-blockchain/` con `runner_blockchain/__init__.py`, `requirements.txt` (web3, hypothesis, base58/multiformats o equivalente para CIDv1), `requirements-dev.txt` (pytest, hypothesis) y `pytest.ini`, siguiendo el estilo de `experiments/runner/`
    - Crear `tests/` del paquete y un `README.md` breve que apunte a este plan
    - _Requirements: R5, R7_

  - [x] 1.2 Implementar el cliente de cadena común `chain_client`
    - Crear `runner_blockchain/chain/chain_client.py` que: resuelva la ruta de `blockchain/out/` relativa al repo, cargue el campo `abi` de `blockchain/out/EnergyToken.sol/EnergyToken.json` y `blockchain/out/MarketEscrow.sol/MarketEscrow.json`, construya objetos `Contract` de `web3.py`, lea `PLATAFORMA_PRIVATE_KEY` del entorno y firme transacciones con `eth_account`
    - Exponer helpers para enviar transacción firmada, esperar recibo con tope de 30 s (sin reintento) y devolver `gasUsed`, `transactionHash`, `blockNumber` y estado (confirmada/revertida/timeout)
    - Exponer helper para asignación de nonces secuenciales explícitos (una lectura de `eth_getTransactionCount`, reparto `nonce, nonce+1, ...`) para el envío concurrente de E3
    - _Requirements: R5.7, R5.9, R5.10_

  - [ ]* 1.3 Escribir pruebas unitarias del `chain_client`
    - Verificar carga de ABI desde `out/`, lectura de `PLATAFORMA_PRIVATE_KEY`, comportamiento de timeout (≤30 s sin reintento) y reparto de nonces, con mocks del proveedor web3
    - _Requirements: R5.9, R5.10_

- [x] 2. Implementar el orquestador del Entorno_Experimental y `deployment.json`
  - [x] 2.1 Implementar el arranque de Anvil y el despliegue de contratos
    - Crear `runner_blockchain/orquestador/entorno.py` que arranque `anvil --chain-id 11155111 --port 8545` como proceso hijo y haga polling de `eth_chainId`/`eth_blockNumber` hasta responder, con tope de 30 s
    - Si el puerto 8545 está en uso o se agota el timeout: no desplegar y registrar error con la causa
    - Desplegar con `forge script script/Desplegar.s.sol --rpc-url http://localhost:8545 --private-key $PLATAFORMA_PRIVATE_KEY --broadcast` (cwd `blockchain/`); el script ya ejecuta `configurarMercado`
    - Extraer direcciones desplegadas de la salida del script / `blockchain/broadcast/` y escribir `deployment.json` (chainId, rpcUrl, plataforma, contratos EnergyToken/MarketEscrow, herramientas Foundry, desplegadoEn)
    - Si un despliegue falla: detener, dejar experimentos sin habilitar y registrar contrato afectado y motivo
    - _Requirements: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6_

  - [x] 2.2 Implementar el cargador de `deployment.json`
    - Crear `runner_blockchain/chain/deployment.py` que lea `deployment.json` y resuelva direcciones y RPC para el runner, los microservicios y el lector de eventos
    - _Requirements: R1.3_

  - [ ]* 2.3 Escribir pruebas de integración/smoke del orquestador
    - Verificar readiness de Anvil ≤30 s, `deployment.json` bien formado, y manejo de puerto ocupado, timeout de readiness y fallo de despliegue (contrato + motivo registrados)
    - _Requirements: R1.1, R1.2, R1.6_

  - [x] 2.4 Documentar herramientas del entorno
    - Crear/actualizar el README del entorno indicando Foundry 1.9.0, Node.js 24 y Python 3.14, y que Docker no es requerido para este MVP
    - _Requirements: R1.7_

- [x] 3. Checkpoint - cadena y entorno listos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar los microservicios de emisión (ms_oraculo, ms_energia)
  - [x] 4.1 Implementar `ms_oraculo` con validación real y determinista
    - Crear `services/ms-oraculo/` (patrón `main.py`/`config.py`/`health.py` + `requirements.txt` + `tests/`) con `POST /lecturas` y `GET /healthz`
    - Implementar validación real y determinista de las tres categorías: valor alterado (contra referencia del stub de medidor/clima), medidor desconocido (padrón) y lectura duplicada (lecturaId / medidor+época); misma entrada ⇒ mismo veredicto
    - Rechazo: `{aceptada:false, motivo, categoria}` sin emitir; aceptación: `{aceptada:true}` + publicar `GeneracionValidada` (HTTP a `ms_energia`)
    - Stubs de medidor/clima con respuestas predefinidas
    - _Requirements: R2.2, R2.3, R2.4, R5.1, R5.8_

  - [ ]* 4.2 Prueba de propiedad: rechazo sin emisión de lecturas inválidas
    - **Property 1: Toda lectura inválida se rechaza sin emitir tokens**
    - **Validates: Requirements R2.3, R2.5, R2.6**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 1: ...`; generar lecturas de las tres categorías de invalidez
    - _Requirements: R2.3, R2.5, R2.6_

  - [ ]* 4.3 Prueba de propiedad: determinismo de la validación del oráculo
    - **Property 3: La validación del oráculo es determinista**
    - **Validates: Requirements R2.2**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 3: ...`; validar dos veces la misma lectura y comparar veredicto y categoría
    - _Requirements: R2.2_

  - [x] 4.4 Implementar `ms_energia` con emisión idempotente por lectura
    - Crear `services/ms-energia/` (mismo patrón) con `POST /emisiones` y `GET /healthz`
    - Llamar `EnergyToken.emitir(a, id, kwh, precio, lecturaId)` exactamente una vez por `lecturaId` (idempotencia), firmar con la llave de la plataforma vía `chain_client` y esperar confirmación ≤30 s sin reintento
    - _Requirements: R5.2, R5.9, R5.10_

  - [ ]* 4.5 Prueba de propiedad: emisión y aceptación de lecturas válidas
    - **Property 2: Toda lectura válida se acepta y origina exactamente una emisión**
    - **Validates: Requirements R2.4, R5.2**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 2: ...`; mock del cliente de cadena para contar `GeneracionValidada` y `Emitido` por `lecturaId`
    - _Requirements: R2.4, R5.2_

  - [ ]* 4.6 Prueba de propiedad: idempotencia de la emisión por lectura
    - **Property 4: La emisión es idempotente por lectura**
    - **Validates: Requirements R5.2**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 4: ...`; entregar el mismo `lecturaId` más de una vez y verificar exactamente un `Emitido`
    - _Requirements: R5.2_

- [x] 5. Implementar los microservicios de mercado (ms_venta, ms_compra)
  - [x] 5.1 Implementar `ms_venta`
    - Crear `services/ms-venta/` (mismo patrón) con `POST /ofertas` → `MarketEscrow.publicar(vendedor, id, kwh)` (devuelve `ofertaId`) y `POST /ofertas/{id}/cancelar` → `MarketEscrow.cancelar(ofertaId)`; firma custodial y confirmación ≤30 s
    - _Requirements: R5.3, R5.9, R5.10_

  - [x] 5.2 Implementar `ms_compra` con modo concurrente
    - Crear `services/ms-compra/` (mismo patrón) con `POST /compras` `{ofertaId, comprador}` → `MarketEscrow.comprar(ofertaId, comprador)`; devolver éxito/reversión con hash de tx
    - Exponer modo de disparo concurrente (envío en paralelo con `concurrent.futures` y nonces explícitos del `chain_client`) usado por E3
    - _Requirements: R5.4, R5.9, R5.10_

  - [ ]* 5.3 Prueba de propiedad: compra sobre oferta no Activa revierte sin efectos
    - **Property 9: Comprar una oferta no Activa revierte sin efectos**
    - **Validates: Requirements R4.3**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 9: ...`; generar ofertas en estado Vendida/Cancelada/Inexistente y verificar reversión con `OfertaNoDisponible` sin cambios de estado ni balances
    - _Requirements: R4.3_

- [x] 6. Implementar `ms_certificado` con Pinata y fallback de CID por contenido
  - [x] 6.1 Implementar el almacén de contenido direccionable y el cálculo de CIDv1
    - Crear `services/ms-certificado/contenido.py` que calcule el CIDv1 del contenido (multihash `sha2-256`, codec `raw`) igual que IPFS y guarde/recupere el blob indexado por ese CID (fallback local)
    - _Requirements: R3.3_

  - [ ]* 6.2 Prueba de propiedad: el CID está determinado por el contenido
    - **Property 5: El CID está determinado por el contenido**
    - **Validates: Requirements R3.2, R3.3**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 5: ...`; mismo contenido ⇒ mismo CID; contenidos distintos ⇒ CIDs distintos; equivalencia fallback/IPFS
    - _Requirements: R3.2, R3.3_

  - [x] 6.3 Implementar la integración con Pinata y el servicio de certificado
    - Crear `services/ms-certificado/` (mismo patrón) con `GET /healthz`, `POST /certificados` `{ofertaId, datosCompra}` (genera PDF, sube a Pinata `pinFileToIPFS` con JWT de `PINATA_JWT`, obtiene CID) y `POST /verificaciones` `{ofertaId}`
    - Solo si el guardado tuvo éxito, llamar `MarketEscrow.anclar(ofertaId, cid)`; si Pinata falla al guardar, no anclar y registrar la compra afectada
    - Fallback al almacén local cuando no haya internet/credenciales; credenciales nunca en repo ni en reporte
    - Verificación: leer CID anclado (`certificado(ofertaId)`), recuperar contenido (Pinata `gateway` o fallback), recalcular identificador por contenido y devolver `{veredicto: INTEGRO|ALTERADO|ERROR, ...}`
    - _Requirements: R3.2, R3.3, R3.4, R3.5, R3.7, R3.11, R3.12, R5.5, R5.6, R5.11_

  - [ ]* 6.4 Prueba de propiedad: round-trip de integridad del certificado
    - **Property 6: Round-trip de integridad del certificado**
    - **Validates: Requirements R3.5, R3.6, R3.7, R3.8**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 6: ...`; íntegro ⇒ INTEGRO; alterado (byte, metadatos, reemplazo) ⇒ ALTERADO
    - _Requirements: R3.5, R3.6, R3.7, R3.8_

  - [ ]* 6.5 Prueba de propiedad: CID ausente o contenido no recuperable nunca es ÍNTEGRO
    - **Property 7: Verificación con CID ausente o contenido no recuperable nunca es ÍNTEGRO**
    - **Validates: Requirements R3.11, R3.12**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 7: ...`; generar CID inexistente / contenido no recuperable y verificar veredicto ERROR (ni ÍNTEGRO ni falso positivo)
    - _Requirements: R3.11, R3.12_

- [x] 7. Checkpoint - microservicios listos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implementar el Lector_Eventos
  - [x] 8.1 Implementar la lectura de eventos on-chain
    - Crear `runner_blockchain/eventos/lector.py` que lea `Emitido` (EnergyToken), `Compra` y `Anclado` (MarketEscrow) con `eth_getLogs` sobre las direcciones de `deployment.json`
    - Asociar cada evento al `runId` y registrar `transactionHash`, `blockNumber` y `gasUsed` (del recibo cuando aplique); entregar al runner la lista al terminar la corrida
    - Si la cadena no responde en 30 s, registrar error de indisponibilidad; sin bus, checkpoints ni dedup
    - _Requirements: R6.1, R6.2, R6.3, R6.4_

  - [ ]* 8.2 Prueba de propiedad: todo evento observado queda trazado a la corrida
    - **Property 11: Todo evento observado queda trazado a la corrida**
    - **Validates: Requirements R6.2, R6.3**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 11: ...`; para todo evento observado, el registro contiene `runId`, `transactionHash` y `blockNumber`
    - _Requirements: R6.2, R6.3_

- [x] 9. Implementar E1 — Integridad del Oracle
  - [x] 9.1 Implementar la generación de casos y el flujo de E1
    - Crear `runner_blockchain/experimentos/e1.py` con generador por semilla fija (derivada de `runId`/parámetros) que produzca 200 inválidas (≥50 por categoría) + 200 válidas
    - Inyectar casos a `ms_oraculo`, completar el flujo `GeneracionValidada`→`ms_energia`→`Emitido`, medir latencia `LecturaRegistrada`→`GeneracionValidada` con `time.monotonic`, y abortar con FAIL si cadena/oráculo no responden 30 s
    - Calcular tasa de rechazo, 0 `Emitido` por inválidas (vía Lector_Eventos), p95 ≤10 s y veredicto PASS/FAIL
    - _Requirements: R2.1, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10_

  - [ ]* 9.2 Prueba unitaria del dataset de E1
    - Aseverar 200 inválidas (≥50 por categoría) + 200 válidas y reproducibilidad por semilla
    - _Requirements: R2.1_

- [x] 10. Implementar E2 — Integridad del certificado
  - [x] 10.1 Implementar la generación de alteraciones y el flujo de E2
    - Crear `runner_blockchain/experimentos/e2.py` con generador por semilla fija que parta de certificados íntegros anclados y produzca 50 alterados en las tres formas (≥1 por forma)
    - Verificar cada caso vía `ms_certificado`, medir latencia de verificación, calcular tasa de detección (100%), falsos positivos (0), p95 ≤3 s y veredicto PASS/FAIL
    - _Requirements: R3.1, R3.6, R3.8, R3.9, R3.10, R3.13_

  - [ ]* 10.2 Prueba unitaria del dataset de E2
    - Aseverar 50 alterados con ≥1 por forma (byte, metadatos, reemplazo) y reproducibilidad por semilla
    - _Requirements: R3.1_

- [x] 11. Implementar E3 — Tokenización sin doble venta
  - [x] 11.1 Implementar el flujo concurrente y las métricas de E3
    - Crear `runner_blockchain/experimentos/e3.py` que publique 1 oferta Activa (vía `ms_venta`), lance 100 compras concurrentes (vía modo concurrente de `ms_compra`) y repita sobre 10 ofertas distintas
    - Vía Lector_Eventos contar `Compra` por oferta (==1), contabilizar dobles ventas (==0), sumar gas por operación y verificar conservación de kWh (tokenizados == validados, diff 0); veredicto PASS/FAIL
    - _Requirements: R4.1, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9_

  - [ ]* 11.2 Prueba de propiedad: exactamente una venta por oferta bajo concurrencia
    - **Property 8: Exactamente una venta por oferta bajo concurrencia**
    - **Validates: Requirements R4.2, R4.4, R4.5**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 8: ...`; para 2 ≤ k ≤ 100 compras concurrentes, exactamente 1 confirma y k−1 revierten con `OfertaNoDisponible`
    - _Requirements: R4.2, R4.4, R4.5_

  - [ ]* 11.3 Prueba de propiedad: conservación de kWh
    - **Property 10: Conservación de kWh**
    - **Validates: Requirements R4.6**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 10: ...`; suma de kWh tokenizados (`Emitido`) == suma de kWh validados (diff absoluta 0)
    - _Requirements: R4.6_

  - [ ]* 11.4 Prueba de ejemplo: conteo agregado de E3
    - Verificar exactamente 1 `Compra` por oferta y 0 dobles ventas en las 10 repeticiones, y gas registrado por operación
    - _Requirements: R4.4, R4.5, R4.7_

- [x] 12. Implementar el Runner CLI y el Reporte_Resultados
  - [x] 12.1 Implementar el CLI del runner
    - Crear `runner_blockchain/cli.py` y `runner_blockchain/__main__.py` con `python -m runner_blockchain e1|e2|e3|all [opciones]` (inspirado en `experiments/runner/`)
    - Rechazar selección no reconocida sin ejecutar nada y registrar el error; orquestar entorno, inyección, ejecución y recolección por experimento
    - _Requirements: R7.6, R7.7_

  - [x] 12.2 Implementar el Reporte_Resultados (JSON + Markdown)
    - Crear `runner_blockchain/reporte.py` que escriba `report.json` y `report.md` por corrida reutilizando el modelo `ExperimentResult`/`Criterion`
    - Incluir cabecera (runId, inicio/fin, cantidades, repeticiones, contratos, herramientas), por experimento veredicto PASS/FAIL + criterios + métricas, evidencia on-chain (eventos con txHash/blockNumber + gas) y frontera on/off-chain; FAIL marca métrica incumplida con valor y umbral; credenciales de Pinata nunca aparecen
    - Veredicto reproducible por semilla fija
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5_

  - [ ]* 12.3 Prueba de propiedad: veredicto PASS/FAIL correcto y reproducible
    - **Property 12: El veredicto PASS/FAIL es correcto y reproducible**
    - **Validates: Requirements R7.4, R7.5**
    - Hypothesis, ≥100 iteraciones, etiqueta `Feature: experimentos-blockchain-local, Property 12: ...`; PASS sii todas las métricas cumplen umbral; FAIL registra métrica(s) incumplida(s) con valor y umbral; misma semilla/parámetros ⇒ mismo veredicto
    - _Requirements: R7.4, R7.5_

  - [ ]* 12.4 Prueba de ejemplo: rechazo de selección inválida en el CLI
    - Verificar que una selección distinta de e1/e2/e3/all rechaza la corrida sin ejecutar nada y registra el error
    - _Requirements: R7.7_

- [x] 13. Integración final y cableado extremo a extremo
  - [x] 13.1 Cablear el flujo completo `all`
    - Conectar orquestador → arranque/despliegue → levantar microservicios (readiness por `/healthz`) → ejecutar E1/E2/E3 → Lector_Eventos → Reporte_Resultados en una sola corrida `all`
    - _Requirements: R7.1, R7.6_

  - [ ]* 13.2 Pruebas de integración/smoke extremo a extremo
    - Smoke de `all` contra Anvil efímera; umbrales de latencia p95 E1 ≤10 s (R2.8) y verificación E2 ≤3 s (R3.10); integración real con Pinata cuando hay credenciales y fallback local cuando no
    - _Requirements: R2.8, R3.10, R7.1_

- [x] 14. Checkpoint final - asegurar que todas las pruebas pasan
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales (pruebas: propiedad, ejemplo/unitarias e integración/smoke) y pueden omitirse para un MVP mínimo, pero cada propiedad de corrección (Property 1..12) tiene su propia sub-tarea de prueba basada en propiedades.
- Cada tarea referencia requisitos específicos (R1..R7) para trazabilidad y, cuando aplica, la propiedad de corrección del diseño.
- Los checkpoints aseguran validación incremental en cada fase (cadena/entorno, microservicios, final).
- Las pruebas basadas en propiedades usan Hypothesis con ≥100 iteraciones y la etiqueta `Feature: experimentos-blockchain-local, Property N: ...`.
- Los contratos Foundry existentes no se reimplementan; se reutiliza su ABI desde `blockchain/out/` y el script `blockchain/script/Desplegar.s.sol`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.4"] },
    { "id": 2, "tasks": ["1.3", "2.1", "6.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "6.2"] },
    { "id": 4, "tasks": ["4.1", "4.4", "5.1", "5.2", "6.3", "8.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.5", "4.6", "5.3", "6.4", "6.5", "8.2"] },
    { "id": 6, "tasks": ["9.1", "10.1", "11.1"] },
    { "id": 7, "tasks": ["9.2", "10.2", "11.2", "11.3", "11.4"] },
    { "id": 8, "tasks": ["12.1", "12.2"] },
    { "id": 9, "tasks": ["12.3", "12.4", "13.1"] },
    { "id": 10, "tasks": ["13.2"] }
  ]
}
```
