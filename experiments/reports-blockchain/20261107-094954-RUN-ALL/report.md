# Reporte de corrida `RUN-ALL`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:48:51-0500  Fin: 2026-11-07T09:49:44-0500

## Cabecera

- `runId`: RUN-ALL
- `repeticiones`: {'E1': 1, 'E2': 1, 'E3': 10}
- `cantidades`: {'E1': {'invalidas': 200, 'validas': 200, 'porCategoria': {'valor_alterado': 67, 'medidor_desconocido': 67, 'lectura_duplicada': 66}}, 'E2': {'totalAlterados': 50, 'conteoPorForma': {'byte': 14, 'metadatos': 21, 'reemplazo': 15}}, 'E3': {'comprasPorOferta': 10}}
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

### E1 — E1 — Integridad del Oracle

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R2.5 | Tasa de rechazo de lecturas invalidas | **PASS** | 100% rechazadas (con categoria correcta) | 100.00% (200/200); categoria_correcta=True |
| R2.6 | Tokens emitidos por lecturas invalidas | **PASS** | 0 eventos Emitido por lecturas invalidas | 0 eventos Emitido por invalidas |
| R2.8 | Latencia p95 de lecturas validas | **PASS** | p95 <= 10.0 s | p95=0.1228 s sobre 200 validas aceptadas |

### E2 — E2 — Integridad del certificado off-chain

- Veredicto: **PASS**
- Metricas:
  - `tasaDeteccion`: 1.0
  - `deteccionesPorForma`: {'byte': 14, 'metadatos': 21, 'reemplazo': 15}
  - `falsosPositivos`: 0
  - `p95VerificacionSegundos`: 0.006593

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R3.1 | Dataset de 50 alterados con >=1 por forma | **PASS** | 50 alterados; >=1 por forma ('byte', 'metadatos', 'reemplazo') | 50 alterados; conteo {'byte': 14, 'metadatos': 21, 'reemplazo': 15} |
| R3.6 | Tasa de deteccion de alteraciones = 100% | **PASS** | 100% (todos los alterados -> ALTERADO) | 50/50 detectados (100.0%) |
| R3.8 | Falsos positivos = 0 (ningun integro marcado ALTERADO) | **PASS** | 0 falsos positivos | 0 falsos positivos; 50/50 integros OK |
| R3.10 | Latencia_p95 de verificacion <= 3 s | **PASS** | p95 <= 3.0 s | p95 = 0.0066 s sobre 100 verificaciones |

