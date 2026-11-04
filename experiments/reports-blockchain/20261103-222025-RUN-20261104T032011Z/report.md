# Reporte de corrida `RUN-20261104T032011Z`

- Veredicto de la corrida: **FAIL**
- Inicio: 2026-11-03T22:20:11-0500  Fin: 2026-11-03T22:20:25-0500

## Cabecera

- `runId`: RUN-20261104T032011Z
- `repeticiones`: {'E3': 10}
- `cantidades`: {'E3': {'comprasPorOferta': 100}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge Version: 1.9.0
- `params`:
  - `seleccion`: e3
  - `experimentos`: ['e3']
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E3 | E3 — Tokenizacion sin doble venta | **FAIL** |

### E3 — E3 — Tokenizacion sin doble venta

- Veredicto: **FAIL**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | **FAIL** | 10 ofertas publicadas | 0 publicadas, 10 fallidas |
| R4.4 | Exactamente 1 evento Compra por oferta | **FAIL** | 1 venta por oferta en todas las ofertas | 0/0 ofertas con exactamente 1 venta |
| R4.5 | Conteo total de dobles ventas igual a 0 | **PASS** | 0 dobles ventas | 0 dobles ventas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | **FAIL** | diff absoluta 0 kWh (conservacion 100%) | tokenizados=22965, validados=0, diff=22965, conservacion=0.00% |
| R4.7 | Gas consumido registrado por operacion on-chain | **PASS** | gasUsed por operacion | 200 operaciones con gas, gasTotal=49689228 |

## Metricas incumplidas (FAIL)

### E3

| Id | Criterio | Observado (valor) | Umbral esperado |
|---|---|---|---|
| R4.1 | Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes | 0 publicadas, 10 fallidas | 10 ofertas publicadas |
| R4.4 | Exactamente 1 evento Compra por oferta | 0/0 ofertas con exactamente 1 venta | 1 venta por oferta en todas las ofertas |
| R4.6 | Conservacion de kWh: tokenizados == validados (diff 0) | tokenizados=22965, validados=0, diff=22965, conservacion=0.00% | diff absoluta 0 kWh (conservacion 100%) |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E3 | Emitido | EnergyToken | 0x95aa4cbbbe86b76d6621b63e811779ce310404235f156a663a6ad64776be03f7 | 3 | 248448 |
| E3 | Emitido | EnergyToken | 0x1a9fe666aed89b4074f3dbd65ff8d2b1a9aeae658fae8933e8140a2aa45232e8 | 4 | 248448 |
| E3 | Emitido | EnergyToken | 0xe3797c0c3b3e641050bb8c1d232d83c55fd70606a4db3e8957ba44eb866083c6 | 5 | 248448 |
| E3 | Emitido | EnergyToken | 0x6c3c796f022515a172c609fb7a8c8a8c69e3ab12cb504bd2c0b25f948ec0d892 | 6 | 248448 |
| E3 | Emitido | EnergyToken | 0xb6441c09f700fb3ac35e8d5467b4ae22fa6528c59101eea0a4a400ba6a6614b0 | 7 | 248448 |
| E3 | Emitido | EnergyToken | 0xe51cd4e81c7bcd596e816f5828d6c24873a8905c2177d027127133f0f902dda7 | 8 | 248448 |
| E3 | Emitido | EnergyToken | 0xf46a7dff078c3810cf48a5d62fa3b5b598a5c2c249f51f3657276730efe6877c | 9 | 248448 |
| E3 | Emitido | EnergyToken | 0x5e1ed96b2144134c49d7c174e575ea2daf5dbdeb4c8d520ae5d20e87be1d5468 | 10 | 248448 |
| E3 | Emitido | EnergyToken | 0x7b43664be3804cfb95cbfd078b74f717fa950d39623fde54aa61b510c71db912 | 11 | 248448 |
| E3 | Emitido | EnergyToken | 0x78b4f7ce6a36deeea443412a3933631106064e5666285851afd3f9db95d45329 | 12 | 248448 |
| E3 | Emitido | EnergyToken | 0x6c53df77a43ca8a61368ac6d6d083ca018096ab96c1ede59aaccd52645ea5b8e | 13 | 248448 |
| E3 | Emitido | EnergyToken | 0xda3abec6360b63912cf404abea2268fdab3ef9ec5ec66989a9dde960cef5a46d | 14 | 248448 |
| E3 | Emitido | EnergyToken | 0x9fd7edfbad7332307761ecadae8712135c7d65738e1b0556a0270efcac8b4335 | 15 | 248448 |
| E3 | Emitido | EnergyToken | 0x59648f93c5f28780fa1f80ddd860686356237d264a9729cebbdfc9cf4c655227 | 16 | 248448 |
| E3 | Emitido | EnergyToken | 0xb96fb36bc5e70ef506110be1b5167bf42183bb35fe6608e794e3e27a60f51522 | 17 | 248448 |
| E3 | Emitido | EnergyToken | 0x73ec09ded4198ce6294687c7d2e59c643292f3f8e0dc15b46f6e1b3e776b70a1 | 18 | 248448 |
| E3 | Emitido | EnergyToken | 0x5c0c9ce7ee1188c740b40c1427d250f65c0ac217a4c913d9005dc9bc5bb4c1ce | 19 | 248448 |
| E3 | Emitido | EnergyToken | 0x41a4858c530185bfab848d24ba88c2e99f9473051657054a698be22784615f2a | 20 | 248448 |
| E3 | Emitido | EnergyToken | 0x692337a68e66d01787b71c61d16b83b37af4673e31b8d3a122bbedb98413b76e | 21 | 248448 |
| E3 | Emitido | EnergyToken | 0x991fd4a18bf0b79f5bb72f572c4f5795f07e9b05ba791999776c723c431b3530 | 22 | 248448 |
| E3 | Emitido | EnergyToken | 0xf27769364f0c596c08d0ee71a31ab12f534b89a00e8e5e3c42c145cd565e170e | 23 | 248436 |
| E3 | Emitido | EnergyToken | 0x840030b156c6a417f109f014ea4dbe741967ed291a518be55b633adbe37b839d | 24 | 248436 |
| E3 | Emitido | EnergyToken | 0xb0bac4a5498379ab043ba814bc1084788fc5bcea36dea5864cb99d163e24d324 | 25 | 248448 |
| E3 | Emitido | EnergyToken | 0x90e7da662eea23b0aec5d9b95e09dc14232353556ecc5d8ab000e29a35a9810e | 26 | 248448 |
| E3 | Emitido | EnergyToken | 0x72493d12b2b42fba20389678e77ae4065e4d0815d8d18628b07fdfb3bdb227c8 | 27 | 248448 |
| E3 | Emitido | EnergyToken | 0x03a84e21ba2bfa178732a071777f8b72f9180b3cd4045383ee8b0ae818d48847 | 28 | 248448 |
| E3 | Emitido | EnergyToken | 0x19b0b54134db4b271dc600d255f7b48efc7646eedaf34bddd6bf3eb84aa79f27 | 29 | 248436 |
| E3 | Emitido | EnergyToken | 0xdc1603db19dfcb974f478b56305babe7d0ac698c40e42feea75c928cd9e81c75 | 30 | 248448 |
| E3 | Emitido | EnergyToken | 0x051b954009b166c5d85795a574330cdd4f06c12fec260b556b6ce365a69dc6b2 | 31 | 248448 |
| E3 | Emitido | EnergyToken | 0x3fc788f44eb80f2e7d55b14047460a297a04a87c8617162fe1f3dca177d9b7da | 32 | 248448 |
| E3 | Emitido | EnergyToken | 0x5f8603adbfc26c9c828eb2cfe6b3dfe48b882263a6ec2ee676b3310fbdba2460 | 33 | 248448 |
| E3 | Emitido | EnergyToken | 0x6b7076196680b9d3ae1b19fb9ea6894d4db1cb5f8a4f7e28f8209052ecd1c7f1 | 34 | 248448 |
| E3 | Emitido | EnergyToken | 0xde1b44d0380ed4ef79ee685567de4fccbab64dc0ac2661acf6d1f0c281aca9ba | 35 | 248448 |
| E3 | Emitido | EnergyToken | 0xfcba78507a56f510c9473199d74e982d13a4100ecd47819324eae44be60da012 | 36 | 248448 |
| E3 | Emitido | EnergyToken | 0x394672452412381e6332ac94999eff315f6268dfdae20f6b994a2d89bb507619 | 37 | 248448 |
| E3 | Emitido | EnergyToken | 0x4bf70475f338f13026850ae2e52df19faf4dc8c133c039cccf026e56e6281bbe | 38 | 248436 |
| E3 | Emitido | EnergyToken | 0x6a38aa1f5474e782e99bd4ce0ff177c6a9e3bdda6396e55b6640049f568dd526 | 39 | 248448 |
| E3 | Emitido | EnergyToken | 0x1825dde36c96c56c0faca61252e20938b332ec904189a4feebce1fe3f6d737e8 | 40 | 248448 |
| E3 | Emitido | EnergyToken | 0x9ad27e3db0b9dc5a0b6891e3ef19bacf1e3d8cec21e9a61ed4e4b060fecd36c4 | 41 | 248448 |
| E3 | Emitido | EnergyToken | 0x807c1588c836a583532a2d8a8bd58840c867089322b04940e3cd09c07be0cf7b | 42 | 248448 |
| E3 | Emitido | EnergyToken | 0xa1b5a5d67578d461ebc98f300e917d4ac40eaa9efa4107d5d0465fd274b26d97 | 43 | 248448 |
| E3 | Emitido | EnergyToken | 0xf60e36f50469827441ba7ed7fd48ae8d43af60ea189433792d8fffdcdb8bec52 | 44 | 248448 |
| E3 | Emitido | EnergyToken | 0x4ba0c51baafe0354280f2ae51033284589c543f36808985c6595ca327c800b9f | 45 | 248436 |
| E3 | Emitido | EnergyToken | 0x4de2a24d45f9cb165c3e3baf3105a475d4cea38a2e17a6c2954aaf61ce4b3d64 | 46 | 248448 |
| E3 | Emitido | EnergyToken | 0x418deb4094a20de11a5c99f82d26fea323710ae754a3ed6cafd7882beae2e9e2 | 47 | 248448 |
| E3 | Emitido | EnergyToken | 0xd25e2dffb245f54c9e5f924c2c39eefa2b56814c705fcbd22914f8321a0d0fff | 48 | 248448 |
| E3 | Emitido | EnergyToken | 0x04cd99643e8cd67959be433202eefdd37d6556b1d3c1b4f6b3ff6bbf28b0f060 | 49 | 248436 |
| E3 | Emitido | EnergyToken | 0xd4f6ffc6de75aefc8b1c7f1c269094fcc2bdfaa262c3c5a039509ad49b06cc10 | 50 | 248448 |
| E3 | Emitido | EnergyToken | 0xe23afc8f475fb76d092020b8e5437ba69bb27b5094d6c8954085d40161786bae | 51 | 248448 |
| E3 | Emitido | EnergyToken | 0x44bf739df3fe06262efb150b895d19543b7cf2256da7c7ab252dc50e3293fd7e | 52 | 248448 |
| E3 | Emitido | EnergyToken | 0x2d9fb547d52fe439523f21a768a5c8e83f5031935999b459e587f0d496ff5c21 | 53 | 248448 |
| E3 | Emitido | EnergyToken | 0xb2a56c0e298df4a3e8bfd883219e78f2b03f5a6dccfaf847272284dea7bf7f3a | 54 | 248448 |
| E3 | Emitido | EnergyToken | 0x7cb83115f8994e1a553045b0c40f05e498cf6db6cc3c91b63ff93836898e22c1 | 55 | 248448 |
| E3 | Emitido | EnergyToken | 0x46c771bc69a0d14de9f259bb462a6c89baee3215dea12c1851ee20bdac806824 | 56 | 248448 |
| E3 | Emitido | EnergyToken | 0x81b6cc250f2468b602b2c40c194ae786d261ecd95c3e155e7e43b7f2a7ac87fe | 57 | 248448 |
| E3 | Emitido | EnergyToken | 0xb17fee7133df29ef2dd6a50b7312e85cac55cafd2e1f651b78bd104dbd0f0dae | 58 | 248448 |
| E3 | Emitido | EnergyToken | 0xaf3ce21a83640273555f305ef8289f9dbe1ef6fe40494ae0d5dc1bf777d977c8 | 59 | 248436 |
| E3 | Emitido | EnergyToken | 0x039e619c36eafd37b1323a1faf974cabd4318f64c0650c3ee07000f1810221f2 | 60 | 248448 |
| E3 | Emitido | EnergyToken | 0x3c3c4dab3491fb9211de178a3f86c763313425e49b5479922f14e65d15122d16 | 61 | 248448 |
| E3 | Emitido | EnergyToken | 0xf15e3f20332732b840271215a4be32305b9d85fee40cd7f09ad68dcc01d02283 | 62 | 248448 |
| E3 | Emitido | EnergyToken | 0x331bffeaca40666f0bb16374360d0aba5ccbda4efe1fa119b813167ff956fc99 | 63 | 248436 |
| E3 | Emitido | EnergyToken | 0x6288f13dccad3605d48bbbfa39a7a7325e4133fe130daa1e723cac025851b4be | 64 | 248448 |
| E3 | Emitido | EnergyToken | 0xbc7a35d6d3f746458c08c5016fbd9f1773c629eca1157c05d53a319cae381c9e | 65 | 248448 |
| E3 | Emitido | EnergyToken | 0xcf4648793620864abe3b48eb7a5df82d5a59dc20378e340b5e2b406bdfe2825f | 66 | 248448 |
| E3 | Emitido | EnergyToken | 0x833fff169f10c5298ae09e7ea2a509d7de65f6a77efb5f4d118434555a2ab176 | 67 | 248436 |
| E3 | Emitido | EnergyToken | 0x0eb21c1595a70d8416e0bb906437cd4040ffae79146cd63cb6e65a980bb98b6b | 68 | 248448 |
| E3 | Emitido | EnergyToken | 0x005ab6467389729ef8a560dc41b77d8d1349901b7aa71065d288579c37313718 | 69 | 248448 |
| E3 | Emitido | EnergyToken | 0xb4857f1a1d4d26a310cc00250c668a990514c18ce2a7255e3cf36e4a1bb0daaa | 70 | 248448 |
| E3 | Emitido | EnergyToken | 0x9c2b6e65bf15c3870e707bf248c3b182634cc696d304eb83b74a4ab3096981f5 | 71 | 248448 |
| E3 | Emitido | EnergyToken | 0x2bca81d522d9d0917d1669ef183b8edaa9bce0ff0dbb37fc7b3445a841fa493d | 72 | 248448 |
| E3 | Emitido | EnergyToken | 0x04595054630e0f151f15d978637a5332c809024b9ff6b6f93c3fb789d4797c5e | 73 | 248448 |
| E3 | Emitido | EnergyToken | 0xe03c6b37b31e6a9131ff8d7651633925933a3df249a40bbc567eb98ff5da99ef | 74 | 248448 |
| E3 | Emitido | EnergyToken | 0x465ae34a4810898f45e7fe8b4894bbb0b3c8b9bfd4d68b9c5f771618ffac7178 | 75 | 248448 |
| E3 | Emitido | EnergyToken | 0x672518626faf89a2c9b5e4b82b97b9e4da276e14a05bb6a17e6031481411e981 | 76 | 248448 |
| E3 | Emitido | EnergyToken | 0xd39100bb4330de1c0c3f2ba1688d061e44090d1aa7eedd52ca1bbce4e201d209 | 77 | 248448 |
| E3 | Emitido | EnergyToken | 0x55c1605171f181d46938d4f8285f91aa32d3465463cdf380bd29e328fed77460 | 78 | 248448 |
| E3 | Emitido | EnergyToken | 0x9d1be81263de1f49d4f15cf7dcb92774cd27e499ffa402c0ecfff40a882173d5 | 79 | 248448 |
| E3 | Emitido | EnergyToken | 0x26de33d4da9981f3f741ea4b7c18829af9290816ed8c41e8728551dfe7fa17a1 | 80 | 248448 |
| E3 | Emitido | EnergyToken | 0xfcfd4443c695551d1cdeb7e1040d6d69f512555ede799789943d27f0ec373a8f | 81 | 248460 |
| E3 | Emitido | EnergyToken | 0x5d5b42d733e4e528438c12f76928c9be5881d8947e1ef1b4a9f63890195d7445 | 82 | 248448 |
| E3 | Emitido | EnergyToken | 0x7e27c112a164dd39fb46ff5928a2b99a768e249d6d7e8da4fd40e6ff69a67172 | 83 | 248448 |
| E3 | Emitido | EnergyToken | 0x8171b5a21638f7488918cdce7081d84334537f43476727356723786bb0c5e805 | 84 | 248436 |
| E3 | Emitido | EnergyToken | 0xda1561068fde046bb612b4ce1d1081ed04ff8f503db2c911976561def00eb252 | 85 | 248448 |
| E3 | Emitido | EnergyToken | 0x505d7e6a233fa2c8cb9fcdedcafe03b01cedddb928085990ea2426582b6a1142 | 86 | 248448 |
| E3 | Emitido | EnergyToken | 0x3b917cdbd9e9228435912e2155c64d8e039e166662918faaaadb014aa17a9b2c | 87 | 248448 |
| E3 | Emitido | EnergyToken | 0xc64377898c14290bf71f56ab29b0fa29bae0fa4eb2bf6cb5ad4dd5f4fb4f40bf | 88 | 248448 |
| E3 | Emitido | EnergyToken | 0xd289e6ffb668f529e2ca1a5dd9c7e0a48c13e183a83b0bcc95bd7fa33d9d828c | 89 | 248448 |
| E3 | Emitido | EnergyToken | 0x429c82ab277cfa75ba14570e048563358a1dce94db8289e301f97da9b4f78b69 | 90 | 248448 |
| E3 | Emitido | EnergyToken | 0xa95da04742f2c807df5b62b0c81466d8dc828297debc2bf991f56022d066f7a2 | 91 | 248448 |
| E3 | Emitido | EnergyToken | 0x8b5cb3fee702a8d8fa1029df1542473cf529ed52b430ada35bedeca119e71828 | 92 | 248448 |
| E3 | Emitido | EnergyToken | 0x99126c81d42d65461f1fcaa746b09bc9b62a6491346b6dfd88764b4307e0b6e1 | 93 | 248448 |
| E3 | Emitido | EnergyToken | 0x4116ca66642f070c0cfaecc5e1a84cd5c3e6eb3c47f861e0556196c52999e859 | 94 | 248448 |
| E3 | Emitido | EnergyToken | 0xee3549bbdec081abe507c5031208af560d5ebd83dfd580f0d9ae0ef34dd46af2 | 95 | 248448 |
| E3 | Emitido | EnergyToken | 0x885e3425f94d7711a1921c75be26dca1b69ff34292644ddad136bb53634a8ff3 | 96 | 248448 |
| E3 | Emitido | EnergyToken | 0x042e63670a1b927c505463df2113143a69374cc40aa2e6648f38cbbff0fc2834 | 97 | 248436 |
| E3 | Emitido | EnergyToken | 0x205804c46b9afe815dea169ad23158efb1fd6236156d620551fe72bbe03282a4 | 98 | 248448 |
| E3 | Emitido | EnergyToken | 0xf42e7f0844af68e281a034b55b222bc33618b639d2c9333b3fa6eded9deb33f3 | 99 | 248448 |
| E3 | Emitido | EnergyToken | 0xe22436a2b3c0b0ca4e3b15ea59fb6c50ad0a046ce7f903539fb7ff46daed371f | 100 | 248448 |
| E3 | Emitido | EnergyToken | 0x9c514b7d5565d4470a67217150803ae22f4a9fae19fa34e7780f0e090fd09e9d | 101 | 248448 |
| E3 | Emitido | EnergyToken | 0xf33330da4168d0bd9f8fb654bd36b58a2ff9bd602801961a0cd94f09a455119f | 102 | 248448 |
| E3 | Emitido | EnergyToken | 0x430573d24703d7d898597e0e385dd59115adfbdecac1e5eef493aac4aa314abc | 103 | 248436 |
| E3 | Emitido | EnergyToken | 0xa627a11b9c462e7b38aad3266334e097fe656736e5101a0cdca90f08a03d6125 | 104 | 248436 |
| E3 | Emitido | EnergyToken | 0xd4b4319e90f1f04e7bd3f903083cfdfc881b88544b53f14bfe808781592cf100 | 105 | 248448 |
| E3 | Emitido | EnergyToken | 0xd2c8fdb3f3f84d7a85b924c5136b9615e3db7260219d0416ca0b65f1fa9a1ea1 | 106 | 248436 |
| E3 | Emitido | EnergyToken | 0x356358e89ade51efc99aa6711b74d2f24f81777f7a30fdd922cbdc0f9d5de7ff | 107 | 248448 |
| E3 | Emitido | EnergyToken | 0x5823a5b68d53effd8f3290deccbd1e42597a08567416ed435c0bfd209f207af6 | 108 | 248448 |
| E3 | Emitido | EnergyToken | 0xff09dbbdc20ad2ecfc496efe5627bab1947f5a91c76ec7ffae61b4bc6d54895e | 109 | 248448 |
| E3 | Emitido | EnergyToken | 0x0a337cf9e0e2f029e8b881d2190b64ccd23075ef34265e6e10ef46482f7268d8 | 110 | 248436 |
| E3 | Emitido | EnergyToken | 0x0f3a16c2237c6b62e28767180c753cac1c4d5b942596d989280ed8fd4ebf6c46 | 111 | 248448 |
| E3 | Emitido | EnergyToken | 0x3ea708776346ef9091d0ea197468cc306c9b99416303bd3f670c66796c5124e8 | 112 | 248448 |
| E3 | Emitido | EnergyToken | 0xd9287cccb1ab7606a46973b85162f91ceba46e6e8cd427a1db22e1e2ca5fc1f0 | 113 | 248448 |
| E3 | Emitido | EnergyToken | 0x80f6b9c067b476edb9b9da040dc36c531e32dad80d1069ef567181117307b445 | 114 | 248448 |
| E3 | Emitido | EnergyToken | 0xf29de3853828edcf2df604c418a636b413da488a5e492670d5bdfb665ff2d2d3 | 115 | 248448 |
| E3 | Emitido | EnergyToken | 0x5ac38bd02bd116fe64eea1c97b668aa0a0f1d8c3449a8968eb85cc6047a488a7 | 116 | 248448 |
| E3 | Emitido | EnergyToken | 0x043ffb46b56d536585a9c7cc25c1f7e223db895e8c6cc035fe8b96fe9c5dbb1e | 117 | 248460 |
| E3 | Emitido | EnergyToken | 0x0ea4f9f1e712ee8b1f46d4a20ee1a0015281337418cee6a499cc5dd699b036f8 | 118 | 248448 |
| E3 | Emitido | EnergyToken | 0x746d20e6f6f02af3b6477fd3c251e653377eaf733a2028d5eb97981a4eae8649 | 119 | 248448 |
| E3 | Emitido | EnergyToken | 0xccda415459eb1cf95b120a31634e760a380246d7f7b967c7394c8fc6351a847a | 120 | 248448 |
| E3 | Emitido | EnergyToken | 0x4fcd86403e31eee8e0e3dc6bf0395d049a09b22ac8190df84a4fe85877436e34 | 121 | 248436 |
| E3 | Emitido | EnergyToken | 0x952046730df6bb71fc5e77726f833a4c88c980d584089e3e6b56ef504d3956b8 | 122 | 248448 |
| E3 | Emitido | EnergyToken | 0x2814bb0c7279f74a9e550a5392ca7526ee0d86376d4579d3c83d3da041e96fd6 | 123 | 248448 |
| E3 | Emitido | EnergyToken | 0x797cd3289337ebcc712bf7eb8bc6902080c1cfcdf84d9520178c634d3337526e | 124 | 248448 |
| E3 | Emitido | EnergyToken | 0x78a1f2299f6161e855be75e51219eff806d143de7be2acef692c47ef13cb727c | 125 | 248448 |
| E3 | Emitido | EnergyToken | 0x882160f8e9b9ec872dc24a9609a1709aefc2d19f491dc5c0bf86aa05ca39f566 | 126 | 248448 |
| E3 | Emitido | EnergyToken | 0x452bf17aba5bd6ce847fc300f5c143addd4294ff31b7c2954d2472aa2cc0fee0 | 127 | 248448 |
| E3 | Emitido | EnergyToken | 0x27823738ffe51298f7020aae342e4b692ece657c10319a7897a4405a8e47a650 | 128 | 248448 |
| E3 | Emitido | EnergyToken | 0xaa875254b693519603678f1411f2f8815f41ad8af3f1ddfccc754cf218dbadf3 | 129 | 248448 |
| E3 | Emitido | EnergyToken | 0xad6d82341ab2ce50f59b4b5fa0882302b1e1341bd12416dd019f09aaebf482de | 130 | 248436 |
| E3 | Emitido | EnergyToken | 0x8b88935d2a6e8b84932f2e139b6740411adec15b7c018a6f1430952e03605441 | 131 | 248448 |
| E3 | Emitido | EnergyToken | 0x25ea4574236fe7ebd46e73480b9435623938d9af40cd6490624c292ef958b1eb | 132 | 248448 |
| E3 | Emitido | EnergyToken | 0x37110119fc7655e6f3f356466e5236f5f6b0cc22a7881cb448bf2ea260e0a3d7 | 133 | 248448 |
| E3 | Emitido | EnergyToken | 0x65f1f708ed3c04d07105a2dc9f072a0f959c91d120fa80fb66662c1ba2b368ff | 134 | 248448 |
| E3 | Emitido | EnergyToken | 0x28c170702c8acbe59239504998879dd5fc7cc0724e7a22b04c6542fe6fa59b03 | 135 | 248448 |
| E3 | Emitido | EnergyToken | 0xd8b1baec71e783c17c2416d8ff3b5dca59457e28ad43daa0a17503c18f826649 | 136 | 248448 |
| E3 | Emitido | EnergyToken | 0x058b63424da2898911fb1aa986ad22445235156b5880d572c2ea82cda3a4ee9f | 137 | 248448 |
| E3 | Emitido | EnergyToken | 0x4cab5896302eff1237b44fa650c63d7ae91d116072063447a8736df1f0cc7e3a | 138 | 248448 |
| E3 | Emitido | EnergyToken | 0xf713654331b76142bd059bcfe4fb9105b98cd0b39ee4c7688cae2dba4753da45 | 139 | 248448 |
| E3 | Emitido | EnergyToken | 0x356e9095ef92453f328f62a882d0bfee90b0de3e898715a8fdea64f1e6562a92 | 140 | 248436 |
| E3 | Emitido | EnergyToken | 0xd8c340f0bb0410a8c443f8ca783d3cc180efa043a1c630d88b46c0b45335dda6 | 141 | 248436 |
| E3 | Emitido | EnergyToken | 0x0cafbe8959c6f85fa7cee174e671a1019beef53d58beb2c7321eb632d237a4f5 | 142 | 248448 |
| E3 | Emitido | EnergyToken | 0x9ec5967a194994936613155d2eaba42f0677402bc2958325c7c02e673350d30b | 143 | 248448 |
| E3 | Emitido | EnergyToken | 0xffb96ff6a5d309d3128f2a3e9354cb5801b8c540daeb76d6a169b96d1884b95f | 144 | 248448 |
| E3 | Emitido | EnergyToken | 0x31be38b6fa05c1c59d0edce30175be60be73a52705f5f8e2118b831ffe7e9f13 | 145 | 248448 |
| E3 | Emitido | EnergyToken | 0x29d28241920b41eba426657fa3a1625074ec513ee0a53294ee0acf53c814b975 | 146 | 248448 |
| E3 | Emitido | EnergyToken | 0xbcff47fa2a3ed597924680d89240c225c769bd6624fdf821aa3dc43cf45ee16a | 147 | 248424 |
| E3 | Emitido | EnergyToken | 0xeed0cd1c8e5a1fdb6667f0d929591927542d3e29a6a4890fdfd35c1378bfa46c | 148 | 248448 |
| E3 | Emitido | EnergyToken | 0x348b2725cf7b59ddc6115ecb402c09c031499376d8dadc87fdb8aa2b60195a9b | 149 | 248448 |
| E3 | Emitido | EnergyToken | 0xcc5e6d6ea9532765894512eb0e1b65956e604469b90425a5ed69ce36049f4e7b | 150 | 248448 |
| E3 | Emitido | EnergyToken | 0x0dc311f3c33313b79ce658c44bab706b661c4f2afc145d6bff4b5b6149fdee8b | 151 | 248448 |
| E3 | Emitido | EnergyToken | 0x5b93f867a0f2519394adcce69843317113788aea99d2eb64ac3c742994c8bba4 | 152 | 248448 |
| E3 | Emitido | EnergyToken | 0x83b79832ce7605d770f08a7eede4c0d254a259470acb2ef29914f721afd9c027 | 153 | 248424 |
| E3 | Emitido | EnergyToken | 0x0a59db751fb42486e3bece5a1d33e2dfdebe06eb5fb3777e051cb7f000ee8324 | 154 | 248448 |
| E3 | Emitido | EnergyToken | 0xb2e7f1ffe731c5613bcaba82ea4dff01fec2f21fe0aa6a69caee58f99d6ab1a2 | 155 | 248436 |
| E3 | Emitido | EnergyToken | 0x8065b3d08d1b20081ff7b11a21ad1be49fd209a1372c42e199d2ee737d7941de | 156 | 248448 |
| E3 | Emitido | EnergyToken | 0x0397d8d9c25a9e5637d6dede7052fa5a43255e59b8f3f8ff1ac8916ceea7c435 | 157 | 248448 |
| E3 | Emitido | EnergyToken | 0x2f0b8a2a4afda36a54320e589a09b84482e9d9894f6d5f1d7b75be9961e050c0 | 158 | 248448 |
| E3 | Emitido | EnergyToken | 0x6b6b76e094d3a8a208a72bbbe742d49f9acb9d334e57b61c3ee6dc0339ae50f9 | 159 | 248448 |
| E3 | Emitido | EnergyToken | 0x8e391761eb38b00218450da8b51778b6965a3ad5312812bc6973005e91162e02 | 160 | 248448 |
| E3 | Emitido | EnergyToken | 0x8019a50942a6e638db7aefac10260dd820f3d6b730146cd9c629b1b3b93beef1 | 161 | 248448 |
| E3 | Emitido | EnergyToken | 0xbd97a28656335a238325c84c44138fd14a5041e2fe299df994d563f899e9c50f | 162 | 248436 |
| E3 | Emitido | EnergyToken | 0xf68376836e0469f4638023458f8423087dbc3a78951ee0ea9f792be6b3aa20ce | 163 | 248448 |
| E3 | Emitido | EnergyToken | 0x7dbb0963dbb58ba7d1e0a098d715280957ddafcc16d72f562fe7ba70db0eb27b | 164 | 248448 |
| E3 | Emitido | EnergyToken | 0x087db16770a136ceb9284a342ca1ff7955f71e5d57eefb956f3409bc13789ded | 165 | 248436 |
| E3 | Emitido | EnergyToken | 0x6c9464c3c80fadea1cdb4624315cd4df0d43d48dfe672ae3a752e345ce7a3eb0 | 166 | 248424 |
| E3 | Emitido | EnergyToken | 0x3378423bf6f8bf7c7ebf585aefcf3be76b89903511ff02aa268d3d086739522a | 167 | 248448 |
| E3 | Emitido | EnergyToken | 0xd15c9aedb66644a1e72e64c0d12f5cc0c153da8c05c9b9b2616a059143b3c980 | 168 | 248448 |
| E3 | Emitido | EnergyToken | 0xa9d32054b61fe559dc2826e427b67348dab019f9a7afb59ee5cf021230f5a0bf | 169 | 248448 |
| E3 | Emitido | EnergyToken | 0xeedb529856746b96f334625d9e6819c59a7245b12a1141f7704b473ddf569b99 | 170 | 248448 |
| E3 | Emitido | EnergyToken | 0xd7c51301fa6941ee318e525c75c4e4268428c53e4564c2b5c7e511827c0616f2 | 171 | 248436 |
| E3 | Emitido | EnergyToken | 0x455de5e8bd280274b477d92cac24c0758e288c6fde3bcf5e9bd70f27faacda06 | 172 | 248436 |
| E3 | Emitido | EnergyToken | 0x69eccd5e430e5b0ff466d585ff0a23887b1a20e3da8c96414798cccf94b33815 | 173 | 248448 |
| E3 | Emitido | EnergyToken | 0x2e5df3befeac4a510c71a62f73db1be732dcffe3c6966443088d50645f3d447a | 174 | 248448 |
| E3 | Emitido | EnergyToken | 0xd4bcbf1f3dbcad2a683762d66bcdec528e74fca451354a8e24b4298016d5cac6 | 175 | 248448 |
| E3 | Emitido | EnergyToken | 0x4e6d1f4d34f5a0d5267f794ec6e92a3e8c2919e2150f72914182c9bf1076ec98 | 176 | 248448 |
| E3 | Emitido | EnergyToken | 0xa6a7e4bb631cdb596d6e85ad9c02c3862a0f81367150161e6055c3039b338890 | 177 | 248448 |
| E3 | Emitido | EnergyToken | 0x05b99b9df566e0f6aaa2385657b322fe2ded4cbac6cd288769048e7d60caab72 | 178 | 248448 |
| E3 | Emitido | EnergyToken | 0x54a724ba76a941064eb507c95575f2a2c40376151097b0c5cabfacaca5d5adb5 | 179 | 248448 |
| E3 | Emitido | EnergyToken | 0x79051be13bd4980f5266e4e8890ae60ce6d21f0eaa02ed4a4a836d05d93fcaec | 180 | 248448 |
| E3 | Emitido | EnergyToken | 0x709fefe628d59de09e03d6fd4840768b515798893265c1c8487cf4875f3ee95f | 181 | 248436 |
| E3 | Emitido | EnergyToken | 0xdac53b1a15ac8e7301cf5122f95f078e67142b0d9dbd738545d8ed53a6b4e1c9 | 182 | 248448 |
| E3 | Emitido | EnergyToken | 0x99058aa377f67f4c095da1ece8fb4280ac14bb466d08ae07fc64a6a20ee35578 | 183 | 248448 |
| E3 | Emitido | EnergyToken | 0x1be1620192832452aa6bcde94c09fae73dda6c750a6e133c296cc05579f7692d | 184 | 248448 |
| E3 | Emitido | EnergyToken | 0x433cf422c3ca574a08a8f9848e035dde999c2ff775aa75c65448a2ff928408e0 | 185 | 248448 |
| E3 | Emitido | EnergyToken | 0x3e11748a84365d846355aeb8af3ac6e3539e175188ff634c5b44b145550ac329 | 186 | 248448 |
| E3 | Emitido | EnergyToken | 0xa603337126911f8f6f33c363d1ec44add9e3a9f631a9b701fb75c33d06e1464f | 187 | 248448 |
| E3 | Emitido | EnergyToken | 0x0c9fa4c1854b56e4df57747524797dc91858e00de62fa050514df42d459ecf68 | 188 | 248448 |
| E3 | Emitido | EnergyToken | 0xb4c68c7c4697a3439e431ead7ad636c139833c3cef1ca3647473156f4f79f3f8 | 189 | 248460 |
| E3 | Emitido | EnergyToken | 0x9b02f260c4cd5447d1377cebffb97d38d9b3ed88bda4e28ba1bc5afeef556a72 | 190 | 248448 |
| E3 | Emitido | EnergyToken | 0xeb63eec68850fb29fb045c3ba2f82577f4cf95e196e08263461f052a7117affe | 191 | 248448 |
| E3 | Emitido | EnergyToken | 0xa6e84f1eb89692a3321d1c03b15aef93549d6db53cd36fc0429c7ea3904311b8 | 192 | 248448 |
| E3 | Emitido | EnergyToken | 0x69153cac0c2891f9bc524e48f7212ba97533e4a10e9c55551060fdac3b48fb78 | 193 | 248436 |
| E3 | Emitido | EnergyToken | 0x563268dc6dad851d064323d708c47916d3f752437230494f13162d02f1fef499 | 194 | 248436 |
| E3 | Emitido | EnergyToken | 0x456de5bbe75706a8b2316e220fad60bc2684f58dbf142eba2433b18ddf4589a4 | 195 | 248448 |
| E3 | Emitido | EnergyToken | 0x126274b12904f8429850350a86cffcb2a18a0eec880dde0955f2f72a701b0690 | 196 | 248448 |
| E3 | Emitido | EnergyToken | 0x4580d703cbb4f84b161fd756f140e38f64661c35f3698c459ad0c265ffc3958f | 197 | 248448 |
| E3 | Emitido | EnergyToken | 0xc2328a83deb23a90ff11def13bb3045ceb326278f5268916780b0febaeb0d752 | 198 | 248448 |
| E3 | Emitido | EnergyToken | 0x9fc5db55ef91863e4ad5d8074c41860cbfe363d3de7852efc64fada711e8074c | 199 | 248448 |
| E3 | Emitido | EnergyToken | 0x4da17f37f2fa770391695d43ce941f2b415daf123b4288ce01b6a27511991c26 | 200 | 248448 |
| E3 | Emitido | EnergyToken | 0xc1dcbb0c44ec8bf256b36f989c73519030447f9f72144333ccdc10980ce8e138 | 201 | 248436 |
| E3 | Emitido | EnergyToken | 0xba62c0bf289102d18a33c7dee73ef667457053e467ab001dd172451e8d9e194f | 202 | 248448 |
