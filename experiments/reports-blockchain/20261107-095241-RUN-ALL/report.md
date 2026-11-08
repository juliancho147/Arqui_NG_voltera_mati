# Reporte de corrida `RUN-ALL`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:51:36-0500  Fin: 2026-11-07T09:52:30-0500

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
| R2.8 | Latencia p95 de lecturas validas | **PASS** | p95 <= 10.0 s | p95=0.1260 s sobre 200 validas aceptadas |

### E2 — E2 — Integridad del certificado off-chain

- Veredicto: **PASS**
- Metricas:
  - `tasaDeteccion`: 1.0
  - `deteccionesPorForma`: {'byte': 14, 'metadatos': 21, 'reemplazo': 15}
  - `falsosPositivos`: 0
  - `p95VerificacionSegundos`: 0.005783

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R3.1 | Dataset de 50 alterados con >=1 por forma | **PASS** | 50 alterados; >=1 por forma ('byte', 'metadatos', 'reemplazo') | 50 alterados; conteo {'byte': 14, 'metadatos': 21, 'reemplazo': 15} |
| R3.6 | Tasa de deteccion de alteraciones = 100% | **PASS** | 100% (todos los alterados -> ALTERADO) | 50/50 detectados (100.0%) |
| R3.8 | Falsos positivos = 0 (ningun integro marcado ALTERADO) | **PASS** | 0 falsos positivos | 0 falsos positivos; 50/50 integros OK |
| R3.10 | Latencia_p95 de verificacion <= 3 s | **PASS** | p95 <= 3.0 s | p95 = 0.0058 s sobre 100 verificaciones |

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
| CertificadoYaAnclado | reanclar otro CID sobre compra ya anclada | **PASS** | revierte (CertificadoYaAnclado) | ('0x15742b5100000000000000000000000000000000000000000000000000000000000000b7', '0x15742b5100000000000000000000000000000000000000000000000000000000000000b7') |
| SoloPlataforma | emitir desde cuenta no autorizada | **PASS** | revierte (SoloPlataforma) | ('0xfe550097', '0xfe550097') |
| OfertaNoDisponible | comprar una oferta ya vendida | **PASS** | revierte (OfertaNoDisponible) | ('0xe0d6755800000000000000000000000000000000000000000000000000000000000000b8', '0xe0d6755800000000000000000000000000000000000000000000000000000000000000b8') |

