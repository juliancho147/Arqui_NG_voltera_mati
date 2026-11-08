# Reporte de corrida `RUN-ALL`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:53:23-0500  Fin: 2026-11-07T09:54:20-0500

## Cabecera

- `runId`: RUN-ALL
- `repeticiones`: {'E1': 1, 'E2': 1, 'E3': 10, 'MANIP': 1, 'E3-CONTROL': 1}
- `cantidades`: {'E1': {'invalidas': 200, 'validas': 200, 'porCategoria': {'valor_alterado': 67, 'medidor_desconocido': 67, 'lectura_duplicada': 66}}, 'E2': {'totalAlterados': 50, 'conteoPorForma': {'byte': 14, 'metadatos': 21, 'reemplazo': 15}}, 'E3': {'comprasPorOferta': 10}, 'MANIP': {}, 'E3-CONTROL': {}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge 1.9.0
- `params`:
  - `seleccion`: all
  - `e2TotalAlterados`: 50
  - `e3Ofertas`: 10
  - `e3ComprasPorOferta`: 10
  - `pinata`: real
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E1 | E1 — Integridad del Oracle | **PASS** |
| E2 | E2 — Integridad del certificado off-chain | **PASS** |
| E3 | E3 — Tokenizacion sin doble venta | **PASS** |
| MANIP | Pruebas negativas de manipulacion on-chain | **PASS** |
| E3-CONTROL | E3 control — mercado SIN escrow (demuestra doble venta) | **PASS** |

### E1 — E1 — Integridad del Oracle

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R2.5 | Tasa de rechazo de lecturas invalidas | **PASS** | 100% rechazadas (con categoria correcta) | 100.00% (200/200); categoria_correcta=True |
| R2.6 | Tokens emitidos por lecturas invalidas | **PASS** | 0 eventos Emitido por lecturas invalidas | 0 eventos Emitido por invalidas |
| R2.8 | Latencia p95 de lecturas validas | **PASS** | p95 <= 10.0 s | p95=0.1307 s sobre 200 validas aceptadas |

### E2 — E2 — Integridad del certificado off-chain

- Veredicto: **PASS**
- Metricas:
  - `tasaDeteccion`: 1.0
  - `deteccionesPorForma`: {'byte': 14, 'metadatos': 21, 'reemplazo': 15}
  - `falsosPositivos`: 0
  - `p95VerificacionSegundos`: 0.007474

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R3.1 | Dataset de 50 alterados con >=1 por forma | **PASS** | 50 alterados; >=1 por forma ('byte', 'metadatos', 'reemplazo') | 50 alterados; conteo {'byte': 14, 'metadatos': 21, 'reemplazo': 15} |
| R3.6 | Tasa de deteccion de alteraciones = 100% | **PASS** | 100% (todos los alterados -> ALTERADO) | 50/50 detectados (100.0%) |
| R3.8 | Falsos positivos = 0 (ningun integro marcado ALTERADO) | **PASS** | 0 falsos positivos | 0 falsos positivos; 50/50 integros OK |
| R3.10 | Latencia_p95 de verificacion <= 3 s | **PASS** | p95 <= 3.0 s | p95 = 0.0075 s sobre 100 verificaciones |

### E3 — E3 — Tokenizacion sin doble venta

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | **PASS** | 10 ofertas publicadas | 10 publicadas, 0 fallidas |
| R4.4 | Exactamente 1 evento Compra por oferta | **PASS** | 1 venta por oferta en todas las ofertas | 10/10 ofertas con exactamente 1 venta |
| R4.5 | Conteo total de dobles ventas igual a 0 | **PASS** | 0 dobles ventas | 0 dobles ventas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | **PASS** | diff absoluta 0 kWh (conservacion 100%) | tokenizados=1000, validados=1000, diff=0, conservacion=100.00% |
| R4.7 | Gas consumido registrado por operacion on-chain | **PASS** | gasUsed por operacion | 20 operaciones con gas, gasTotal=3198926 |

### MANIP — Pruebas negativas de manipulacion on-chain

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| CertificadoYaAnclado | reanclar otro CID sobre compra ya anclada | **PASS** | revierte (CertificadoYaAnclado) | CertificadoYaAnclado |
| SoloPlataforma | emitir desde cuenta no autorizada | **PASS** | revierte (SoloPlataforma) | SoloPlataforma |
| OfertaNoDisponible | comprar una oferta ya vendida | **PASS** | revierte (OfertaNoDisponible) | OfertaNoDisponible |

### E3-CONTROL — E3 control — mercado SIN escrow (demuestra doble venta)

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| CTRL-1 | Mercado sin escrow produce doble venta bajo concurrencia | **PASS** | >1 venta (defecto esperado sin la guarda del contrato) | 10 ventas de la misma oferta con 10 compras concurrentes |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E1 | Emitido | EnergyToken | 0xae7df442180785718ca426a9d4b32ab42a528d4b24c844fcd30deb86442c5fc5 | 1395 | 248448 |
| E1 | Emitido | EnergyToken | 0xe63d27704d810afe39a460a7fc9edb155580f27adea1dd275b09c919233ddd88 | 1396 | 248448 |
| E1 | Emitido | EnergyToken | 0xb36328846adbb2b26867a33686863fb7163089a12e6c9f8191dfbbe3a8f00198 | 1397 | 248448 |
| E1 | Emitido | EnergyToken | 0x9d84c87625cd788cd3da6868be10a825347237f2db6a4f1441b987724050fdaf | 1398 | 248448 |
| E1 | Emitido | EnergyToken | 0xd0ef3e6389da57be34a737125692e6ed55a086e58ef2481082e9607c85f3aa38 | 1399 | 248448 |
| E1 | Emitido | EnergyToken | 0xe39e52c58206b0850f3eaa1ef703763d4f936e23c02078b319f5fd5a7aa66c29 | 1400 | 248448 |
| E1 | Emitido | EnergyToken | 0x1b549197d528232b1476bbec519c9dabf0573bfca4daf978d3c383d323228bfc | 1401 | 248448 |
| E1 | Emitido | EnergyToken | 0xb19b49f58e00a12e6ed99a045390e7ff4c77ad115624d3b56325b9e85f21e7de | 1402 | 248448 |
| E1 | Emitido | EnergyToken | 0x062bb2f16004b4e0d18060dfbcc8fe63374a6ef3baf9195f0d1a06d40d519ee8 | 1403 | 248448 |
| E1 | Emitido | EnergyToken | 0xa14094feca259fa564c9834b35f051c96c93c233c2d7a20ab8e91cccde922701 | 1404 | 248448 |
| E1 | Emitido | EnergyToken | 0xce71e12cee87fc4f6e4d369a05cb199794961b94cfff363fc22f086d23e05738 | 1405 | 248448 |
| E1 | Emitido | EnergyToken | 0xed60f34f9a7549347f1438dcdd0dd434623619f5fd0fcce08e57214f9ad85e33 | 1406 | 248448 |
| E1 | Emitido | EnergyToken | 0xd174051f225dae2658a9ccf261943b68454c6a314b4fc7fb511f69956f8364af | 1407 | 248448 |
| E1 | Emitido | EnergyToken | 0xc7e8c358f7a83b2772cfc9a4c6798ddd60653375538f34bba8e453a6b990466b | 1408 | 248448 |
| E1 | Emitido | EnergyToken | 0x58e941a9e11cb79515c786120ffc06a5aa3a6c758ed52e839877ca98159a21e5 | 1409 | 248448 |
| E1 | Emitido | EnergyToken | 0x61e5f42a10204efc6e0931e9ea7650a06e335a1e74c35d91b44812cf016c2d7b | 1410 | 248448 |
| E1 | Emitido | EnergyToken | 0xbef0191d05e22ad18c5fd8ae800d487374d57da171a1e6afdc7ac14e0a236c8c | 1411 | 248448 |
| E1 | Emitido | EnergyToken | 0x944b9c81e0697cff8edf4acdc901fd436f39e525220e7deec56b8f95467b2846 | 1412 | 248448 |
| E1 | Emitido | EnergyToken | 0x366ef7401c602e8d94160b506a7d13eef142ce054bb8b7d47522d00e2f594f1f | 1413 | 248448 |
| E1 | Emitido | EnergyToken | 0x5719c94a2c6023ba2a4af5ded2c0220b7368419f6e22f662a94fc95582b8243b | 1414 | 248448 |
| E1 | Emitido | EnergyToken | 0x0a999c060861f430a0e74801a3e60506a9c7f24676d17b7cc724ebbce209dce9 | 1415 | 248424 |
| E1 | Emitido | EnergyToken | 0xcb71e8a10c1abcf8262d23100b1e28a2f1a4e70906bf5dc2a0903d93e4afc587 | 1416 | 248448 |
| E1 | Emitido | EnergyToken | 0x98fc967f709ea804da604433dc88ff4ee883d606339b251f51243962324e9be0 | 1417 | 248448 |
| E1 | Emitido | EnergyToken | 0x03adc15c2524336df693c51d4c16ab376fffb1ee88b9eb604bca87980110ee77 | 1418 | 248448 |
| E1 | Emitido | EnergyToken | 0xe9d55d57fca45fb2761bb7d3f20b35a76960d5b0bb71408857e1716411bb35bb | 1419 | 248448 |
| E1 | Emitido | EnergyToken | 0xe5c298eacf3bdff2f779b7ee84151a34291dd2b73a2ec9e7b4f3487c231b9d15 | 1420 | 248448 |
| E1 | Emitido | EnergyToken | 0x920847718ad2de1651c1da492195d85ee8fc4e6659dd03af52b71d354842b970 | 1421 | 248448 |
| E1 | Emitido | EnergyToken | 0x175c8fe88a524ab8a0cc776a7ca4d17e4fde055f51038bd5f91a382498dde1a1 | 1422 | 248448 |
| E1 | Emitido | EnergyToken | 0x9a442eaf7ceeeef4273be9ea827fbd0f351fa901df07c36967445f0dc0aa686b | 1423 | 248448 |
| E1 | Emitido | EnergyToken | 0x9ab2abffa628febe4c9def7922f8b54fb771ca99d0f4ab58e56f64c22963b78a | 1424 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b91d42991a51b393a2e0513a237a4e8f32402fbfcaebf4bfa3cfd67833d8ecd | 1425 | 248448 |
| E1 | Emitido | EnergyToken | 0x893d76d4ecc7f585a64c4363c8b408766265e54c5e4f625b0c00287c1c441eb9 | 1426 | 248448 |
| E1 | Emitido | EnergyToken | 0xad67a5f13e9cfab4c0b6813b0b3d74e0aad61fa40250f00538943dd038421633 | 1427 | 248448 |
| E1 | Emitido | EnergyToken | 0x424d673b34bfb7c9ab94986fddcf275c4ab7113c7e59e300688eba201677676d | 1428 | 248448 |
| E1 | Emitido | EnergyToken | 0x28aa23b9dae33af3f1e0cb9fcdeb20679686d85275310bc5673295dc6bb56fb5 | 1429 | 248448 |
| E1 | Emitido | EnergyToken | 0x460b3e8f3921521ec301112aa25b39e45330fdc1a77ee02d7eb0e2381cad883b | 1430 | 248436 |
| E1 | Emitido | EnergyToken | 0xc9e18f0c89b3305ae8b587e70d89cd4dd693ab0c07b3bcec891d4985ca254069 | 1431 | 248448 |
| E1 | Emitido | EnergyToken | 0x0b053e144d680ddb79fbad0a2b7c2d0e7bf295e66d1d368151b5ee8e769ced11 | 1432 | 248448 |
| E1 | Emitido | EnergyToken | 0xebc304c845504dd7a75936242a0860b9a3b4cc46c1288222d422adb62c5aac13 | 1433 | 248448 |
| E1 | Emitido | EnergyToken | 0xa5ef7e631700e11dda471e10a31d4dab6394c01b8def0f370454d12dd72e08f6 | 1434 | 248448 |
| E1 | Emitido | EnergyToken | 0x78cbdee441b53dac43ed469754f74f8817018ad84d567cd429851b99e4faff2c | 1435 | 248448 |
| E1 | Emitido | EnergyToken | 0x9b1991d83216d1f71f72cbdc8fb107e7f98e6a331b3b022b225b45f6e16a1b02 | 1436 | 248448 |
| E1 | Emitido | EnergyToken | 0x0ba0e248fe7430b8ef23010ad4a5e5388dc0aa3acccc3d4227ec3c7472ec3ac5 | 1437 | 248436 |
| E1 | Emitido | EnergyToken | 0x5cc8174c2da4bccfb839d2c0497bc561266770202f0c4e0ce1c186c82ef150c7 | 1438 | 248448 |
| E1 | Emitido | EnergyToken | 0xcbd764620e856d0ae7860a9ce9d7445d04efcaeaa364a798c0381732c828f597 | 1439 | 248448 |
| E1 | Emitido | EnergyToken | 0xfe49843146b0bd1d81cdc4103a21a463eab0140bda1dda218515482e3f7fc2ec | 1440 | 248448 |
| E1 | Emitido | EnergyToken | 0x4c4ecf1c41b2230f442d9b1acb3430990438c73309026be243c100c25e9ef4de | 1441 | 248436 |
| E1 | Emitido | EnergyToken | 0x81b7423002e887914fedc1dc9a0f991047eec58bcd32010f8a6d76abc927d91a | 1442 | 248436 |
| E1 | Emitido | EnergyToken | 0xaac238c552f8357b2268dd503551e20d3b6db19b812e6eae01094aacb0646eb8 | 1443 | 248448 |
| E1 | Emitido | EnergyToken | 0xd741264f74763c4c0c3b0fa43017a875b26309ca0fef166b07aa814cc71c3165 | 1444 | 248448 |
| E1 | Emitido | EnergyToken | 0x818353fa87175e527f5c797b0e635ef3b0181ec4217fa6ee4bf44fb556d708db | 1445 | 248448 |
| E1 | Emitido | EnergyToken | 0xd2d8e819973c9e5064c11a75e93b28d0023287035ccc86d61ac3a735aea105bb | 1446 | 248448 |
| E1 | Emitido | EnergyToken | 0xae156cc685e2411f120cbcdc196f02fcd0dadd6fbf4e6608b8178e9fba3aa522 | 1447 | 248448 |
| E1 | Emitido | EnergyToken | 0x1a006f1ca36307cf92740b8d6d6e2369c813b9be73fd34ea840aa040c9b8358e | 1448 | 248436 |
| E1 | Emitido | EnergyToken | 0xf46a4ccdad72d8c573d184bad1cb484bd18cb542a0336f828434911470542212 | 1449 | 248448 |
| E1 | Emitido | EnergyToken | 0xe0d2f2c249deed77c819a48741c394105bacee8917f57af349c6a563cbc6dfd2 | 1450 | 248448 |
| E1 | Emitido | EnergyToken | 0x8a8db8e5c243944359a2fbff751fe5917e2b8e7f1a5d1f6c38f61e878b2d1031 | 1451 | 248436 |
| E1 | Emitido | EnergyToken | 0x7b3c2db803354bf0c6b1f8d75eb79712977b5fe0dce08ea87f0cdf2595bedb7e | 1452 | 248448 |
| E1 | Emitido | EnergyToken | 0x0630edb665fad542a30727809626f2dc6c1993244fd8c948b51afa7a262924c5 | 1453 | 248448 |
| E1 | Emitido | EnergyToken | 0x94bd0041b86c77df391680b0f6297bdf0ffd9677b8505ed280fbd9ed5bb96748 | 1454 | 248448 |
| E1 | Emitido | EnergyToken | 0x1a3eb8216e911f597abe73c666e9c5152e0f58f8476b967ed2f64050624e7812 | 1455 | 248436 |
| E1 | Emitido | EnergyToken | 0xf1a9f35c4e77d779ae6138b6c84f13cd94cf7752666d9755b2c30552519aa179 | 1456 | 248448 |
| E1 | Emitido | EnergyToken | 0x5e1b6881f47938a042d355c8fbe94b93df8e5aac56e3794a3021102c81bb3204 | 1457 | 248448 |
| E1 | Emitido | EnergyToken | 0xc44680f4e259371f7cfd1720c715e701d1d0bda58ecb3aa26163ff03cdce7f47 | 1458 | 248448 |
| E1 | Emitido | EnergyToken | 0x5cd8f11f54f525a056f06647b9486d202f1246aa700aa528709a90c01cb13327 | 1459 | 248436 |
| E1 | Emitido | EnergyToken | 0x7fe823684e4213a0edf1167432ec6520c7a4eb0402033582d91f070abecd8687 | 1460 | 248448 |
| E1 | Emitido | EnergyToken | 0xec328dd3e2bd0396276958bf9160d51fca0fbc295b55e93bc06ad41191c8158d | 1461 | 248448 |
| E1 | Emitido | EnergyToken | 0xcf617e4b2bf839d25da89a868ee0504ce2b717225c54d37fcc9e20f159801053 | 1462 | 248448 |
| E1 | Emitido | EnergyToken | 0x3d9cd3043fc66befa1f89167938819bf457f48b9e10af189679fbba76a896d20 | 1463 | 248448 |
| E1 | Emitido | EnergyToken | 0xc71612eedd03252f19dbb120f1de31f5ccb1cb3a89e0aaccc24c456cf41c8cb2 | 1464 | 248448 |
| E1 | Emitido | EnergyToken | 0xac995f20166b20fde5b2659cc39a795d0a8bc87f84439e41beb123ebdc72e105 | 1465 | 248448 |
| E1 | Emitido | EnergyToken | 0x990e3727d005247d17cf60dee40d67dd3151b06516bcd47ab0e70e3a9caf85eb | 1466 | 248448 |
| E1 | Emitido | EnergyToken | 0x7fe62bced01346ce1e663c6c22c8838323071633aa63056a8e64e406152f832f | 1467 | 248448 |
| E1 | Emitido | EnergyToken | 0x9923dc6c7b1d59618616694d3c936a22bae15aa2c1e6390d9d66c261a54a6712 | 1468 | 248448 |
| E1 | Emitido | EnergyToken | 0x3f696e9f10647c3cea80898c221571444ee521f48b5afa2105fc74816c382719 | 1469 | 248448 |
| E1 | Emitido | EnergyToken | 0x7165fff4eceefc6308b4edaf41847ff3b0986d00c82f384c58bbb7c1f4957fc0 | 1470 | 248448 |
| E1 | Emitido | EnergyToken | 0x3277f47efa2847627305467dfa4b1d9df2f51c9cf8c7ced33f4d757b09bb4853 | 1471 | 248448 |
| E1 | Emitido | EnergyToken | 0x262b73b49c5c16155139916ab661b332d38dc9070c7874372fdbb9bfea6b15e0 | 1472 | 248448 |
| E1 | Emitido | EnergyToken | 0x381ec85776d0c7fc8c4110b3321193fa38f8fd1af9f6c36f8543c75763463bb0 | 1473 | 248448 |
| E1 | Emitido | EnergyToken | 0xa9acecd1fbd21bc6c117d2e15a4d0b284b99f8db9b9dd4268f0d095b138454de | 1474 | 248448 |
| E1 | Emitido | EnergyToken | 0xed72d5225ca304e33fea1682478364530c5e9855a669cb4e6ab9ec486537f3c0 | 1475 | 248448 |
| E1 | Emitido | EnergyToken | 0x2c5f4f5e921b7ce09421215ee93cd5f2120c46d2aa5934dbddd06b7a8af32900 | 1476 | 248424 |
| E1 | Emitido | EnergyToken | 0x286c76368f16f532807724714045d37e5b037a1284f1f3711d4aedecdde89f2f | 1477 | 248448 |
| E1 | Emitido | EnergyToken | 0x365110774ef199d10d15dafd6422074f06013dc4a12402705926cb994d56e420 | 1478 | 248448 |
| E1 | Emitido | EnergyToken | 0x390ae38b872a6da6b59be6345768b56694d882d3c029c51ea67242f153bec6e5 | 1479 | 248448 |
| E1 | Emitido | EnergyToken | 0xc4d48769b6438ed6e86d8672a54672d6e61e66a37c31d233a00ab558b5e3c2a2 | 1480 | 248448 |
| E1 | Emitido | EnergyToken | 0xa75fda71506ededdca7abc7a5ae60a6b3127399131cd20e629c7c47012319590 | 1481 | 248448 |
| E1 | Emitido | EnergyToken | 0x8227409a94a5e9621aa0a0f329bcedf07cbf42d81a8a95867d7167b108404aca | 1482 | 248448 |
| E1 | Emitido | EnergyToken | 0xda2150552003786a88f138eaceb8d0d99f6cd007c30f6b44900ee20d4772b202 | 1483 | 248448 |
| E1 | Emitido | EnergyToken | 0xd9ce2d1286544312a2b58330da86757362b13c40d7dbe6b7ac00aab453834d0c | 1484 | 248448 |
| E1 | Emitido | EnergyToken | 0x7f5d6392fc2b3c4e878880bdb99a52c68acbf4971873037a2f15c03e828eca3b | 1485 | 248448 |
| E1 | Emitido | EnergyToken | 0x1f7fce75ec80159652362d6d12b44ef78cd325ba842ecb8b9ab23f26bdb87b36 | 1486 | 248448 |
| E1 | Emitido | EnergyToken | 0x3d6331e8a317a5778c35f0d7baf8f6399ef95cfb66044137a2a002c6ee3a8721 | 1487 | 248448 |
| E1 | Emitido | EnergyToken | 0x177fb0f45595c7a7e7d35f22cf281d825b8cd624bef3f033a8d37dcfbd941ef4 | 1488 | 248448 |
| E1 | Emitido | EnergyToken | 0xc2b1a3d6c83593c905572e1d62a9696d2d78b0df18b493f47b0dd9e8b0b723fb | 1489 | 248448 |
| E1 | Emitido | EnergyToken | 0xfd3c52adcbdb7f8e159958cf74989c15dac29513a2a4fd014586af6116ad66cb | 1490 | 248448 |
| E1 | Emitido | EnergyToken | 0xd0a779cd5afd9f567391b099d11748e0b6bbd79ad0b33640f21d1bfa1df86a01 | 1491 | 248448 |
| E1 | Emitido | EnergyToken | 0xca69132c720acc7cf0c66a4969ab88c9c9b36edfa375ed294ece3166ba91e84f | 1492 | 248448 |
| E1 | Emitido | EnergyToken | 0x33fb1bfaa48c1d61196c46b2fcaac03a85aede7ce691a0c556764c5acdf89c3d | 1493 | 248448 |
| E1 | Emitido | EnergyToken | 0x491a8c377e8f85dd542a13537356dba1bf18f6dd6402a0040fe901b36f5036b7 | 1494 | 248448 |
| E1 | Emitido | EnergyToken | 0x988ee99353c15c2b974691a7ca3fec3046a51fda4db69136fac0f117f4b782e3 | 1495 | 248436 |
| E1 | Emitido | EnergyToken | 0xd9934e837a031555b3a68b555c5af7ca36fc8d8aeba5f9c85a7ba9205928a55f | 1496 | 248436 |
| E1 | Emitido | EnergyToken | 0x1c9bd003b510b4b7a3c03e27ba9edcc67ee8a2ee5c97e0c11a5280c3b86d00ec | 1497 | 248448 |
| E1 | Emitido | EnergyToken | 0xbb2722f734c038b46499bdacb36d98f7131e0d8ce714984dc380743bb2dd8797 | 1498 | 248436 |
| E1 | Emitido | EnergyToken | 0x32e5afae6c57cb26982f707e54df6ed79e3975336331ada2049fdea597ef7e9b | 1499 | 248448 |
| E1 | Emitido | EnergyToken | 0x3a015e2cffc0ef33b7296dcdd55673c47c9c46700c9391eecc2f546dc3b41194 | 1500 | 248448 |
| E1 | Emitido | EnergyToken | 0x77dadef685160e72f6237d4fa2e522f8827de2fa1ea44f200f59290b1550ad93 | 1501 | 248448 |
| E1 | Emitido | EnergyToken | 0x8e4fd0d00a32586fdd580bd069910fa954b203802709728c6e5209416dc62f81 | 1502 | 248436 |
| E1 | Emitido | EnergyToken | 0xc2cdb5a07daad6c077adf9af50093f60f1553de137c5c4b0b6d7b48dfae61d45 | 1503 | 248448 |
| E1 | Emitido | EnergyToken | 0xc5c2cc53987bd46d0bdb230c8eec28b9361151c46ccd19d3aaafc591736369ea | 1504 | 248448 |
| E1 | Emitido | EnergyToken | 0xfda7bef747140446aa027fcde14708c98e39c122e018ee40c7b9d2bb975a7305 | 1505 | 248448 |
| E1 | Emitido | EnergyToken | 0xb5e7b7dc25e98ddf2a5a99d9c4fb7b52c78899772ba65082700f04a1d57a279d | 1506 | 248448 |
| E1 | Emitido | EnergyToken | 0x9f40e59276fc27629da5642fda9273193498f202c6437b889866dc4c9dabf875 | 1507 | 248448 |
| E1 | Emitido | EnergyToken | 0xd80f2fdb75f82cce2506ef8e2fe5a77ea06504067450547c6a685a4043dc1ffa | 1508 | 248448 |
| E1 | Emitido | EnergyToken | 0x06c0d3af0b46f2fa7f35a034f4f8c316c4108495ed18602ec4f1d4e86fcc74d1 | 1509 | 248448 |
| E1 | Emitido | EnergyToken | 0xb49361a2c1efaa6c8c0051e1f5fb6a2e67cbf9ae40ece8f80bd4728d41049b3a | 1510 | 248448 |
| E1 | Emitido | EnergyToken | 0xb5d6e769130cb614c2c42237bc81dc5b68097c368583be5ef0c5e3008b23ab98 | 1511 | 248448 |
| E1 | Emitido | EnergyToken | 0x2cf869383c59f8b10d404b5c230aa4f4561e3b85485580fc4b1d123c2e079e4e | 1512 | 248448 |
| E1 | Emitido | EnergyToken | 0xd563b0711040896b08bacb7068c882fb53e646b444cc3c1f39af8b74cf3f671e | 1513 | 248448 |
| E1 | Emitido | EnergyToken | 0xd5a333627094d5e488ff8b829bc8a729902a9480c3cf718b67e29dd0edd42254 | 1514 | 248448 |
| E1 | Emitido | EnergyToken | 0xa4a8adeca0e7619c94ab119d08b67c5f8687e5f7cb3ee1409308330c836c8c7e | 1515 | 248448 |
| E1 | Emitido | EnergyToken | 0xd7f85ae37bb279045a4b48cab51caa8f8ed99fc39dd80a53a6966752acd5f4e3 | 1516 | 248448 |
| E1 | Emitido | EnergyToken | 0xd88c76838108cacc41302478b47ba832727dff2b1d8941ebaba06200e40f96a4 | 1517 | 248448 |
| E1 | Emitido | EnergyToken | 0x5d097fbc22d5a0ffc6653d0414f64ce1f206652a9a6c8629021e391a69f5dbeb | 1518 | 248448 |
| E1 | Emitido | EnergyToken | 0x2cdc2884427af47646598358534edbf39149ef30aa5c4634682cfd576aacfa5e | 1519 | 248448 |
| E1 | Emitido | EnergyToken | 0x20c14b6efbe11c0a1916c089f5cd9f5c7440d0b3d296380a7a5e19033d67f2cd | 1520 | 248448 |
| E1 | Emitido | EnergyToken | 0xad063a60e7baa9b652d0acb6526c18dc0d0500646673c1cf92175009d3e3abef | 1521 | 248448 |
| E1 | Emitido | EnergyToken | 0xab34600643c4ebebe598404dc8cbcb46d3b0136c71c6bb1e502cf95370b18741 | 1522 | 248436 |
| E1 | Emitido | EnergyToken | 0x66cc779a30b09dc8268125875db0852111039c935c5461c25652086edff90045 | 1523 | 248448 |
| E1 | Emitido | EnergyToken | 0x1f2867be6746a5e003b4d334c843e3386c40a48bf4a3f72c9811fe5f5f89f1f4 | 1524 | 248448 |
| E1 | Emitido | EnergyToken | 0x4a3fea3e44ea6e976074f581969672104411b3c2b7acb0292ba05d44f081e51a | 1525 | 248448 |
| E1 | Emitido | EnergyToken | 0xa3a0f0f36055313676f931d8345deb614ae2fea6bc0c89634dcbd9143569880c | 1526 | 248448 |
| E1 | Emitido | EnergyToken | 0x48645a48ff924173843e37118363a96c70fb7e788a1e77eb8eba48a00d25c4b4 | 1527 | 248448 |
| E1 | Emitido | EnergyToken | 0x69137cc34a36b2bded310bb88cd60d54f99584054b0eac330ad279df00153acf | 1528 | 248448 |
| E1 | Emitido | EnergyToken | 0xd862392ea62c7ae6b56d62cdea3dd6409e00cc46ae0a138412a97395bc5c7a23 | 1529 | 248448 |
| E1 | Emitido | EnergyToken | 0x48a3749c88954f03d242c32170988f9cb95c2f27bf4136a6963d03cac6683f9d | 1530 | 248448 |
| E1 | Emitido | EnergyToken | 0x87f59c9460f78bb0a4dcb0571c5684ac3345bb438e70d6ae5c62a474d462861c | 1531 | 248436 |
| E1 | Emitido | EnergyToken | 0x9ccc3bbba53bf1adf518fdc99a8f66c637eed284e33c4fafb793ed70266460f3 | 1532 | 248436 |
| E1 | Emitido | EnergyToken | 0x93d20805a1c38e6ab0ae7b8b1847b809b6fdf5ad2ea373b7cbe96ac9d7db30d0 | 1533 | 248448 |
| E1 | Emitido | EnergyToken | 0x64f96525dc325e888ae61d06c940d541c3e8fca6b4b4668c5e5e9d217a556ac1 | 1534 | 248448 |
| E1 | Emitido | EnergyToken | 0x212f080eb29213407fb5fc3fdb6d6e1d3749a5511b6b6f43a2797a23efdf7fe5 | 1535 | 248448 |
| E1 | Emitido | EnergyToken | 0xf7710a2f941c50908aae6a5d5696893cefeb015dd6b639502471132d9d3a8d29 | 1536 | 248448 |
| E1 | Emitido | EnergyToken | 0x908c4b4020625458a136ba479f9f53f474fd6a462b3891f2e3432acce85adb4c | 1537 | 248448 |
| E1 | Emitido | EnergyToken | 0x3fc22f82156e1e6e89051e20b6235473ae75dffead238455f1d046b8704859b6 | 1538 | 248448 |
| E1 | Emitido | EnergyToken | 0x441672efda735c15382920bc49a1ad488055c3ac99c7cf7c44c3444f3156ff52 | 1539 | 248436 |
| E1 | Emitido | EnergyToken | 0x6763989be42c17b0c1addf6f6bf6abc09b6c3a67678b8918d46a19fde55c6eb6 | 1540 | 248448 |
| E1 | Emitido | EnergyToken | 0x587375518785c19eb9d5642cfbc6bac1c4284fc15803e93c90afe2b280408ee3 | 1541 | 248448 |
| E1 | Emitido | EnergyToken | 0x5175ac53dab04f8151425c9e53b215379e436a2d2a7fadfca8577066dbffca29 | 1542 | 248448 |
| E1 | Emitido | EnergyToken | 0x2ee1744d12037048df58cca6921c92bed38d68457512164afae3738493036558 | 1543 | 248448 |
| E1 | Emitido | EnergyToken | 0xd38a61ce98a20907ee6021b20ca931ac59d8095fcdc26549ec3063d51b5cf77a | 1544 | 248448 |
| E1 | Emitido | EnergyToken | 0xccf3dddfdbf5957a17430f285047e2bdc1b8e6b11f28d086880a7ca4cababbb0 | 1545 | 248448 |
| E1 | Emitido | EnergyToken | 0x77c5b81c502da86c983251c9f1e309ce0feb42668c2caf5942e43d9fd30f029b | 1546 | 248448 |
| E1 | Emitido | EnergyToken | 0xbb559f07f6062dc45a9e24c997fb0f3faee7433b2b790393ff98da1f178a1f72 | 1547 | 248436 |
| E1 | Emitido | EnergyToken | 0x0a16aa7fa37e0dc70714be7ea782597339cc6d8c9fc544232de5e2a80f3b2c42 | 1548 | 248448 |
| E1 | Emitido | EnergyToken | 0x656608f12061cafe8d3527c4025768129f607371cdd94f3996037285e17206f8 | 1549 | 248448 |
| E1 | Emitido | EnergyToken | 0x197c977ac7cfee04bbd5af3c2737a783ae45d7319943005cda9fb0dece56ea5e | 1550 | 248448 |
| E1 | Emitido | EnergyToken | 0x9cd530b80e8df2a2e02835e8721dc9b840393075bf5e975edc47f1e87bd33143 | 1551 | 248448 |
| E1 | Emitido | EnergyToken | 0xc926bab77aca88479d1fb997c23fd67272ee11f9fd7461f014d54c086e3bb8fc | 1552 | 248448 |
| E1 | Emitido | EnergyToken | 0xcf82b2f4b2cfd9a96a21913a68c772fe4e940727d042659ec1ef8ed6b3775e09 | 1553 | 248448 |
| E1 | Emitido | EnergyToken | 0x92f68b5c4fe91f9b550437181f3ad23db75f6b917fc33e00bae6de58d6c960d4 | 1554 | 248436 |
| E1 | Emitido | EnergyToken | 0xe3248024fcc8dd960ca0c0aead70ba2c2c5b9e3391b66209b677bdba9607896a | 1555 | 248448 |
| E1 | Emitido | EnergyToken | 0x205146b8b6081368809f554aae3b03e368d6630b8cde1949968eb54142298d03 | 1556 | 248448 |
| E1 | Emitido | EnergyToken | 0xe8f8c9cc814bc35d6cc5b1c830dfcaef86e6bec7adaffa18076e580613671be6 | 1557 | 248448 |
| E1 | Emitido | EnergyToken | 0x24b3d65d0047478dbe55cf0cb60107622893620e3ff1991ef84cd07445a396af | 1558 | 248436 |
| E1 | Emitido | EnergyToken | 0x858735b422e75ed26cfb0bea071af0f21be7a92dde118574b6a1a7757d290df2 | 1559 | 248448 |
| E1 | Emitido | EnergyToken | 0x941b03872ccecb9b81840fcb468c3e86229065086c9f91485e622ec44fb98ac3 | 1560 | 248448 |
| E1 | Emitido | EnergyToken | 0xf584b5db5c57b906f7cd855c60e1ef3813429f02802ffb079844b9f445947ee9 | 1561 | 248448 |
| E1 | Emitido | EnergyToken | 0x8646a7db751a9143bf0b21edfde0f32463466a77d4ae0cc8db3f5da8689b9506 | 1562 | 248448 |
| E1 | Emitido | EnergyToken | 0x05ea7cd9f3b3112383d2cf2e357f7ff7a9435a914811b9bff9989d75bf893f22 | 1563 | 248436 |
| E1 | Emitido | EnergyToken | 0xb38c4f306b6e83a2003354d7b61cc2ef9a4e77599e5b111d8996eca6fde5551b | 1564 | 248436 |
| E1 | Emitido | EnergyToken | 0x1251121b09252c49635fb2a3f129a6312b8addda8fb7fd09a65e34809208bf83 | 1565 | 248448 |
| E1 | Emitido | EnergyToken | 0x828ae193cd6b3fc4834680680fe77121f907fe0030ab51da187f569b97d7d444 | 1566 | 248448 |
| E1 | Emitido | EnergyToken | 0x19933ed452aa9b23b50a8dc6ae075fe6c57f41941c65f8e925608d400e35c40f | 1567 | 248448 |
| E1 | Emitido | EnergyToken | 0x1f05d11ea6623376051d53b218ba09b342b41f4287b33511928e80d2c8b09447 | 1568 | 248448 |
| E1 | Emitido | EnergyToken | 0xa38e165ca2f61359c9bfb733283b490ce68b2355a7578bcb75e825c8a712eaff | 1569 | 248448 |
| E1 | Emitido | EnergyToken | 0x1814c27724577aefd4d860febbe4e89e3b99c79986c7a39a221404ebf6fe9650 | 1570 | 248448 |
| E1 | Emitido | EnergyToken | 0x788f5d01cc0c2463118c6351d15ec03dc507c5ba140e68f87c67d23d26534491 | 1571 | 248448 |
| E1 | Emitido | EnergyToken | 0xf5fc8b6c0970a2a93dbc79eb0624fe4f16736a9aaa7f847d8ea1da0a1c5b377e | 1572 | 248448 |
| E1 | Emitido | EnergyToken | 0x06daef4a62e2d94d3339379156eefc49f9f4a4969e5c827c4851053df73750ba | 1573 | 248436 |
| E1 | Emitido | EnergyToken | 0x5988f1f6923171be797439ff004fa47bbb9246a888cd44fb52ebe07bce165880 | 1574 | 248448 |
| E1 | Emitido | EnergyToken | 0x920e4cf678623c88585d571eccd06f13b9e309b5c70301de7e8a09ad5aaa2d5a | 1575 | 248448 |
| E1 | Emitido | EnergyToken | 0x2e4ac8a46099e99fa1e39b16b89bee09a027cf6ec42e8680a42f3bab5ea04898 | 1576 | 248448 |
| E1 | Emitido | EnergyToken | 0xe19df96c6250c059804ef04b1c211163fe39e97af610c14944336e9fd6222df3 | 1577 | 248448 |
| E1 | Emitido | EnergyToken | 0x45b8cf90ca77625a06a13b85f927de0c70f7dbdad15dc87f8f00e820bddcccd8 | 1578 | 248448 |
| E1 | Emitido | EnergyToken | 0x8f2885634906d0e0a5510ac49a82de9fc480728120ba410b41ffbbc32a81bd92 | 1579 | 248448 |
| E1 | Emitido | EnergyToken | 0x0ba5d1e9340e881928ccfa82c9539d4db477ab47593c6170738f3effc74a5de6 | 1580 | 248448 |
| E1 | Emitido | EnergyToken | 0xe74da797fb2cccd50cf675d3673f9a9295461a25676451760591ef31e6d85419 | 1581 | 248448 |
| E1 | Emitido | EnergyToken | 0xf5cc1f789a4700fe6352af5123c5a38f9805e063571cc77759b24968fb1f7917 | 1582 | 248448 |
| E1 | Emitido | EnergyToken | 0xbfe42eaaeb2b086c0b15448387d35daa1ce3f6c84eccd66991430565a4bfcf74 | 1583 | 248448 |
| E1 | Emitido | EnergyToken | 0xfe563141a9e6949125b19488adf4194d18c1e4984eac85c0e193c2eb83ffc3b2 | 1584 | 248436 |
| E1 | Emitido | EnergyToken | 0xdaff6fdfbadd847d16f5f25356e4d70aed31e6fb6283c686d0408f9141c04ed0 | 1585 | 248436 |
| E1 | Emitido | EnergyToken | 0x77a7af1e81871e8e71c182972eb5557d221e177e3251ca5b483801591a893675 | 1586 | 248436 |
| E1 | Emitido | EnergyToken | 0xa1d26e0a16d842dbdf6c2e6d45ffdf3f393c8d392827ad693a436f8919d83b87 | 1587 | 248448 |
| E1 | Emitido | EnergyToken | 0x728072c6b18b0951e7f505bc7fd40687c9c6a39a96cdff3674301dccd8026d20 | 1588 | 248448 |
| E1 | Emitido | EnergyToken | 0xe0518891dbe7875ea234ddf52594d5d0056f46a409ce7ca4da98d4e44f112cf7 | 1589 | 248448 |
| E1 | Emitido | EnergyToken | 0x70579382d78ea0a11f1140ca8f4eddbf9581c628c876d88de0013e2dfc3792a3 | 1590 | 248448 |
| E1 | Emitido | EnergyToken | 0xd0a4ccb43b55b262d54712e56bc122a28dc715d9b362b7f3dcbec9dbc8d66869 | 1591 | 248436 |
| E1 | Emitido | EnergyToken | 0x9e8016a0eb715cf321af5dc8fe9e2e1e3ef1a9b129fd6b3ee704ffcc0424fdb8 | 1592 | 248448 |
| E1 | Emitido | EnergyToken | 0xcc0f8b414e96e3022c90eb2b7d6f06a6b385d6bbc5af0cd9dbf846eabda6b7e9 | 1593 | 248436 |
| E1 | Emitido | EnergyToken | 0x460d3965f947cae94b917e5d43b79a44e3f96eeddf0c560d9d2531f0393657ed | 1594 | 248448 |
| E3 | Emitido | EnergyToken | 0x728fffc2b781d56712fb68a2b43ff16b668c9207812f0be84fa8cc5147b3acde | 1795 | 140289 |
| E3 | Compra | MarketEscrow | 0x0e213adc2dc086aa17c260261c006e10875e6985603237ab2dc37cbdf4ad5f90 | 1797 | 179606 |
| E3 | Emitido | EnergyToken | 0xaa56372a0f132b04ea07d546bb479a2b8b8acf674d05d4f432b029a62ad50e71 | 1801 | 140289 |
| E3 | Compra | MarketEscrow | 0x4b8849d6301c1cf4add3a1eab2073717c1a662dc302cdbe2d061f47df93b7d08 | 1803 | 179606 |
| E3 | Emitido | EnergyToken | 0xe9fef818df1bfad755acc6b7456ca2d442e5963fe6c27c97e3461f67a9dacb60 | 1807 | 140289 |
| E3 | Compra | MarketEscrow | 0x3e533bae787a154c0b0c1b002520428e645924c5680bb8a5ec3c637d51f288bd | 1809 | 179606 |
| E3 | Emitido | EnergyToken | 0x0c85e5ac5beb8410b9a4d688ecce71bbbfbb23c7dcbbfcfb43fea300ca213eb8 | 1813 | 140289 |
| E3 | Compra | MarketEscrow | 0xd32433a56532dd98bb77303b8cd6425683937f83cec64b3220fbea55d1fe8676 | 1815 | 179606 |
| E3 | Emitido | EnergyToken | 0x4d9c1f78918121f1bd83c04b91dddc2e94a1783e7d89ef123e944edb04a427d8 | 1820 | 140289 |
| E3 | Compra | MarketEscrow | 0xa3e667ed31a804493e277611bb286adbb50da2b3dec89290e1dfdcbe5a8fa82d | 1822 | 179606 |
| E3 | Emitido | EnergyToken | 0x28c803dc296fc4f886fffd8fea0ec2490b6f44a97a6e4586131b7e49125c673e | 1823 | 140289 |
| E3 | Compra | MarketEscrow | 0x2a8c974ff0ba567a00994b5e1175bc22a9f7bb32ff10a58209870bfbee45146f | 1825 | 179606 |
| E3 | Emitido | EnergyToken | 0x6db91de794e4b3918564bd7e4e1f15f662447c6ecc8c01965e3e97c43fffec99 | 1829 | 140289 |
| E3 | Compra | MarketEscrow | 0xc3f1a1e2cfd3bcf0d4f93bef4ac3d43223ee9ece4d109c4fa50385ca8a2c3205 | 1831 | 179594 |
| E3 | Emitido | EnergyToken | 0xabbc570fa7fd57c4c62eb7b0c608b02be339729414442c217f5aad15e9d9518d | 1835 | 140277 |
| E3 | Compra | MarketEscrow | 0x678b4701768f13056f0a0da18264622476fb1659b575d8e9247ddab1a43985eb | 1837 | 179606 |
| E3 | Emitido | EnergyToken | 0x419dbc1d56de0c8513a424ba674bb8d3a43be1a833745f5f853350d1a3ab7a2a | 1842 | 140289 |
| E3 | Compra | MarketEscrow | 0x684cd64dfc2a99a1ac97f6239b2004156b2fc4dd115201c8e7158e32eb2b2d27 | 1844 | 179606 |
| E3 | Emitido | EnergyToken | 0x980877a8107d09640d56a4ba045adb2eb742895caca40c7f1862d4e85e3050e1 | 1849 | 140289 |
| E3 | Compra | MarketEscrow | 0x8222663e21acd46e3dcf6eb01b9944bc467ec4f2681e2e13e105cd2401a917ce | 1851 | 179606 |