### E3 — E3 — Tokenizacion sin doble venta

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | **PASS** | 10 ofertas publicadas | 10 publicadas, 0 fallidas |
| R4.4 | Exactamente 1 evento Compra por oferta | **PASS** | 1 venta por oferta en todas las ofertas | 10/10 ofertas con exactamente 1 venta |
| R4.5 | Conteo total de dobles ventas igual a 0 | **PASS** | 0 dobles ventas | 0 dobles ventas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | **PASS** | diff absoluta 0 kWh (conservacion 100%) | tokenizados=1000, validados=1000, diff=0, conservacion=100.00% |
| R4.7 | Gas consumido registrado por operacion on-chain | **PASS** | gasUsed por operacion | 20 operaciones con gas, gasTotal=4178126 |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E1 | Emitido | EnergyToken | 0x92a1c8b00e4acc45e2f0a5f04c06528ca1c4d1cf512e768062bd11bf961f358b | 466 | 248448 |
| E1 | Emitido | EnergyToken | 0x8ff6f2a85cbd5b59c979f49732827ca1e32a169b717021e93ec3261c7b1d0710 | 467 | 248448 |
| E1 | Emitido | EnergyToken | 0x9ae11277ee6e6124aa77eec7d8e1693f1c97a56d2d7fe176a79eee3aa35704a3 | 468 | 248448 |
| E1 | Emitido | EnergyToken | 0x5646af116cee0eb1a08cdc8b26a1e5e2481311779c112e21d4c6be701cc41893 | 469 | 248448 |
| E1 | Emitido | EnergyToken | 0x74b3ca0c6003f840ef9f359c612f2cd1aa523619ac047037de632cfa899384c8 | 470 | 248448 |
| E1 | Emitido | EnergyToken | 0x1e181090403e53923fc0265a54feb86fac32575e6158c3c9cd6f05341ae97252 | 471 | 248448 |
| E1 | Emitido | EnergyToken | 0xc8c65b963ed805c9a004d0f1ccc818cce6f700f04f44152e21359cb578597527 | 472 | 248448 |
| E1 | Emitido | EnergyToken | 0xf4c21f6bee0a7d2953ca761389a8545d7769cc8c68d1dc10da7bd23bcedca9d5 | 473 | 248448 |
| E1 | Emitido | EnergyToken | 0x591c433dd3fd106d8c0fe5012eab0bf08f1d63eab25b24021732ab98bb29803a | 474 | 248448 |
| E1 | Emitido | EnergyToken | 0x4b6d6c524421bd3bbba2d8c4ed9c607456daef3d3900100a7e5070d767efebd9 | 475 | 248448 |
| E1 | Emitido | EnergyToken | 0x5b3f6119bd77e18e0523981b5d34e8dc2fb73412c31d17bfe5af3c0239b0b947 | 476 | 248448 |
| E1 | Emitido | EnergyToken | 0x3e0aade3a0f4fd105b9b5db8f7bc210f034a20e65176746131f9b4320428d153 | 477 | 248448 |
| E1 | Emitido | EnergyToken | 0xadbd38ae590c20acb8ec42142daeedd94e7b96b416ed0995e40da374cf96e6de | 478 | 248448 |
| E1 | Emitido | EnergyToken | 0xd665c83b8b0044d9338f340902d722f6c060ddf9e72dd2b40601de10ce449138 | 479 | 248448 |
| E1 | Emitido | EnergyToken | 0xa33d9469118ca4e9faf41efbe60da9bfb893620e851e396b4929645b75042fe5 | 480 | 248436 |
| E1 | Emitido | EnergyToken | 0xe4de74c34fa169cee4ee852b34843a473f24dc579c8d2822eda5a6f95e7f73ef | 481 | 248448 |
| E1 | Emitido | EnergyToken | 0x290082cd3f9d2ae3a225aacf06a9524d281b042cfd5abf19f5a7992f1a54eb3c | 482 | 248448 |
| E1 | Emitido | EnergyToken | 0x28704e8e6ea8abe57350c3a5c8aacf3a7065e0d44df018b9b7e3e8f23b3147f3 | 483 | 248448 |
| E1 | Emitido | EnergyToken | 0x39b99183f4b05e9f9904927602e0208ee6fb0a405ab36afb52179ab6979ca5f3 | 484 | 248436 |
| E1 | Emitido | EnergyToken | 0x9bffe8ca22254207df229e9d98d49572d67519b25a83ff883159ccca90523d30 | 485 | 248448 |
| E1 | Emitido | EnergyToken | 0xf45c2f4bea561a7e831ba4b46a71614a0b88c846bce1e205ef6981140394ca44 | 486 | 248436 |
| E1 | Emitido | EnergyToken | 0x60c2cba3fb78577607c0c480b97af1c0b06811e3db1d033a193d556b8dadd84d | 487 | 248448 |
| E1 | Emitido | EnergyToken | 0x19890e35bc92b7d3c2c631cfe517e8b0dcaca78f724edd81f5cfbd59439cde6a | 488 | 248448 |
| E1 | Emitido | EnergyToken | 0x7f91c8959d3c89c69300c41a2060861bbda521af7501f51bf73030259ac19459 | 489 | 248448 |
| E1 | Emitido | EnergyToken | 0xa766d747dd74fb03e56b1b66c2f59d54510ce82cb360aa02af9ded38ed934ab6 | 490 | 248448 |
| E1 | Emitido | EnergyToken | 0x08c4fcc7c4fc1959ff87c80503e1ccc75632d153bde5d51b3c808106afd4fca7 | 491 | 248448 |
| E1 | Emitido | EnergyToken | 0xd5f34fa02afa70dcb770361766bc666e3fb99d0656e2449156a9817d0b111e74 | 492 | 248448 |
| E1 | Emitido | EnergyToken | 0x80b854f02aba349c4052a2954297ef6b0d99895278ccd34361b9f15110c060d8 | 493 | 248448 |
| E1 | Emitido | EnergyToken | 0xe981ba8aaca809c47eb9fe6ae666644b0a255f4e3d1682ff608c0fc08c64dd56 | 494 | 248448 |
| E1 | Emitido | EnergyToken | 0x6607ee343a7325aefd3c630a6732afc797e6c7c44a444c565081f383597b6353 | 495 | 248448 |
| E1 | Emitido | EnergyToken | 0xd452ff7213dd2e20c8e917863841e3b14cb288153022bb3336693f0d9092912f | 496 | 248448 |
| E1 | Emitido | EnergyToken | 0xcf7dba872485e6912e1c3a6f8ea88725208ee0282b820a6dd2da97c22cdf24ae | 497 | 248448 |
| E1 | Emitido | EnergyToken | 0x2a29b29000ec69bc5a208988f5a08be0f9e37736cc0cb967deb53b90bceed0ed | 498 | 248448 |
| E1 | Emitido | EnergyToken | 0xcb1aa8b9434bc154a65f71e82e876258a95a1d243c49e6ec25447795a976c3bb | 499 | 248448 |
| E1 | Emitido | EnergyToken | 0x7d5e7a6a26559e279369033db669f025df8b300b8cf6665664bdabb337cccb72 | 500 | 248448 |
| E1 | Emitido | EnergyToken | 0x30da66348cffbb0b7e834f68918b2c77a5ebb4f1d8e86f10bda2a03599656f1c | 501 | 248436 |
| E1 | Emitido | EnergyToken | 0x89366194d36848ada1f91c2c5e2c5f6e6787ef3fcec24f4c1df2427e623ee9b5 | 502 | 248448 |
| E1 | Emitido | EnergyToken | 0x04aef17c968347de6515ceeda10bc4804372d93566d6d56c40922336842be3d3 | 503 | 248448 |
| E1 | Emitido | EnergyToken | 0xb07a813c447edd2fe10a1dc754f1cf58aca4421b863eac9263b56be6d3235143 | 504 | 248448 |
| E1 | Emitido | EnergyToken | 0x735e3c4bf10b0621bcf0ea8159e168e11175f583f6dfbc1d2c5916bb3bd9645f | 505 | 248448 |
| E1 | Emitido | EnergyToken | 0x17c64b8d1dc194a31807b509f889124d46c6c35a054948ed68580f43822b04a3 | 506 | 248448 |
| E1 | Emitido | EnergyToken | 0x35e0a8845abeb7018c7c1e8813ee5e894e5d40ce1251e18ceeac49520339645d | 507 | 248448 |
| E1 | Emitido | EnergyToken | 0xd1b9151fe17afb9faeae053a4ba58fa68844cc8b9bb4d76675a73b77a705ce82 | 508 | 248436 |
| E1 | Emitido | EnergyToken | 0x49c5aca26da30095a68d3fd3d715280938ced466b0d51eff5152c60295944bc8 | 509 | 248448 |
| E1 | Emitido | EnergyToken | 0xdcbb835bf6d1144f0b4a1ed878564a8f88410f5b1231d03f79a4a03bdb6af2dc | 510 | 248448 |
| E1 | Emitido | EnergyToken | 0x968f815619e4abb3feaea5c60784218a7a504e16f559a5f96c87c50bc6ca5374 | 511 | 248448 |
| E1 | Emitido | EnergyToken | 0x9121aa7ea63383cf84c11a254ddce6ab7b6894d00e8dc32fb0214c7b37ddb404 | 512 | 248436 |
| E1 | Emitido | EnergyToken | 0xef44ae45768efa03e6e99c9ffb68b0977481b0cc3f87f5e2eadf029d2842af81 | 513 | 248448 |
| E1 | Emitido | EnergyToken | 0x88e2070329ba6588adb156eabbca22d18a1127f8661de1eaea1a414f11e655f2 | 514 | 248448 |
| E1 | Emitido | EnergyToken | 0x61725e41d59f5e105546c698c7469e63dd04f1adbcd2b2a9cc0c914b968f5401 | 515 | 248448 |
| E1 | Emitido | EnergyToken | 0x05afb5e484ed5759519f34d461aa185928989918938660b816868c24b6f3c433 | 516 | 248448 |
| E1 | Emitido | EnergyToken | 0x2f2be5bde45721082ffc174aa25c5ae78f880eb4229261b789b39b16c2979806 | 517 | 248448 |
| E1 | Emitido | EnergyToken | 0xbdf027387166a82a68999633be47dae2abc175323e8bb34738cc9128c1bd0f79 | 518 | 248448 |
| E1 | Emitido | EnergyToken | 0x9b67a5aebec5519be90ba46eab10bd62a8f2f615df3540e54b22cbb684041ac8 | 519 | 248448 |
| E1 | Emitido | EnergyToken | 0x1271dcdcdf3347ee0306d295f246dea105f220da39155f08390ce56c2b625d54 | 520 | 248448 |
| E1 | Emitido | EnergyToken | 0x529b091a470e7a41c48731b093091630d5ccb05cb19a8ea32da4a95a5c8256c3 | 521 | 248448 |
| E1 | Emitido | EnergyToken | 0x4687ee42216a83cf18af0247a4a6938cef5a39415e5458523ae5c8f6f5c3cb5b | 522 | 248436 |
| E1 | Emitido | EnergyToken | 0x884da01811c83888e06f5f116186afc8658bcaf9362388138f09f478f31e9639 | 523 | 248448 |
| E1 | Emitido | EnergyToken | 0x502777414cc6a0a77b5def1f426333b3bd98e1edae13d54c384562e1d2a7d021 | 524 | 248448 |
| E1 | Emitido | EnergyToken | 0x3264a1e475522e1d29c29c2f67271f2cfc38ddcc48269feaef9cf11175c1db08 | 525 | 248448 |
| E1 | Emitido | EnergyToken | 0x1e7cbfb7f6eaca1a72f415d82922e13fa700ea1747daf8e4ab2239b393a7a401 | 526 | 248436 |
| E1 | Emitido | EnergyToken | 0x5753a4047d20e314b20510c2ed8b7f52b411ee6163b44188783f5de14f898b60 | 527 | 248448 |
| E1 | Emitido | EnergyToken | 0x4661141e8ead22a16bb89b3aad3cd9acb23aa61a5c14bf19663ca09d1532ceb3 | 528 | 248448 |
| E1 | Emitido | EnergyToken | 0x279bc3b8ce6631063baae26e85349b4c49b8c799647b11a974b49bee7be760d3 | 529 | 248448 |
| E1 | Emitido | EnergyToken | 0xea7e85cd235289d89a1fa887a96fdf863c283872350091dbdfc3b95a72a0717d | 530 | 248436 |
| E1 | Emitido | EnergyToken | 0xa237ef82c02a4d0e1a5d864de22acc894c68f2e70a6ceeae0cf3b3785c11fc93 | 531 | 248448 |
| E1 | Emitido | EnergyToken | 0xc1738230fe280679cb5c5f6fe309354d9ab69d2eab1f0c4583ee211604feb1c6 | 532 | 248448 |
| E1 | Emitido | EnergyToken | 0x791bc0d6c3e46aefae074eada0f2b12802d0cfd100831cd3f7cdee986bf9e077 | 533 | 248448 |
| E1 | Emitido | EnergyToken | 0xe61292c4c41ca6f0d577acdb436f50eadf90082146c36bfacc7e547af065580b | 534 | 248448 |
| E1 | Emitido | EnergyToken | 0x1cdd9381fccae87a0bb3d30a3650724550971d87d484d15bae4657aa52e451f9 | 535 | 248448 |
| E1 | Emitido | EnergyToken | 0x09e84d36364c202e9b6c29ab02ba181ddc7929811693b280ea60d157c77c67e7 | 536 | 248448 |
| E1 | Emitido | EnergyToken | 0x5a9ed2c7189294e8361a1eec857ab61c76ee4927e5fa29fdcf7fb2dee5872615 | 537 | 248448 |
| E1 | Emitido | EnergyToken | 0xbb978f4f8d53a1b3a6a7f5fb4a99178908b139582e1b801cc7a7eed379f12925 | 538 | 248448 |
| E1 | Emitido | EnergyToken | 0x797d8097b3e645d33bad70a155091df163558facddc90bdb812f239747d62881 | 539 | 248448 |
| E1 | Emitido | EnergyToken | 0x8b754dc78a6025465e481c8adbfbb39a3e75cbbe7c6d31f4bf6fcd5ce87d909e | 540 | 248448 |
| E1 | Emitido | EnergyToken | 0xf392da71991ee9858221e6f0d05c18943e4dc87cc9f7f41459580c199ff8c3c4 | 541 | 248448 |
| E1 | Emitido | EnergyToken | 0xb46c37686844177f9272396b15e1af0a7f6e5d168ace0ddd5fbfba38d1a7c893 | 542 | 248448 |
| E1 | Emitido | EnergyToken | 0x674149571358da377fc58a4d42bd30b327c42b596cbcd602550ad8a0b76b93bf | 543 | 248448 |
| E1 | Emitido | EnergyToken | 0x52d46cc9e867c2abdbab284fe56d31db97308aa03532b6968c29fd1c7b6af20e | 544 | 248460 |
| E1 | Emitido | EnergyToken | 0x546e0215f4093f4e6bb5104d2d5a620680adfb0b643ec2e7ec9a468e4bfc55ab | 545 | 248448 |
| E1 | Emitido | EnergyToken | 0xa1b451d2f40697d56fb7a459fd227f60f0c0d43a79389f762f9db9aa19c412ea | 546 | 248448 |
| E1 | Emitido | EnergyToken | 0x197138ed4bba181e80d6bfdd41a19ba80b1864c436a52b086d94fe33d5dff477 | 547 | 248436 |
| E1 | Emitido | EnergyToken | 0xd22c97a5a9c7cbf1fb7aa98d0813e90b73098d78de72a595d85d724b143cac6c | 548 | 248448 |
| E1 | Emitido | EnergyToken | 0x1b6ba740d4c98a9662115e5275257f189c34024126aca717164266294e53f181 | 549 | 248448 |
| E1 | Emitido | EnergyToken | 0x6eceff3530bf2bf9212cce1ea4275163cbacf02fa48f80412a468243a967aa8d | 550 | 248448 |
| E1 | Emitido | EnergyToken | 0x4754721c81096346db9c98f5be7e71b329c115d2bb3b65a8b75aa74318c946f9 | 551 | 248448 |
| E1 | Emitido | EnergyToken | 0x48eea6ad137783af2605ec7518682b221f5d75436fc1ab18bdccc704e5e7279c | 552 | 248448 |
| E1 | Emitido | EnergyToken | 0x188cd1c0fe73e7f997cb714ce3b08eceb2bd5bae9d5b48cf5ce0b4e50642c293 | 553 | 248448 |
| E1 | Emitido | EnergyToken | 0xbfd318cac5ab7a8eeb80085a19857ac62d9205ec85d3271f3f8ef1569376587c | 554 | 248448 |
| E1 | Emitido | EnergyToken | 0xf5275298ffd8a7269df0c2aab574e94fc32229e977cfc8cc090dc1a9ab16eb67 | 555 | 248448 |
| E1 | Emitido | EnergyToken | 0x6f498a13940c64018cae168794ff735f53d1844d51ce168c1249bdc05e281d6f | 556 | 248448 |
| E1 | Emitido | EnergyToken | 0xde4fc69f55ad22cf61c25f16c84ab4e9a08620312bd966b6b895f25d8ec9a75c | 557 | 248448 |
| E1 | Emitido | EnergyToken | 0x8c9b0918961aa6ffc0ac1c2265a4222ea8b090703d118049fa0604a7aa8e5035 | 558 | 248448 |
| E1 | Emitido | EnergyToken | 0x8f16b54eca228c783b3653e9a373e54ba18c001bd9062c2600d2f382798398bc | 559 | 248448 |
| E1 | Emitido | EnergyToken | 0xcc5f2d1a8dbd5f064c56b25b4c79b37558d04f80b52e5f800ca1733c1d0075d1 | 560 | 248448 |
| E1 | Emitido | EnergyToken | 0xe6692cd841e65f30caabfd2f790b8f02498f143246554c7ad62f1b584696e9f4 | 561 | 248448 |
| E1 | Emitido | EnergyToken | 0x989e773608450e1882ee4aa6398c7fd3e72b7598257b4148d176d21124da67ef | 562 | 248448 |
| E1 | Emitido | EnergyToken | 0xe7d8f9b63cb4a9a41020d6b19acb74c448724bd2a7886e6a257b2d21e93c0597 | 563 | 248448 |
| E1 | Emitido | EnergyToken | 0x36552aaa5938d7de8e5936dbfbf0188fbc0a08e07fa1553d80437540e3b0624a | 564 | 248448 |
| E1 | Emitido | EnergyToken | 0x19e146181aacd71ec9cc3e9e5a3647591c946f61cec23c3af0e7868ff281cd00 | 565 | 248448 |
| E1 | Emitido | EnergyToken | 0xcdb7e2cfe491ddc6fdb8a25a2d1ec4aebfc673fb4ef458a1850abfcc05271e96 | 566 | 248436 |
| E1 | Emitido | EnergyToken | 0x0f02179331240b2bd71cce01eb48e36e27b682c3ce2ae2d400fe3bef61030375 | 567 | 248436 |
| E1 | Emitido | EnergyToken | 0xfffb112d47022c949c0eba1bbb4d062218a7fa0b096183bc8ccec65a409f20e7 | 568 | 248448 |
| E1 | Emitido | EnergyToken | 0x83ffcaf862374727deba710e22b17c6896b48427e7d23796e5532611543674a6 | 569 | 248436 |
| E1 | Emitido | EnergyToken | 0x480e067be8186b184c4bfc7155370e9cc511ae3975582e65fc2efe219bbb9c50 | 570 | 248448 |
| E1 | Emitido | EnergyToken | 0x09246247e815ce1a47855702cff7f7f6657fcd658fdf520a1e68ea5d5f1c6293 | 571 | 248448 |
| E1 | Emitido | EnergyToken | 0xf9496768b4f403e202dc95f4f2723348c496418b8490d93891684a8af9f5ca22 | 572 | 248448 |
| E1 | Emitido | EnergyToken | 0x409ad9a0f2e0b90f3509e9e13d8197ca1d732be5cc64269889f8588638f71fde | 573 | 248436 |
| E1 | Emitido | EnergyToken | 0x6740f0cc2840f1a1affb47f83ddfe741f5dd1fa1b1648285d610a5a15f112174 | 574 | 248448 |
| E1 | Emitido | EnergyToken | 0xc0cd6d00691bb5abd916a54fedb3821161b59cdfb38ca9a1e20d8f3b8345de2f | 575 | 248448 |
| E1 | Emitido | EnergyToken | 0x9b4fa04ca2e8ec1178a5eb6937b3ed2aa9745c9eae9209e720dcbf3c9bc2cdd6 | 576 | 248448 |
| E1 | Emitido | EnergyToken | 0x3ce01e600e8d0afe8b6ea64ba62498cd6e3dee7ac738a4ba63e07c208d8ec66b | 577 | 248448 |
| E1 | Emitido | EnergyToken | 0xfb928b27c4a3ad49c4174181d917b57904e6558bce1d8ffc5169ed992de20f4d | 578 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b97f03ada74a2b7dff3f2fe28e529b7ed9062626253d13959b4b64dbb99355f | 579 | 248448 |
| E1 | Emitido | EnergyToken | 0xdb8ccf7e3f83d1c0e0f0fd3d0d7d80a09fd0be8f7a03bc75100980a9831ba894 | 580 | 248448 |
| E1 | Emitido | EnergyToken | 0x5d7c44871252690bcc09383b5dd9fad0acb033b1152a8cec4a2033681cab8128 | 581 | 248436 |
| E1 | Emitido | EnergyToken | 0xb48194b786a2d6c167dffbfd907d7a096497c876612bef292a6332e5d806edde | 582 | 248436 |
| E1 | Emitido | EnergyToken | 0x7379192f89bc60daedb5732a29c4e78c5c889c59879992053a300fe1dc4e031f | 583 | 248448 |
| E1 | Emitido | EnergyToken | 0x2439954630f09493f9c7650e2b963b6460e061e5e80cd7ce87b5f21275185a25 | 584 | 248448 |
| E1 | Emitido | EnergyToken | 0x32bcd058ce5dcedcccc168a6d383b6304607d2231d28134aa66d123fe9d8bcd6 | 585 | 248448 |
| E1 | Emitido | EnergyToken | 0x565728c961fadd9c2b3c8ad29a25dbbcd730ee745af50410c0497cb054d53cd9 | 586 | 248448 |
| E1 | Emitido | EnergyToken | 0xdba759513cc841fdb5397969255dcffee2b7e5cd35c1008edb7e076f52affeec | 587 | 248448 |
| E1 | Emitido | EnergyToken | 0x3c0b66373c9793063e9bea44b608dd2f68de1f00b6a668580f0ba1b8932b30ff | 588 | 248448 |
| E1 | Emitido | EnergyToken | 0x4b3e6dcbd999311d357844b1d39350a2207d105cb4459717c2248615cd1be535 | 589 | 248448 |
| E1 | Emitido | EnergyToken | 0x9ad519bbe24640514ad4ea259f1ed94ddb243d7fc5c82ec00b6dec79cfdbe27f | 590 | 248448 |
| E1 | Emitido | EnergyToken | 0x3537f78ce24a1734afbdd0257e54079040de31709745cc000b5337868e553244 | 591 | 248448 |
| E1 | Emitido | EnergyToken | 0xa280e1e6384df76163d39f17479fe16d1fc3c15fa5113c7414845475be5373c9 | 592 | 248448 |
| E1 | Emitido | EnergyToken | 0x8b00d3090c90f30313c3315db11ec0bd17b573a1080351d5c73e21b725ea9848 | 593 | 248436 |
| E1 | Emitido | EnergyToken | 0x9d4d28ad6f21a2a4760a8660d80e5ed54e0eefe31c4302899a6622a7c140a150 | 594 | 248448 |
| E1 | Emitido | EnergyToken | 0x30fead492482c9de7934059e2705f676ef3d49715ff006e42256cc664caca48e | 595 | 248448 |
| E1 | Emitido | EnergyToken | 0xaae39252bb7fca18b1aa3a4a6c12a3911c0f5cde7cd51b287216774116f18b84 | 596 | 248448 |
| E1 | Emitido | EnergyToken | 0xd3d0c751a0ab350241519c67c12c5447883088cfc62433c5f61e01e56354cf61 | 597 | 248448 |
| E1 | Emitido | EnergyToken | 0x91858a981a3b94a689995fdec7ef2e4de8f83fa45429bfe67c77ffcee680386c | 598 | 248448 |
| E1 | Emitido | EnergyToken | 0x048ebe327d2db63ad46e5d26b59098abb2b3308ee5a3fb121bfde55d7415ae4e | 599 | 248448 |
| E1 | Emitido | EnergyToken | 0x58cc505ff8143f39cff6f042bd1b72c6aefe4e3014c735163ae4604618a24eaa | 600 | 248448 |
| E1 | Emitido | EnergyToken | 0x6a7c5297a1f765518a99dc303b07e5c1c315c7b7ec592d93d94bb26a39b893e1 | 601 | 248448 |
| E1 | Emitido | EnergyToken | 0x65f1f396b4624f66653285bd546e7ed3106cb24d0861113abffc6b7e6b746043 | 602 | 248448 |
| E1 | Emitido | EnergyToken | 0x3df06490a536825a4772b3fc69c063583e236164774b3cfffc64521e49169e2b | 603 | 248436 |
| E1 | Emitido | EnergyToken | 0xf6526bfa8b0b9e79b1f239ae99c139b02644020918b126c43b0568a279e531cf | 604 | 248448 |
| E1 | Emitido | EnergyToken | 0xa6840558db3aab47fd24a90d5ac2286188869d2447bfdc28d988b50c571de4c5 | 605 | 248448 |
| E1 | Emitido | EnergyToken | 0x24197dcb7697649018f0adf2e1ad049f09d1dc48c7621561a7ee07a4a9ad785c | 606 | 248448 |
| E1 | Emitido | EnergyToken | 0x9d4644beda0c54c8c22f28b48f2db5f949bbbf30f82f5fb9c9624397e36a552c | 607 | 248448 |
| E1 | Emitido | EnergyToken | 0x83e4dc40335d921de33aadec9d9a62708da037219ff7baeb89c4ac9c389190b6 | 608 | 248448 |
| E1 | Emitido | EnergyToken | 0x4140667bd71dc085fdf6b2821a8f8e2740870180366a391d7942ccac57b2bd2c | 609 | 248448 |
| E1 | Emitido | EnergyToken | 0xeb422b855b2281384b85934adaea0017e32bfc338e4b085d1a0c6c8f6d671a79 | 610 | 248436 |
| E1 | Emitido | EnergyToken | 0x63083001a4a9128cbf2266fb97a2ce8bdb336f096d0c206423f00b91885e2be0 | 611 | 248448 |
| E1 | Emitido | EnergyToken | 0xe3b252f7210789b54143a8210a835d50efa493860c6786e107ce01d9f7567ed4 | 612 | 248448 |
| E1 | Emitido | EnergyToken | 0xb06fdc5fa564784e04a711a6531e8992268df147e771a1ec72c7a2e8d8a4e80c | 613 | 248448 |
| E1 | Emitido | EnergyToken | 0xa3b87f728e2d3c338a2beb7f73bac708f6822d0bddc7bc23ca0bad8dfa3a4c82 | 614 | 248448 |
| E1 | Emitido | EnergyToken | 0xc2a66f28dd9c68f5621bd89a8f88bd2ddc3f1ad14e01f6cbe3beed147ff7acbe | 615 | 248448 |
| E1 | Emitido | EnergyToken | 0xc4cb511d30133536c922f7093bc20bc4cdfb2901e34e0ba744053dbce12cab79 | 616 | 248448 |
| E1 | Emitido | EnergyToken | 0x05725cdc86a8166f16c5c406ab53b0dc01f43ad34c9828f6331f5da944ebe1c2 | 617 | 248448 |
| E1 | Emitido | EnergyToken | 0x2535814c2cd73c4f85e889d6cfd3981b415364685595f2bec553d78b88e0fa87 | 618 | 248436 |
| E1 | Emitido | EnergyToken | 0x34a422e55d3955e67d57c8096b874622f72e1ce9e8d788755d3e6ff1acae2f64 | 619 | 248448 |
| E1 | Emitido | EnergyToken | 0x34f32fd76f0fc6135b2da7b45ac0bd2642e01b383dff4bd3fe70d5c16b509dd8 | 620 | 248448 |
| E1 | Emitido | EnergyToken | 0xeb62609928f8853870da7b7fa0c8e89156df79206d00df56b2e692a8fc821436 | 621 | 248448 |
| E1 | Emitido | EnergyToken | 0x340ec919ca3685560dffa94012a1635198b89bc7fbf4e3cf85b53778ee4e611b | 622 | 248448 |
| E1 | Emitido | EnergyToken | 0x7bebba0b4d33b39854204c4b10ee21927af7eaa298539c78fe5e1d5c0fa36b02 | 623 | 248448 |
| E1 | Emitido | EnergyToken | 0x4fd21cbe9ab6d471c0fb9cbe8c5f12b809912e75c5539ad19808332b85607545 | 624 | 248448 |
| E1 | Emitido | EnergyToken | 0xa01adcdc5afe041b03471c145ff442446e22997260e484f3ccce115c02f648b2 | 625 | 248436 |
| E1 | Emitido | EnergyToken | 0x9821b2ce1ddfe57707e82d72e422aa7d25227b4708f4401b516edcd708cdb009 | 626 | 248448 |
| E1 | Emitido | EnergyToken | 0xbf4486e645691a1b2216c3675559407c034190873f079a19631719e8c6d29846 | 627 | 248448 |
| E1 | Emitido | EnergyToken | 0x89684ca22998b323391d9398a0750ca5c97c07c6f0ee0084089f93cd90c7a7c6 | 628 | 248448 |
| E1 | Emitido | EnergyToken | 0x0b423b6531effb4b7b77defcf5657e19b831831b94fde25be7d9d61e5745b078 | 629 | 248436 |
| E1 | Emitido | EnergyToken | 0x131d28b4dc32124d2bdcc6fd872b49e696a9eb0f148601250a446a4c908409e5 | 630 | 248448 |
| E1 | Emitido | EnergyToken | 0xb6aefbeb1220a15d5d15dfdaf55ff42c76eea3e52b8a0761eca123b8045b87b3 | 631 | 248448 |
| E1 | Emitido | EnergyToken | 0x4b42a6e1641c04c196ec6aaa65a4a03f55457dd92dc7d6f5d4e1c7088c8d9aad | 632 | 248448 |
| E1 | Emitido | EnergyToken | 0xf20aa9430dc03601a4a976355c8ca65dfcb048dd104b68aa5b4a78f8af2e9a82 | 633 | 248448 |
| E1 | Emitido | EnergyToken | 0x0ab7845102fb1f195329dc409815603110b518ff1211c31fe7c6c681b7dd1902 | 634 | 248436 |
| E1 | Emitido | EnergyToken | 0x5717b31bc729c03000f44489c3187d31dafd77f2609b3fbf41d171420e12f564 | 635 | 248436 |
| E1 | Emitido | EnergyToken | 0xe94112f933a688b6c99df16e12bf33d23c017f2cd55a9d8e201f53d9338a181e | 636 | 248448 |
| E1 | Emitido | EnergyToken | 0x5eb820162561b83f9b9c004bb2a8b99f6f9bffeb0a112c5275bf0356a58fa50f | 637 | 248448 |
| E1 | Emitido | EnergyToken | 0x0a3d2dd57e8d999004a8c1d1b6a9609f4ce2e4087f84320ce558dafe3faa6242 | 638 | 248448 |
| E1 | Emitido | EnergyToken | 0x8a3de9463f3e98c4ce8c37f0454e3c4312109a6fcd2561e5f5040fa19ebe352c | 639 | 248436 |
| E1 | Emitido | EnergyToken | 0x9d69ed2bb9b727363e53bb42df55b4893220767600e1731d923b7a79ccef74b5 | 640 | 248448 |
| E1 | Emitido | EnergyToken | 0x8c64a9a4f12425716c78e1b9fde9790068a49f99e078515c6b1d9c9c4d8d05df | 641 | 248448 |
| E1 | Emitido | EnergyToken | 0x6f6744b8ed6df3d3d6fb8fca7ae0574dd1b7963f8f0913ed21ae7c30a39a6c56 | 642 | 248448 |
| E1 | Emitido | EnergyToken | 0xf7f4a64f17579b313500f2ff12354d90b5b7886007d400ae4acac5beef7ff07a | 643 | 248448 |
| E1 | Emitido | EnergyToken | 0xbff9b63dfd12957fc0e702624053c2af4da13060cb7ab67e864669b4cb9b8865 | 644 | 248436 |
| E1 | Emitido | EnergyToken | 0x712b3047043052cfd9deaa9d5510a6ed2fbbdbedc98e9ff18779dfb0ed8b3fbc | 645 | 248436 |
| E1 | Emitido | EnergyToken | 0x0a0e68e82a1c895140fc05614d27fcdcedf71f6b5a2a34d201dda811dcb7f614 | 646 | 248448 |
| E1 | Emitido | EnergyToken | 0x5f8931f42d2761f4f277bfd84fbbd4aecd5dd44e455f19d9a00189951540f962 | 647 | 248448 |
| E1 | Emitido | EnergyToken | 0x838fb1bfd6b001102d3e64e2654c9e874883e82c2362a70960ea2a29ed17b575 | 648 | 248436 |
| E1 | Emitido | EnergyToken | 0xabbd0f64f32d88828da9b20f9d5fd86707423d74ea8ff021eb4fd9ab89ceefc6 | 649 | 248448 |
| E1 | Emitido | EnergyToken | 0x58965a3ecb5bdb8074a09fb3296afddeb700cfd89e7be2f7f39727e2ea17618b | 650 | 248448 |
| E1 | Emitido | EnergyToken | 0xc8b02fe023a4c4d8668862fc4b3aada4c677a29cfdddddd5ae3cfc72d3a0414b | 651 | 248448 |
| E1 | Emitido | EnergyToken | 0xd3f51c9c1bc19cfafe88994472b45409d86319fe58d6ea5dc2e46aeb677eff69 | 652 | 248460 |
| E1 | Emitido | EnergyToken | 0x88bf43eb18c3b5396cb35a28a552d7d7cd18eda6996329b8c219db30be233400 | 653 | 248448 |
| E1 | Emitido | EnergyToken | 0x2656f11ff7f4db3dbabacb82f6d060406b1bea0caf9f3ac8b79e6dcc3a7abd9d | 654 | 248448 |
| E1 | Emitido | EnergyToken | 0x489371786bbc54610a0a4c2d98ee29bbcc92b08b5ca80e51926102b43573ac23 | 655 | 248448 |
| E1 | Emitido | EnergyToken | 0x72fe7357cde5fc5e14af0f1080402f584b7c94317397dcff85156e17eab26a18 | 656 | 248436 |
| E1 | Emitido | EnergyToken | 0xb5c7b6ae8092947719b105d1970a13d2fa176e380846414dd1ced7fbecdd5753 | 657 | 248436 |
| E1 | Emitido | EnergyToken | 0x93633309a37bd2efc097487c22d899334f987ece47b0e2486ab09d99635036d0 | 658 | 248448 |
| E1 | Emitido | EnergyToken | 0xce781ff94c07b563eab48ad07c3b84e74194edf8d43f5d41e1266f1f15895c3f | 659 | 248448 |
| E1 | Emitido | EnergyToken | 0x637c52117369c88de973fe13d6cd5086cfdcb1f9520070d0b558cc8c41617bc3 | 660 | 248448 |
| E1 | Emitido | EnergyToken | 0x6ffd2517cd7376641c3d5a344c60f5dc20df893fcbcca3624d19c85fe7a536e6 | 661 | 248448 |
| E1 | Emitido | EnergyToken | 0x4a29445709554103425a3cf10dc4dd86364eccbd8611c4bffce1ace9445c2d68 | 662 | 248448 |
| E1 | Emitido | EnergyToken | 0x370f748025136cb9c1f722dc8446beb319cd7b07d486fba6dd0f8bc22e3f7e8a | 663 | 248448 |
| E1 | Emitido | EnergyToken | 0x9c7b59862cfad7335b8e4d7385154a0bc44d0b208f6c04131bcdf8c42c37155d | 664 | 248436 |
| E1 | Emitido | EnergyToken | 0xd2274eb9f1e7b19ee0e0d0da8c520508d66fd26b3f2e17843e5eb117053db0ff | 665 | 248448 |
| E3 | Emitido | EnergyToken | 0x93d85e807acbd0568b7701fb7c2c700d892391b2b60e544c7741c657f55b5e6d | 866 | 140289 |
| E3 | Compra | MarketEscrow | 0x7c8fa86a87c7e92714820094eef70940e5925d66f52b6ee26c1d1e667c9bf298 | 868 | 277526 |
| E3 | Emitido | EnergyToken | 0x10164069f2d128f059d4768a514f68baf7e67e078b605a39d4ccf7926a3e4b67 | 870 | 140289 |
| E3 | Compra | MarketEscrow | 0x0053167f7a3017e974d5bb8fd66f18441f5ce4ef70164890a17ad500d8283a72 | 872 | 277526 |
| E3 | Emitido | EnergyToken | 0x8eff19097bdb6f10c1aa92824029282150116b565b6e75c59f848e7f6496643d | 878 | 140289 |
| E3 | Compra | MarketEscrow | 0xdce700c07d4d27b6687edaad4fdfd365ab70219b4358550e2df9aee9c24e0f4e | 880 | 277526 |
| E3 | Emitido | EnergyToken | 0x814abcd89427c0886023a4ad7a33b0776c0881e86420a4a7720a61f26a483be6 | 885 | 140289 |
| E3 | Compra | MarketEscrow | 0x68df12f86d733a510b1574cd58793b0c3ff32faebae9e54261fda11317208938 | 887 | 277526 |
| E3 | Emitido | EnergyToken | 0x23e501ff843a1d3bbd2ecea103718dce775069649e032dcaa6aa052216929a9f | 890 | 140289 |
| E3 | Compra | MarketEscrow | 0x558bb4d2344ba982c706f3e8cdc71b6c62197fc1a25d8d5a17472816af88b3c3 | 892 | 277526 |
| E3 | Emitido | EnergyToken | 0xb54294196a2cc4b8a83645e0ef1624fbd838f4b4c8b7459dd118c261e1c1619d | 896 | 140289 |
| E3 | Compra | MarketEscrow | 0x6ca792e3471be06271683a8129b925642b10c431aa4d777b3de45de19f73f49b | 898 | 277526 |
| E3 | Emitido | EnergyToken | 0x3ddcfb0bbc76e98bd1bc656d723b1b8ac8c983e578bb5b1dad6552bb19a183d0 | 902 | 140289 |
| E3 | Compra | MarketEscrow | 0x69858a9f7da271b3d8a4600652606746180938094781f08ef43ac5eb9adf3bef | 904 | 277514 |
| E3 | Emitido | EnergyToken | 0x57946e87c9857727e4238ab22a87cd108f52220fd445a5ea0286f1cdfba26e6e | 908 | 140277 |
| E3 | Compra | MarketEscrow | 0xdc798826b3900d12fafaad7864e1ac7950f03483f27e7ecf139562a00034cd7e | 910 | 277526 |
| E3 | Emitido | EnergyToken | 0xca2baffa79bfbafa17f2077a10d2d71b0bee452e8f03bdde654449791587b9dc | 914 | 140289 |
| E3 | Compra | MarketEscrow | 0xb4923089b24328fdf75d0182f573d7aaa07f9b1579e4469adb267b26076373c0 | 916 | 277526 |
| E3 | Emitido | EnergyToken | 0x0397a47eea180530e6f5792ab7350da9dee639e8d5e6fa772235f289bbd9c689 | 918 | 140289 |
| E3 | Compra | MarketEscrow | 0x537470a4987d73e2ec67d9d70348ba647a87f3439f941e7f0721a1ef5e2f40b7 | 920 | 277526 |