### E3-CONTROL — E3 control — mercado SIN escrow (demuestra doble venta)

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| CTRL-1 | Mercado sin escrow produce doble venta bajo concurrencia | **PASS** | >1 venta (defecto esperado sin la guarda del contrato) | 10 ventas de la misma oferta con 10 compras concurrentes |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E1 | Emitido | EnergyToken | 0xb7f261e2c4d4c86a3db1d971c7e63b742a0b42899dfa628e4b2c5f05a5b623bb | 926 | 248448 |
| E1 | Emitido | EnergyToken | 0xbcbd12cd34af0d86434472b16b1b416aed6b66803e20d865d09c9861cb72a16a | 927 | 248448 |
| E1 | Emitido | EnergyToken | 0xac09b6818cd9ab43afb13a5788e1c4098d82cb9b6a0a0b6ffec1c50f8b3b9f40 | 928 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b0e41b53c24b4bed4139bbd9bc94264c1b9d7ad88ce3e1823a241870460b893 | 929 | 248448 |
| E1 | Emitido | EnergyToken | 0x7c36463137bc6d0bee20fe3f9d3df6cf4e7a9200a0dbe6efd691f01c927c8c7f | 930 | 248448 |
| E1 | Emitido | EnergyToken | 0x6dff717926cd187895ad6bd0b7783f9e231bd98bb7c04e0668c83d2d01aaf11b | 931 | 248448 |
| E1 | Emitido | EnergyToken | 0xbc4c179493f57fd028094782d10db10ec882d6205da58513c558f7c5efb31b15 | 932 | 248448 |
| E1 | Emitido | EnergyToken | 0xd34d4a3c6eeda392bec443fc965d75ba0b87baa65f3e86006a573221c61cb7ae | 933 | 248448 |
| E1 | Emitido | EnergyToken | 0x466863aaa00b0f0497043e61e7fc7df56cca53d610184a0d22c2065bf02aaafe | 934 | 248448 |
| E1 | Emitido | EnergyToken | 0xa28cdadf3c84f76e11bf8bc2bd3fdaa4e62f2743993caffccadcb9a411ab1f41 | 935 | 248448 |
| E1 | Emitido | EnergyToken | 0x4c00e5a9bbf17188ec5201df5d98e35130e320e964f7a85ff75cbc5d75dac452 | 936 | 248448 |
| E1 | Emitido | EnergyToken | 0xc8d8765338c49bae28bb83e2b8a335bd325a1395afe54c647bbe9b57c09ea3d1 | 937 | 248436 |
| E1 | Emitido | EnergyToken | 0xd4dcee18d89123cb80ec681e4e6d23e030671b5a4b0806ca09edfcd91cd14e22 | 938 | 248448 |
| E1 | Emitido | EnergyToken | 0x07d48b0dc1642e9007f5ef6ba599dfd3789e5d20dd8a7c2aca698746a3e872fd | 939 | 248448 |
| E1 | Emitido | EnergyToken | 0x8ae0ff610ed32f3a669beb5458e5dfb3e52f8164dfdcda4fd93322b4472be742 | 940 | 248448 |
| E1 | Emitido | EnergyToken | 0x584951de6f7cee019925dea6f5ed55573c4b503f2ecfd7f1fac149aef0c378af | 941 | 248448 |
| E1 | Emitido | EnergyToken | 0xb996a63009e1e93fa5e32ec5684877b522ff3dd5570a0d84183a8e2e72b14c8a | 942 | 248448 |
| E1 | Emitido | EnergyToken | 0x2a9298eec4ec071fd16136bc9396ec26cfd3410bbd9eee117bd09bce2b823cae | 943 | 248448 |
| E1 | Emitido | EnergyToken | 0x99b72269a2d397d49c44346937f34eecf8aac39ef39e80d30cc55f68209dbfbe | 944 | 248436 |
| E1 | Emitido | EnergyToken | 0xf6619c7511ea738ee29f566a88760b7b47723f32c5fe85e4a725af4c684632ad | 945 | 248448 |
| E1 | Emitido | EnergyToken | 0x30bc5e05b752cbd0e3cb0c58639a8e3505de115ed72a59c212b42115318df06b | 946 | 248436 |
| E1 | Emitido | EnergyToken | 0x96ce5b601758d37525a9c9c856f2c64545273dbaa82519c94af3cc1f8485565a | 947 | 248448 |
| E1 | Emitido | EnergyToken | 0xda9f6b98aff6ed9c384dbd6d0e26467548c784d8e1f09b52504c1a0aaea038f0 | 948 | 248448 |
| E1 | Emitido | EnergyToken | 0x1201932ba72b80d2130c082b021bfcf44a5c7aa0315144b4e103cfa14a5dd6e1 | 949 | 248448 |
| E1 | Emitido | EnergyToken | 0xe45ef22807c634e98777d329b00a1346de8538ab8feb78ff3143e2a4d5ab7a87 | 950 | 248448 |
| E1 | Emitido | EnergyToken | 0x69e5a9b598fbf76a3267c8c629a73a77c78e9bbe1fbc25acc04a56dbcb0dbb1b | 951 | 248436 |
| E1 | Emitido | EnergyToken | 0xeef37467571341ccd1802b646e776a6a32d7831704e830c4f41a25301a8b6683 | 952 | 248448 |
| E1 | Emitido | EnergyToken | 0x1a15fe87e8f4ff986f9c42054aa58451cafc47ef0e6aa5e48d99ae74eca84705 | 953 | 248448 |
| E1 | Emitido | EnergyToken | 0x05b2219e917b511a69eb597657ac535f6f8cfd01f1f5fbda9661f74c7a6b9996 | 954 | 248448 |
| E1 | Emitido | EnergyToken | 0xfa5be57b3b65bb7c5b58ff85980ae0cc5b5d4cd752b43e67958dbaa25a619dcd | 955 | 248448 |
| E1 | Emitido | EnergyToken | 0x15781d07aad6fe5fc9bccc5e07468862a0f2201b63d6440a2a65faa271469bac | 956 | 248448 |
| E1 | Emitido | EnergyToken | 0xc922c9605dc8571d2bee754600f7e5c88e7c649cf364adcf47f910c6676ab55d | 957 | 248448 |
| E1 | Emitido | EnergyToken | 0x6fe1dd5e844fa709015de6737be2ee39796e12b730db71307caa6ae8df687de3 | 958 | 248448 |
| E1 | Emitido | EnergyToken | 0xb38ba427b7d10ac9ed8e8417ad5fccb3bf86ba4c50c7d1c9b9016cc8c30da2b2 | 959 | 248448 |
| E1 | Emitido | EnergyToken | 0xaad67206bac1925168b80065bee61788104c3a29dd72a6f21d4d4571c2677213 | 960 | 248448 |
| E1 | Emitido | EnergyToken | 0x79bad3243e2e4a2d682b8358a4674a39a92e8c7b0aee348d4e079e37cda3d492 | 961 | 248436 |
| E1 | Emitido | EnergyToken | 0xf13d927b73115c32cc5d301f51dcf6dc7662dec25919a52df8091d223a666e88 | 962 | 248448 |
| E1 | Emitido | EnergyToken | 0xb856b6f78abbd59d81a3f8335d19b43d9ebcd66837a41c86c7ddff3acbae8000 | 963 | 248448 |
| E1 | Emitido | EnergyToken | 0xad0f4283f760c57f085c5c601d65d4f40105d1184fe50d8e7b68acd0c7ff1677 | 964 | 248448 |
| E1 | Emitido | EnergyToken | 0x2f964165cce80509cf9eceb2ea7b85110ad09cec57ca49a380957107abf519b4 | 965 | 248448 |
| E1 | Emitido | EnergyToken | 0xee5880a32ae151b3df737c2414f71ae94837863727bbb255d87fde89d32add1c | 966 | 248448 |
| E1 | Emitido | EnergyToken | 0xf8d1947dda0d0a63fcaafe185f090cccf7bfd549fc946201e9c2aa418123295e | 967 | 248448 |
| E1 | Emitido | EnergyToken | 0xaa0f9e541ff7b794cc1bdb8b54d0eef2fb7cfda775c46f0fdb4db362b54b64f5 | 968 | 248436 |
| E1 | Emitido | EnergyToken | 0xead111b2efb2000e5eb57cdcc0be0b3c13888304e938fa8b83f946e4d9c63d5f | 969 | 248448 |
| E1 | Emitido | EnergyToken | 0xb405d478838f635b31c3f330cda85866e4b04975e5a4ef61f05a917d795cc606 | 970 | 248448 |
| E1 | Emitido | EnergyToken | 0x0d675d96e42a1b27c3ec39e102f283df2116b79b9ea40515444abee559fc90ce | 971 | 248448 |
| E1 | Emitido | EnergyToken | 0x0c9f6abb0df3ff5b1e45a8a0cc317b5fc4911b7133eba9a2aa448addfa1851ab | 972 | 248436 |
| E1 | Emitido | EnergyToken | 0xca5c900c07a3ec29c043e38480e64f1e5c8ed1e75a9d2973669a4b1c4ad23d24 | 973 | 248448 |
| E1 | Emitido | EnergyToken | 0x5d57c2e99141279736ae0da0e217fb072194536c2efac01aedd7052c93139a10 | 974 | 248448 |
| E1 | Emitido | EnergyToken | 0xa808d71ad71160ee6a45577e71613d2ac75edb6da904f466542b64ad1262da89 | 975 | 248448 |
| E1 | Emitido | EnergyToken | 0xe75404d17e3b6d2550d26bd1cd8e0efb9025e7226360da8d5d6fca5c443b3f61 | 976 | 248448 |
| E1 | Emitido | EnergyToken | 0x3ad55ad3952f5541b89a61a331b4dde376aad6f7c916bf9cd086a84b75294051 | 977 | 248448 |
| E1 | Emitido | EnergyToken | 0x5e072e50279801a98f2b03b4304b25d040ff04e9c22d25319acc685ef488d7f9 | 978 | 248448 |
| E1 | Emitido | EnergyToken | 0x4e288223be1605648d0f9543dbeb9271d047857b4ffea129246c4ffe316075d9 | 979 | 248448 |
| E1 | Emitido | EnergyToken | 0xfd51d778ae709afc639b85f065adb8368297ad5e327955342769106c6adcfb3d | 980 | 248448 |
| E1 | Emitido | EnergyToken | 0xe071d78a807c10f854d1d734aa14af2ba5b58dd0f463f07a79624ddb00b6cfb2 | 981 | 248448 |
| E1 | Emitido | EnergyToken | 0xa2878401b4a528be70da641af7e0fa1e64e2796df0215593352a146cf54bfb12 | 982 | 248436 |
| E1 | Emitido | EnergyToken | 0x1fa0a696e48e3ee0bd0a4fe523af28a30d5c38aad4a052069a9c4548509a6916 | 983 | 248448 |
| E1 | Emitido | EnergyToken | 0xd20672503d9032e0cd7d44d50627ec37f348aabcd1a54071f20aa9552a499891 | 984 | 248448 |
| E1 | Emitido | EnergyToken | 0xf7ed299a5424953d68559640e012a43b36d14f030c49206556b16b6ad6c2ecb1 | 985 | 248448 |
| E1 | Emitido | EnergyToken | 0x76a07ad4b38581e882ef14ce86f8d6cb76e7cd1b6b26598960c672acfa8e5e05 | 986 | 248436 |
| E1 | Emitido | EnergyToken | 0x300961454ef39bc913cacbc46e8ef0daf4ea30ccd2a2663f5767647ea2b50bee | 987 | 248448 |
| E1 | Emitido | EnergyToken | 0x054f1e6c833d99f22963610af273464941be313cd48e1c12b159a2ef8e73d682 | 988 | 248448 |
| E1 | Emitido | EnergyToken | 0x49f9abc9cc7ae8c929ecbbcf2969cf9d4f4f23e8429f47b6f0f85c2cf9abedd5 | 989 | 248448 |
| E1 | Emitido | EnergyToken | 0xda4cb6aaea49fdbf88f6c2a57329a8cef0cde4c85cfdd62b8cc4dca556ee65e6 | 990 | 248436 |
| E1 | Emitido | EnergyToken | 0x9a67e15b6719e17c4792bfba2585c47beb3ff6bdb4cb20b6f04f78ad97a48fb8 | 991 | 248448 |
| E1 | Emitido | EnergyToken | 0x239edd79e2edca899c92cd66ede460fedf98bfce7a3331e077649c7449ec36b5 | 992 | 248448 |
| E1 | Emitido | EnergyToken | 0x3178bc870e169f27ee7f0b44e8ec60f50b1c32208dafcfb6e1ea0570136990a4 | 993 | 248448 |
| E1 | Emitido | EnergyToken | 0x0fc639bf2d51734e2f3e4cea109233cc9e0657e328bcdd9ab2f59d3aceebd19d | 994 | 248448 |
| E1 | Emitido | EnergyToken | 0x18d553d0746db6e24c86d18f22f622614ae2a9356be0d34cea5744030b2cd19b | 995 | 248448 |
| E1 | Emitido | EnergyToken | 0x32a92261d58f4c570b5c46bf077ffee365fabc24de7a9ba04475f9998f466b9c | 996 | 248448 |
| E1 | Emitido | EnergyToken | 0xad953d15aba26ab1404ff67fa43eb6595e73efb56cd2db766b720caf83d12bd7 | 997 | 248448 |
| E1 | Emitido | EnergyToken | 0x2e8bb5c74c0ca68c2132aa3a6bc3e701113c6d906eef7caf457c61698514232f | 998 | 248448 |
| E1 | Emitido | EnergyToken | 0xa41270f98a49f4fe7e3f6c4777f91ba64a8c6771d62db2706a967f1292387dfc | 999 | 248448 |
| E1 | Emitido | EnergyToken | 0xf63f00abf252b7cffe90ff01d204f115f90f7c2573e02968b8eac217d0f7f163 | 1000 | 248448 |
| E1 | Emitido | EnergyToken | 0x0e5386f501f25fa13b715a23e8af4d316582e0396331b5035eb35858d438f0d2 | 1001 | 248448 |
| E1 | Emitido | EnergyToken | 0xf939de06884fd5ced04b1b34f92dad4e81879a0fda1a188fe43defc31a809aec | 1002 | 248448 |
| E1 | Emitido | EnergyToken | 0x216d06806bd228e46c869721d2c17f60072d1d93cb9a2688251a27312cdb9009 | 1003 | 248448 |
| E1 | Emitido | EnergyToken | 0x487a651b1143fd1f2fe0015ced83d493d1e79ff2f876cf4dc149c337bd28f692 | 1004 | 248460 |
| E1 | Emitido | EnergyToken | 0x2e2f7656e80b315e5934f12333a07a5b31fd6984ead857fe3020b0a1aa838384 | 1005 | 248448 |
| E1 | Emitido | EnergyToken | 0xbeab3816b05a235799d2684efc4ee2de57e96238c766e5a1913c86645943a0a9 | 1006 | 248448 |
| E1 | Emitido | EnergyToken | 0x1fb7fafd88fbb29c006d0ae1f74fceb902ab062d13538b6eeb33d14b339f2888 | 1007 | 248436 |
| E1 | Emitido | EnergyToken | 0x1c4f461b6734f8cf91452cd811f8364636a423e596d8051a77ff9255785a53bd | 1008 | 248448 |
| E1 | Emitido | EnergyToken | 0xae74b3e8715317d3de5cb63c6e16ef3769f95021a7114402e38452fe28946621 | 1009 | 248448 |
| E1 | Emitido | EnergyToken | 0xaa44fbddd429118dc7bd934f0566914549b75e728613eed7182f7d9eb4e9f7a3 | 1010 | 248448 |
| E1 | Emitido | EnergyToken | 0x365a7c2ea2ce7fbf7bf6ee3f77cee837a3672cf754953e928b98368e7d19e3ca | 1011 | 248448 |
| E1 | Emitido | EnergyToken | 0x4fac51849ae4885c22fddbdfbda53e301f3570ffb8a406b935febfb4e8307301 | 1012 | 248448 |
| E1 | Emitido | EnergyToken | 0xdaf2c1f1b86125997e8701c581c5b59b5d669b14fa4f05cd9fcb2adfc548386e | 1013 | 248448 |
| E1 | Emitido | EnergyToken | 0x8296c0f612d87a82255834b2311ef179d83b711117f8eb0dcf4ed5a05d5f4e3c | 1014 | 248448 |
| E1 | Emitido | EnergyToken | 0x02ac2b0f2d9da9273160b92e294d637c16881d593a145ff29a9ef318d2de9492 | 1015 | 248448 |
| E1 | Emitido | EnergyToken | 0xf3ea5b22d4057d8fa948a054cfc580c3894db6abc9638e0bfb75def840ac14dc | 1016 | 248448 |
| E1 | Emitido | EnergyToken | 0x27e38621a5499b58f9410f732789b7e59a3aef2e7666f6d42f5210cc7aab8159 | 1017 | 248448 |
| E1 | Emitido | EnergyToken | 0x4e4da0e539fbc6d5c5d3742dadaea8121124756f04aac536c359a83d28857263 | 1018 | 248448 |
| E1 | Emitido | EnergyToken | 0xb2bf31a17695e89ab68e07575b47dfbf7539ea5ef1cebad9d824f1e139e9f717 | 1019 | 248448 |
| E1 | Emitido | EnergyToken | 0x33e7ccb0da6b839119a642ace621d1f7f0bd36b3e9604bd866a084a5c6ca1a96 | 1020 | 248436 |
| E1 | Emitido | EnergyToken | 0xdfedd6367113298c130256f93750df1bc716c04ee5d0ff66bd51d099b4c13869 | 1021 | 248448 |
| E1 | Emitido | EnergyToken | 0xa787c307bc1a67112bb3e0193f7b42748d510ba250cbb29449b2ff6214575c3b | 1022 | 248448 |
| E1 | Emitido | EnergyToken | 0xfd56b1af25447a4da542dc6bde864987efd21b90c98b02285a83426cb0574c63 | 1023 | 248448 |
| E1 | Emitido | EnergyToken | 0xf5d2d97de3247b92f1fd5cecf430163ad9221016880bcbcd3e4b0e1cb2bcf85e | 1024 | 248448 |
| E1 | Emitido | EnergyToken | 0xc30449788a751d42dbf22b0ee2af233bda90622fd652d139d3d8e3f9418a68e1 | 1025 | 248448 |
| E1 | Emitido | EnergyToken | 0x23cd2ecabd9ae1d1506681f70a1d690042244198bbc90929f4446c2003d35e7b | 1026 | 248436 |
| E1 | Emitido | EnergyToken | 0x8c1061d7c4463229a4e800b8da1fa88a006743d2a224a645c3603d8a5513dc3e | 1027 | 248436 |
| E1 | Emitido | EnergyToken | 0x987763b2a121ca816cdba1f7a3292e29dc5cc43cc93b388f9e5e8f958ae8033f | 1028 | 248448 |
| E1 | Emitido | EnergyToken | 0xbbaa55d18e8704ace25a54f0bfb15fa7d29f020c2a82206af7782a667b9e0f0b | 1029 | 248436 |
| E1 | Emitido | EnergyToken | 0x65fdddff8d57489ae736ca599eed91c1bbde2ffd9d1c5de4aef16c6a9db290cb | 1030 | 248448 |
| E1 | Emitido | EnergyToken | 0xc8be7b259be4ebe75affb4c037d0c6cd400f80322cc99e61429c8e1a527ce285 | 1031 | 248448 |
| E1 | Emitido | EnergyToken | 0x4f3c857d1251a8951d202df8210274aaed4095083737cce786cfadfc1da423bf | 1032 | 248448 |
| E1 | Emitido | EnergyToken | 0x663f36bb9e4b0cb7f87117402609567e89684d04027af9097d4f576a371cf6b9 | 1033 | 248436 |
| E1 | Emitido | EnergyToken | 0xfebd18c13aaf8862da680f4b6eab1ac4d3c3b67558e426d2f8e44f476b3d0c15 | 1034 | 248448 |
| E1 | Emitido | EnergyToken | 0xdcfe1a758c8151542f159f9ba7c05ac7d0f28392379f3ac6ebf41ae5766c5858 | 1035 | 248448 |
| E1 | Emitido | EnergyToken | 0x0ad433f33e9e653b2841356b7e0e680d60076223bf34a54b78433188b3055206 | 1036 | 248448 |
| E1 | Emitido | EnergyToken | 0x0f84f0fbcf991af0ed6acf4b8c3d877dc7306e7f02fe45b1b1e8679ed1221ccc | 1037 | 248448 |
| E1 | Emitido | EnergyToken | 0x13f6bc8bb1109b65f7ad1e88d578e6f9c6e80cbd426ecf092ad77762ac1e1e6e | 1038 | 248448 |
| E1 | Emitido | EnergyToken | 0xb3710f507ccb7dd89693b44beaf3d13d5503caf4e0562493877e49bb398f9d78 | 1039 | 248448 |
| E1 | Emitido | EnergyToken | 0x30824745342eb5d5ec5e959763c22cfaacd2d2492fa6c20dae4dc97e2e471c10 | 1040 | 248448 |
| E1 | Emitido | EnergyToken | 0x4cad9e5a3b22a2ab787e8ea10a0616cb6d8a7ae600780f93118fd2863cfaa55c | 1041 | 248448 |
| E1 | Emitido | EnergyToken | 0x472d506f6e1a3a25bad82f5332c2455d85f9357e97182b50e83b70bd530d664d | 1042 | 248448 |
| E1 | Emitido | EnergyToken | 0x63e9dce20ebe94ad644d16a9e8feaab7c6a261bbb049fa07b826d16ad226739a | 1043 | 248448 |
| E1 | Emitido | EnergyToken | 0xb5ce01f76a8cc29c1e23fb685c7ef93a59d20508964befdc2947fd4dfc86e77a | 1044 | 248448 |
| E1 | Emitido | EnergyToken | 0xfb8ec20893e0150f7f2ffaaac08f3dcab7c5f5c628fb202587ae6624cb143cd5 | 1045 | 248448 |
| E1 | Emitido | EnergyToken | 0xd9819e5383083e6a70dbf9d9cfbe89c8c77f54ee1e08d8ce69123796d6c58b88 | 1046 | 248448 |
| E1 | Emitido | EnergyToken | 0xbaa46ffb4068ba3f580ceecc3c9b0a1517cb6bb9c1c370ccef845a3d115712bf | 1047 | 248448 |
| E1 | Emitido | EnergyToken | 0x95e615144172871386699c5cac070738151d3375ec2f0df8937a30562b052d01 | 1048 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b30c6d9d3e71d6ce84e776edea39b814e7edbc9bc9d7619df9361bd0a8204e7 | 1049 | 248448 |
| E1 | Emitido | EnergyToken | 0xb1647d112b0a426f87fd4058116bd26d222cfe7b1acb1d193b64385d794d6d32 | 1050 | 248448 |
| E1 | Emitido | EnergyToken | 0xeaa97992be3cb604851d8a81a3b2084d7d6195e5740a91b9a74140c36ef58097 | 1051 | 248448 |
| E1 | Emitido | EnergyToken | 0xab7d176ad03108d0a8d0f10b5df17419b434d9c94a09c13468ed7d8cb0abe8e4 | 1052 | 248448 |
| E1 | Emitido | EnergyToken | 0x2f55d0fba9ccd56b61f1880b2aeca297015955cca21bf2eacc4e489a7031ff76 | 1053 | 248436 |
| E1 | Emitido | EnergyToken | 0xf91f0bd273aac445f4338562e6219c96228d6335cc9fbc9cdf8c4d0989ee4ba2 | 1054 | 248448 |
| E1 | Emitido | EnergyToken | 0xd1ef6683bfbd211d00a8f1d3f1de3801657b30ce2627d95d9d080992d3b65695 | 1055 | 248448 |
| E1 | Emitido | EnergyToken | 0xfab50c11588d80aeb10c4723c8c49641b7fb2d982b7f083b853fc8db5f888dd6 | 1056 | 248448 |
| E1 | Emitido | EnergyToken | 0xc7c03aec7c80b585ca713069f2d83c669d9537c4908b2a5aac726ffc90df572b | 1057 | 248448 |
| E1 | Emitido | EnergyToken | 0x84ff6d99ba589edccb3dafab970320fb7edc82586c352222de24c52e31c08259 | 1058 | 248448 |
| E1 | Emitido | EnergyToken | 0x295f4b88da3802c161d917c2d3bbf2ce5649049f1a28c05649e231036f7b5056 | 1059 | 248448 |
| E1 | Emitido | EnergyToken | 0x70913a5dc535e97c1711e2babec9e877bb5a10242a9b3301ac4a43a839f12432 | 1060 | 248448 |
| E1 | Emitido | EnergyToken | 0x2d6042fd5ee953002df8dbc7fea1cdcbc17853966e3cc3d5e14b72a59249dd12 | 1061 | 248448 |
| E1 | Emitido | EnergyToken | 0x952321fa44ee5fa615238ececa89baad8c527c4153572e3a0a5958ee017b851f | 1062 | 248448 |
| E1 | Emitido | EnergyToken | 0xa46c52e14d6df0bf09213df2dee3a5cd1249f544886ada19739bff3ee1a3e1e8 | 1063 | 248424 |
| E1 | Emitido | EnergyToken | 0x6d67f7561b11e24dfbdec12d88747967a1fcac072584ed11457097e35c768e5c | 1064 | 248448 |
| E1 | Emitido | EnergyToken | 0xf838f85c676ccf4f36b1ef83963284e561eebd00154e9b6a43330103b6118b16 | 1065 | 248448 |
| E1 | Emitido | EnergyToken | 0x65da14a401314797e8146b919d896d8bbad0d106306dd822b3e11167c3148514 | 1066 | 248448 |
| E1 | Emitido | EnergyToken | 0x6365ca81067f9769102d2567bf35b3f6cc9b4d6a9a2873be353f0812e775d12f | 1067 | 248448 |
| E1 | Emitido | EnergyToken | 0xdc7483629dbf61dac6a50ac71cb8d85c91a4eb0926b3cf61a8f7097270c062b3 | 1068 | 248448 |
| E1 | Emitido | EnergyToken | 0x0c29162414a8a4694205276ffa08940cd9968521fe98f6a11a8e7e9aa65b2adf | 1069 | 248448 |
| E1 | Emitido | EnergyToken | 0x94c4df8be464ad60854fc1724cf03fe5f1c75054bc75dda5040823bab8aa1092 | 1070 | 248436 |
| E1 | Emitido | EnergyToken | 0x2312c103e51686293e2eebf227d630f5d1fa3aa16f7b8ba3d99d45d7569c61f5 | 1071 | 248448 |
| E1 | Emitido | EnergyToken | 0x522e072123ac17c67db92f413951dbc843d03f91060d8b0b9f0feb3f07435158 | 1072 | 248448 |
| E1 | Emitido | EnergyToken | 0xd8b025552a35ff7d87bb14bca7a26a0d61b34f55a7bbe4530b2db49e5a000983 | 1073 | 248448 |
| E1 | Emitido | EnergyToken | 0x71d48d1a20d5c7f0b0b0dafd484afb59bfd00a13c7370f276f48636b83d4347f | 1074 | 248448 |
| E1 | Emitido | EnergyToken | 0xc4bbd1f61deb430bb93f9266ed381d4d56e6f3c63acefddd140aa52f44dd4a5c | 1075 | 248448 |
| E1 | Emitido | EnergyToken | 0xe8d8336ee9fe7d0bba6b22eae7258b654a8ba1c214216781e70068bf3f36d8e8 | 1076 | 248448 |
| E1 | Emitido | EnergyToken | 0xed4269f91effa94bfba32efd895a66a45f3346d13d30196630e399feccbd4059 | 1077 | 248448 |
| E1 | Emitido | EnergyToken | 0x7448a92f1448e80488e5d011bfabc926869124a7c1c3372855c63c5f23e21ff6 | 1078 | 248436 |
| E1 | Emitido | EnergyToken | 0x2d33218f9b725d6120672aea7194733492451b1a24fa42109a4d3b5adde089ce | 1079 | 248436 |
| E1 | Emitido | EnergyToken | 0xb07c9aa4a87a9cc5e62c671096dd31d2807435a6de460fca58f02076a8b40385 | 1080 | 248448 |
| E1 | Emitido | EnergyToken | 0xe84b5544250c2bcf9168890d36ed6de24776f412d22aac60c3a55a3e90c9f194 | 1081 | 248448 |
| E1 | Emitido | EnergyToken | 0x74a2f6c7d9008f3510ac1a49707abd79c823ef1a192c4d5696110897732a97f8 | 1082 | 248448 |
| E1 | Emitido | EnergyToken | 0x8f5640b2ad04e9efa51a0830e607951392e3c5ecaee6d265eef526aeebf44e06 | 1083 | 248448 |
| E1 | Emitido | EnergyToken | 0x6cc03b5967834428a40354972909dc6b694c97d199fe09fa1df1e09e2cb1f606 | 1084 | 248448 |
| E1 | Emitido | EnergyToken | 0x6cac748459cb75e503ca65ac43d287dea1d4c984c19a052ab5764f65838f7627 | 1085 | 248436 |
| E1 | Emitido | EnergyToken | 0xcd49c9c9cd1e7cebb52ced7362316605cab768429eb2b1fabded4650fb147b35 | 1086 | 248448 |
| E1 | Emitido | EnergyToken | 0xc245ce0f86eb2f0d86bc8c0b99f18453ee9d7f67db32c7c8ff3dfedfc12856df | 1087 | 248448 |
| E1 | Emitido | EnergyToken | 0xaf6c536d301695cd1c8d858d2d145999620ee77c6664e99ef1c3b64f0a3503b7 | 1088 | 248448 |
| E1 | Emitido | EnergyToken | 0x66557a269abf7f7eb8490117710cdc2dc3c8beb8fbb1e6d76c5111ea19b25921 | 1089 | 248436 |
| E1 | Emitido | EnergyToken | 0x9dd14e10e233dd6e98d25a6e7253f73c2fc96241fe1f18b61b8fd013d55777ca | 1090 | 248448 |
| E1 | Emitido | EnergyToken | 0x29c8b478b0ea4881e733449a4a2aac7ce725490fb29a1a94db81fe8f34b23f02 | 1091 | 248448 |
| E1 | Emitido | EnergyToken | 0x13dc2b2293e1b726cadd60ce3640b770df27efcc404a424e4c757e2932a78e6f | 1092 | 248448 |
| E1 | Emitido | EnergyToken | 0x5584e3c17e4696d4906f027764f4eebc4a15e79707f5fa8b5df14fc4ee6df4e9 | 1093 | 248448 |
| E1 | Emitido | EnergyToken | 0xcd70c91d1543957b9f0c3dc3dba9b5af951e89e788cf93300f84b5ecb1e57720 | 1094 | 248436 |
| E1 | Emitido | EnergyToken | 0x135754b5d764f1ada418dae8dac90e5ad0a18045ecb0a42e5240c88c26508d57 | 1095 | 248436 |
| E1 | Emitido | EnergyToken | 0x2d702c43d6a658166e3b6c0e3eb76dd833a705a5cbdf78e4c535d94a3163bd7f | 1096 | 248448 |
| E1 | Emitido | EnergyToken | 0x1cd111b90cc64acbd8b7dbdfe9e5a96a416e4452d15660338976af16a88874f3 | 1097 | 248448 |
| E1 | Emitido | EnergyToken | 0x17afbbf36b21169832048f99588de16ccf941ae18929d0c98d4d85f92fe4078c | 1098 | 248448 |
| E1 | Emitido | EnergyToken | 0xaaeda6f520ed7503963d52de57634a4efd7aa9bdb321e26ee5a364be9c547265 | 1099 | 248448 |
| E1 | Emitido | EnergyToken | 0x597d47a849b1b6cf8fcf871eb23539a3e9cd3589091b6c916ab227d8f97a8890 | 1100 | 248448 |
| E1 | Emitido | EnergyToken | 0x1c495225b32f5233098cd7fe8b2b75905327c105fd33879287e86a75e6d05db3 | 1101 | 248436 |
| E1 | Emitido | EnergyToken | 0xf73697eee3bf10ec814f338dc992074e007464d5f66e2d40fa1caac0a0d457c0 | 1102 | 248448 |
| E1 | Emitido | EnergyToken | 0x9c82c07354933b10332f10068e66684abb8c745e67eb4dc3cb9ff217ae99fe83 | 1103 | 248448 |
| E1 | Emitido | EnergyToken | 0xffc6cb79c2e281244b4448bc6eb7476b3b924c8491142c6326bdb890c27d2144 | 1104 | 248436 |
| E1 | Emitido | EnergyToken | 0xa2fb64ee11eb81785e8b5ad338b3e8ed9df9fb4d3bc490664fc6e950ef287be3 | 1105 | 248448 |
| E1 | Emitido | EnergyToken | 0x1f3a6ef7e180e949973a091c0b7148f285aa1da774389a00ef30415f1831cf99 | 1106 | 248448 |
| E1 | Emitido | EnergyToken | 0x02c196d01e40c8229a3eb233e21aa6a5c8638ae45dbca7d963d3da7ec36bd236 | 1107 | 248448 |
| E1 | Emitido | EnergyToken | 0x0a609054b66360617fdbdce7d484103e4f8c9c5c3b3c058f60d9995d3f445f37 | 1108 | 248448 |
| E1 | Emitido | EnergyToken | 0x35f0574a60f53b7be1369ea351fca979d976a6ad4820c31efe9e0bb0b9378ea4 | 1109 | 248448 |
| E1 | Emitido | EnergyToken | 0xa83e8d0de0524eb6bfc9098682c27e78764cd8c79bd6eeee19da9d80deac655f | 1110 | 248448 |
| E1 | Emitido | EnergyToken | 0xfdcef7085efccfa944340f71e116bbcd5eaa8fd3428232c5e1025d7ad55dced3 | 1111 | 248448 |
| E1 | Emitido | EnergyToken | 0x86f832526a84ed91c7aef707a48c0dd1ef99cc0a05120eb850a6fd711c8b2e70 | 1112 | 248460 |
| E1 | Emitido | EnergyToken | 0x93378d0b36fa4d97853d85a01920ca900f6643143a4c81f1b368e95fe5c183d4 | 1113 | 248448 |
| E1 | Emitido | EnergyToken | 0x560e1699a4a9f007246b77ae33b326d9555d1935495245dead4c45fdd153553f | 1114 | 248448 |
| E1 | Emitido | EnergyToken | 0x19bf3e570406d5afa6ecc6598833b5c23df8f51ea0d61eaee8e9f20ce2b5dd00 | 1115 | 248448 |
| E1 | Emitido | EnergyToken | 0xccd86d4c46db9560917d97499d43d71447d3e5e3a90e20ec288f2dda60505ad9 | 1116 | 248436 |
| E1 | Emitido | EnergyToken | 0x8923048ea4b7f91f5ae11782f9e377d725e9a49e4b1f19e9336442b82b6736a0 | 1117 | 248436 |
| E1 | Emitido | EnergyToken | 0x1af59005ee86cf84c6e4c0b0e7056be7d6937f75a0f748db0ae02f9bf73d0e65 | 1118 | 248448 |
| E1 | Emitido | EnergyToken | 0xd6c39573a50d908d88a50878d0d6e0fd7d224cf44f2965529a09f03d38a1782e | 1119 | 248448 |
| E1 | Emitido | EnergyToken | 0xf6f78ccfe8835b206e901f86eb67b68276a852bd1a1eba9b890c31497a9b40e5 | 1120 | 248448 |
| E1 | Emitido | EnergyToken | 0xab7e22e6b3e8149370e274a7c0d7d15ec698215b0e559e22e417b263da2a242d | 1121 | 248448 |
| E1 | Emitido | EnergyToken | 0xdc320ad5b8c21c138e429d4cda39b0ac04f37a661f617ac45caf6dcee9c592d2 | 1122 | 248448 |
| E1 | Emitido | EnergyToken | 0xf4bd4561b74e394b75e2c4512c7d75612d16efba5cbc70f8e86b55ccc54792de | 1123 | 248448 |
| E1 | Emitido | EnergyToken | 0x8ff71fab8d9975b93d311690dff8455649dc513b3f6f9958f792c707e8947611 | 1124 | 248436 |
| E1 | Emitido | EnergyToken | 0xed7d481ed82321baeafe77be519711f52a7e066f172f81d7173d6c4591065c49 | 1125 | 248448 |
| E3 | Emitido | EnergyToken | 0x5dcb06342bdcdcff479ff5319141377873e9a7983f6d200f0ab142f54150118b | 1326 | 140289 |
| E3 | Compra | MarketEscrow | 0x064769c86e3099e16436b43c641b5609819ddf65b4fa626b794d225cbbefb3db | 1328 | 179606 |
| E3 | Emitido | EnergyToken | 0x18a8ad7b404a024eb6cde180761dd234ac2f24cefd905004abbd5934aa774bc9 | 1331 | 140289 |
| E3 | Compra | MarketEscrow | 0x2a35476fabfad19a36e42f16a479914ab6260059b2f058e60358ba97be53d92c | 1333 | 179606 |
| E3 | Emitido | EnergyToken | 0xc403d94b98b34510e858e87b48743dcc820433ccfeaf5157dce08a4677fe66f5 | 1338 | 140289 |
| E3 | Compra | MarketEscrow | 0x9c0555664767cb3f51718039d2bc4c558f4b6ef7af85842de444cccf6746d559 | 1340 | 179606 |
| E3 | Emitido | EnergyToken | 0xc4d6f844dcbc92640096fff169790e82cc9f36c6af956300458b3c2c4755357a | 1346 | 140289 |
| E3 | Compra | MarketEscrow | 0x25c742f5972c7f5ea07709c03c541ee19178c13e49ba3ae227bc78e131eff436 | 1348 | 179606 |
| E3 | Emitido | EnergyToken | 0x8edc2b4f2e17e25c94866c205cf52e185726cca0103d1f5b0832252f4569da21 | 1352 | 140289 |
| E3 | Compra | MarketEscrow | 0x7035ce23d34c968bba7c31f7039ad3bf63e0c0bafac0a24328c9935dbb98ba59 | 1354 | 179606 |
| E3 | Emitido | EnergyToken | 0xd03395b4f42b4a9a3279800e97551f46ca63e890335c2e73753bce793e0f6805 | 1358 | 140289 |
| E3 | Compra | MarketEscrow | 0x7f5225c9646b4b29221f1d61a5504b911feeacf0a7398507ab716df225af4099 | 1360 | 179606 |
| E3 | Emitido | EnergyToken | 0x3f2717e45c58b60c4c3f90f35bf8cd8f7fb56d1ebaed432179ff50396af37b64 | 1365 | 140289 |
| E3 | Compra | MarketEscrow | 0x5927b2843c71d73c0c6a477850fb30b7804482c739d05f1194840197dfe0e323 | 1367 | 179594 |
| E3 | Emitido | EnergyToken | 0x7e6efcb7a18047636970679732941a73c1f0a42958d672df01ecabf015749188 | 1368 | 140277 |
| E3 | Compra | MarketEscrow | 0x5dcb4f333796a3ba84c8e4302bde55af4ea04a6f411a64fa0bfea83335df0a48 | 1370 | 179606 |
| E3 | Emitido | EnergyToken | 0x731c35fd7c8d96828d94a2e7b5c785e2d0808c532574a4b905a9656852b0b14f | 1374 | 140289 |
| E3 | Compra | MarketEscrow | 0x9cbf9476abb0633e42206677ee5c6125d5e51b36745af295b9d11b8f1432aa8c | 1376 | 179606 |
| E3 | Emitido | EnergyToken | 0xb8285758738fdca355a7631fd8dc909a620aa213909b0abbdc6cff2d919ff25c | 1383 | 140289 |
| E3 | Compra | MarketEscrow | 0x5863ae0afd779fdcd04965f5e162532971a3d99c3f7bdec203ad7615015f87a8 | 1385 | 179606 |
