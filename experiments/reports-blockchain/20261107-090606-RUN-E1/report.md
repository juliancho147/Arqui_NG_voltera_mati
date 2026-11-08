# Reporte de corrida `RUN-E1`

- Veredicto de la corrida: **PASS**
- Inicio: 2026-11-07T09:05:51-0500  Fin: 2026-11-07T09:05:56-0500

## Cabecera

- `runId`: RUN-E1
- `repeticiones`: {'E1': 1}
- `cantidades`: {'E1': {'invalidas': 200, 'validas': 200, 'porCategoria': {'valor_alterado': 67, 'medidor_desconocido': 67, 'lectura_duplicada': 66}}}
- `contratos`:
  - `EnergyToken`: 0x5FbDB2315678afecb367f032d93F642f64180aa3
  - `MarketEscrow`: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
- `herramientas`:
  - `foundry`: forge 1.9.0
- `params`:
  - `seleccion`: e1
  - `chainId`: 11155111
  - `rpcUrl`: http://localhost:8545

## Frontera on-chain / off-chain

- **On-chain:** Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta (MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). Firmado por la plataforma (modelo custodial).
- **Off-chain:** Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion del runner. Las APIs de medidor y clima son stub.

## Experimentos

| Experimento | Titulo | Veredicto |
|---|---|---|
| E1 | E1 — Integridad del Oracle | **PASS** |

### E1 — E1 — Integridad del Oracle

- Veredicto: **PASS**

| Id | Criterio | Estado | Esperado | Observado |
|---|---|---|---|---|
| R2.5 | Tasa de rechazo de lecturas invalidas | **PASS** | 100% rechazadas (con categoria correcta) | 100.00% (200/200); categoria_correcta=True |
| R2.6 | Tokens emitidos por lecturas invalidas | **PASS** | 0 eventos Emitido por lecturas invalidas | 0 eventos Emitido por invalidas |
| R2.8 | Latencia p95 de lecturas validas | **PASS** | p95 <= 10.0 s | p95=0.1197 s sobre 200 validas aceptadas |

## Evidencia on-chain

| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |
|---|---|---|---|---|---|
| E1 | Emitido | EnergyToken | 0x1e2f8fa99ef5ab3d0265bd7e3b0727f40c6ede4e6ba754b731391fe5d726011e | 210 | 248448 |
| E1 | Emitido | EnergyToken | 0xed673bd440ae3f78db91a6ca27ea5dc999b6bca4dc364059bbf1a8085d679467 | 211 | 248448 |
| E1 | Emitido | EnergyToken | 0xdd4709a7c7e290b6b00b24df9254137ed24f3b4f3a839578ca07976a792933d2 | 212 | 248448 |
| E1 | Emitido | EnergyToken | 0x969b3d9262c2ff83f607d8fe9bc46e391c8e3eb35d1a9243c7baea9d095408e0 | 213 | 248448 |
| E1 | Emitido | EnergyToken | 0xf8bcec45f36859cd1889d6972561e5fea6785fad6401bbe76414801ab7a3fa2e | 214 | 248448 |
| E1 | Emitido | EnergyToken | 0xbc3a60a57325773695ba0c9d9657325e2bccc01a68d126740be1c961e1ea0d75 | 215 | 248448 |
| E1 | Emitido | EnergyToken | 0x77a7bd841479995169598785e778eb37bd4c62978750808bec28c0045797e0e3 | 216 | 248436 |
| E1 | Emitido | EnergyToken | 0xae65eb026d627de6ec02d6a6541d78e9742b5472ac9fa22ce57cae6dea307375 | 217 | 248448 |
| E1 | Emitido | EnergyToken | 0x2672b2cb00030ed31f3c22865caba9aa4bc9921b6a422984cf817353745ff0fc | 218 | 248448 |
| E1 | Emitido | EnergyToken | 0x95369ba769a9c871c008593557e97d959f2c2295b5cb5959a304869ec35d56ee | 219 | 248448 |
| E1 | Emitido | EnergyToken | 0x305b818bfa61d1272100c576aaaffc75679b72fe29259aad2972a16d0ddb0f4b | 220 | 248448 |
| E1 | Emitido | EnergyToken | 0x7ebd0314761829e48275d2cda93b3909f77ef1f3d294755fd258315e398847b3 | 221 | 248448 |
| E1 | Emitido | EnergyToken | 0x8e7cccb6d2370366139a7f09ef5c92e7aed16438daba01d4b0a53434fb67a331 | 222 | 248436 |
| E1 | Emitido | EnergyToken | 0x40842b9fdfe380318adeea1797cc76cd4f11b7a5e489f47e759f30bc11dfe66d | 223 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b4b14a59eb75b683bf30f3a00e04b6a8a1dac1e7890f6dd6acc39d83ee5ad49 | 224 | 248448 |
| E1 | Emitido | EnergyToken | 0xba259b193949d7ad9341c9e8df3a8fa787426e736610ac2bb530fd9b42b352fe | 225 | 248448 |
| E1 | Emitido | EnergyToken | 0x62e25ad422378d9bb7e1071fc5b0317f7b34a8c9115d904d3954c18331fc05fc | 226 | 248436 |
| E1 | Emitido | EnergyToken | 0x9fa642b2fc7cd705205ff83117623333bccba4cd2b448f5cfae63caaf69a21d0 | 227 | 248448 |
| E1 | Emitido | EnergyToken | 0x270b29be7fbcac55b861cc29d6e848687db19ec218a7179e6e32f25a84f790f4 | 228 | 248448 |
| E1 | Emitido | EnergyToken | 0x217e4f1950c4d003f7f74fe1fc547a33d1b733323cf32a58c77d517f7e9ac7be | 229 | 248448 |
| E1 | Emitido | EnergyToken | 0xb0890b2515cdea8e4ec8833693a51ba4323079ce99f3dd43db0e08c3b6dfc6a0 | 230 | 248436 |
| E1 | Emitido | EnergyToken | 0xd40d605cacca87d91847e77be3060732a598cb637ed592f6fab417c36aed3fd5 | 231 | 248436 |
| E1 | Emitido | EnergyToken | 0x546af7fb78a282c6b0cca7d80e6e20e8a710116e7c73fe1e3c05774f06ba4624 | 232 | 248448 |
| E1 | Emitido | EnergyToken | 0x8b49bf7ac9639cfc392de6a0a8bb039fae883c1a849672e7988976474fb4e54b | 233 | 248448 |
| E1 | Emitido | EnergyToken | 0xc0778312d69f4a386c5f55030bceff81ec32ce794495dc2d14dbeb245fdd18c8 | 234 | 248448 |
| E1 | Emitido | EnergyToken | 0x3ac633f8f43e0140a6c483b67eaa59bcb82e540d9e6fa8a240a7c212d38c51b9 | 235 | 248448 |
| E1 | Emitido | EnergyToken | 0xfcb57a10ac798b30233f46566fd2fb8e44cf69ba251e19413e96313d2fcb2a88 | 236 | 248448 |
| E1 | Emitido | EnergyToken | 0x9e8d32912f39a908d2146303524f384de6cb8252add0e717788a17d09078ae48 | 237 | 248448 |
| E1 | Emitido | EnergyToken | 0x5e3c160d9244060bc91ecf7bd556410c6cfee30e0814dd20060905eea02d0d5a | 238 | 248448 |
| E1 | Emitido | EnergyToken | 0x4569682d1ddab1448e0a331797227e4d81830574d283755e4121a4c921d19aad | 239 | 248448 |
| E1 | Emitido | EnergyToken | 0x6786d38d06ff379b5cabc6294ebf215499c502a357cc226a594f711f8e9f4b6c | 240 | 248448 |
| E1 | Emitido | EnergyToken | 0x964d2012bf75c45c84d53cd74a506cfc7caf052478ff83c852a5a1d10dbe5926 | 241 | 248448 |
| E1 | Emitido | EnergyToken | 0xd60858581173846353688b57b10e2304d054e3e2efdc41f4ed3d377d720b1364 | 242 | 248448 |
| E1 | Emitido | EnergyToken | 0xe05619617692c776f4b6e2ecd0e9cbc56198445a5292e4cc39f51652c998b2e1 | 243 | 248448 |
| E1 | Emitido | EnergyToken | 0x76a2ce336f079e731fbe952e60eec5e10f5e5f01a1d331288409c303033ab428 | 244 | 248448 |
| E1 | Emitido | EnergyToken | 0x0130bec35401a85d3fdaff50c3ac0d221764e54936c059f85f18083bb8d308a2 | 245 | 248436 |
| E1 | Emitido | EnergyToken | 0xb36f185e5a08474ee8587d88ac730bf00c7d4d5e65f87421d450cc8fb39d46e8 | 246 | 248448 |
| E1 | Emitido | EnergyToken | 0x0adf80951bdf734c55720565f2abd6a8bb73f135c45105d6bc3fbfcff6d55026 | 247 | 248448 |
| E1 | Emitido | EnergyToken | 0x6ed8b3d15a7d2c9f418cab01e4a2adb1ef3dd36dd959704d14a6686d033fbebf | 248 | 248448 |
| E1 | Emitido | EnergyToken | 0xe5ce55a833771d1977b5228e7dbdb2d919a583e4688a0857b06f3933434db7fd | 249 | 248448 |
| E1 | Emitido | EnergyToken | 0x513e3b48b91c66f8c8e64ffeed3172dc7e6438a079e56053ae51f212361207ec | 250 | 248436 |
| E1 | Emitido | EnergyToken | 0x45415ef823eea4a3f1dd8703da1fa3c57f914cebff336fca83300fad8a707a30 | 251 | 248448 |
| E1 | Emitido | EnergyToken | 0xfcffc0de1b89a28530a91480fe37152258fc7f6e5a55efdea409cb1d30e32ef0 | 252 | 248448 |
| E1 | Emitido | EnergyToken | 0x51ce55381bb75782aa365d1a9f7845c3dea77429aeca90e812641990e92f3d61 | 253 | 248448 |
| E1 | Emitido | EnergyToken | 0x173d429043373697f7d649c79d799b95518ecc1ea92d3c7e8aa556a89115fc90 | 254 | 248448 |
| E1 | Emitido | EnergyToken | 0x082e6e138ea164b7735a28f9e5b0878d0b9e256c2174455101424de768e041cc | 255 | 248448 |
| E1 | Emitido | EnergyToken | 0x71e1276f8c31ab7e8697d9f2ada1ca3bd2eeb989a13b4ab75ec9dc6c30892ffe | 256 | 248424 |
| E1 | Emitido | EnergyToken | 0x087a20a54510f1f417ec3c47b716fa1bb15683784f6b5db8ddce6af8a087050b | 257 | 248436 |
| E1 | Emitido | EnergyToken | 0xf9ac0dcb23d46db07ceaa23679020e77b37fb924b2e955afb2dd385dd38aea50 | 258 | 248448 |
| E1 | Emitido | EnergyToken | 0x704bdc86943f375cb1e970c7f5fc3ece31403f20672562b3a269c7ca437b0649 | 259 | 248448 |
| E1 | Emitido | EnergyToken | 0x33fbdd96252fc95a1b5d40bc7c25d4ac67f779cec820e1c54334a768950859ec | 260 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b3a7ed57127785ff88f47f51ae7ab119aac6997d43d25b5f98355305ae1fe22 | 261 | 248448 |
| E1 | Emitido | EnergyToken | 0xc2e811aa9f89fd712e1f7ba9a8c8de3df394ca58975d1434df21b54a3b2933be | 262 | 248436 |
| E1 | Emitido | EnergyToken | 0x7db87ff74511efb719bb2c3431a0bff6c09269492f34207c1a51f833bc4e1312 | 263 | 248448 |
| E1 | Emitido | EnergyToken | 0x92e5458859387b92d042f5649cca8c287b4250c1ceb2bb69bb2a48544383f806 | 264 | 248448 |
| E1 | Emitido | EnergyToken | 0x173d7b3406d8f29006e5be91b97f820af925a2ca721789bb497ecf5bc1072959 | 265 | 248448 |
| E1 | Emitido | EnergyToken | 0xb07eaa7ecee07944b8e6c5aeea91fd36478cf6dceeb62ffc4812df77d32be347 | 266 | 248436 |
| E1 | Emitido | EnergyToken | 0x729525c92e4ce000d42a49b3341d5b00fac0959d72568ffc77a1e45204198fbf | 267 | 248448 |
| E1 | Emitido | EnergyToken | 0x5805866db8c186a12cf5e2f3de7d2bd96f281b211e2fbba664dc06e623f7e6da | 268 | 248448 |
| E1 | Emitido | EnergyToken | 0x0780621d0910871c7f093693a261140d08f82be53148f38aae6b945581aabf9a | 269 | 248448 |
| E1 | Emitido | EnergyToken | 0x3541bbbba8fae431bf5b69e6c6f35386c771a37a26f6cead4f8e21cdf6f24bc2 | 270 | 248436 |
| E1 | Emitido | EnergyToken | 0xcd901d017963fd02c58181f32552ae33561491819edc43e0d0c987f010714f41 | 271 | 248448 |
| E1 | Emitido | EnergyToken | 0x6d93530ea34bc486afdc3d4165c82d23b66a90a6e42f89d6c32a86e7827e9fbe | 272 | 248448 |
| E1 | Emitido | EnergyToken | 0x23467ec27685372220a7ea15bae9192f70be00082b89e8f3d7bcffa30dc480ed | 273 | 248448 |
| E1 | Emitido | EnergyToken | 0xe2f4d261bf63b6a495382b7c9a99c4a44a966ec4c32228e2f6fd15f8216e7556 | 274 | 248436 |
| E1 | Emitido | EnergyToken | 0x90bef6961bd4402884579e63e41d6452d2fb508aeb2f8eb908e0be51e5377c32 | 275 | 248448 |
| E1 | Emitido | EnergyToken | 0x4d62ac9119777af657576051815d20d4ce213360c75e288223aff9f92e0f5bcc | 276 | 248448 |
| E1 | Emitido | EnergyToken | 0xaaf8e267a48f78d57484e27fd60faa48153d1dfac94ae0863a2e03b0366ef190 | 277 | 248448 |
| E1 | Emitido | EnergyToken | 0x7acb763cc7f3e9f505c35f44f38ebf0e08f36ac723432e426a9481551e9636a9 | 278 | 248448 |
| E1 | Emitido | EnergyToken | 0x5fb404ab3ddeba2f7319e6c6b0a7c756052d1998160d35bde397ac3dbddae4e9 | 279 | 248436 |
| E1 | Emitido | EnergyToken | 0x7cf5a7dab1b2129296f8a1dad80b8938b8aec6a81e6146b5468ef437d4f8fd7f | 280 | 248448 |
| E1 | Emitido | EnergyToken | 0xe124fcdf182962498fb55a90071ab81257751c6507cac8df1eaff58df5f25df5 | 281 | 248448 |
| E1 | Emitido | EnergyToken | 0x4af508988db94970273eea29d8ae2b216b53540d8bb145544c87de6fb1f370cb | 282 | 248448 |
| E1 | Emitido | EnergyToken | 0xa6e098c5a9602ad33d39f63923b6c9a7dc43f93daeaafae0b0a3578be202390d | 283 | 248448 |
| E1 | Emitido | EnergyToken | 0xfde968f5e4637043650643584f104d1e57237c34fc0608d68f3ff2d3d7864919 | 284 | 248448 |
| E1 | Emitido | EnergyToken | 0xd3a0d9a6c5b0f937d529d711350dec486eded5f9e8fa3671ba3b4944b40abebb | 285 | 248448 |
| E1 | Emitido | EnergyToken | 0xe928f5046071dd644b9e34d0c9b45c2d8e4a91ca86c0c2fb06f2be7ffb5b82c9 | 286 | 248448 |
| E1 | Emitido | EnergyToken | 0xdab3a41076b5c936063281341a205da4256df2b6b1a1c11f509b46d432132176 | 287 | 248448 |
| E1 | Emitido | EnergyToken | 0xe17a7f1f000a586fe5e02c54e98b34afa8aa9f567befc55813456426d396c172 | 288 | 248448 |
| E1 | Emitido | EnergyToken | 0x79877f47c53b83ab8df79c66bb501ccc0eb6e3c892623c248b85446365644ddf | 289 | 248448 |
| E1 | Emitido | EnergyToken | 0x8e475092ab667b7816591156e36162b98d549e4aa8b3e923cba38b83877eae40 | 290 | 248448 |
| E1 | Emitido | EnergyToken | 0xc22247a1c13121b2c2790bf61cf46252134b49a7c8f795b37c1adb2a0e868ad2 | 291 | 248436 |
| E1 | Emitido | EnergyToken | 0x5cebdfe40700f573bde2efbc70e9f6159e2b26874e0c4c9c0ac4097d67604632 | 292 | 248448 |
| E1 | Emitido | EnergyToken | 0xe5d37b95773c5fdd27031f0842c13f6b70fb49aff26edbd98cbb2b38cf38f9e2 | 293 | 248448 |
| E1 | Emitido | EnergyToken | 0x41ee6ca316a492906cb8d7aba148af035edd21769173a36c4a9b3a6515c34577 | 294 | 248448 |
| E1 | Emitido | EnergyToken | 0xd94dda62667f3ae44e7dd05e2d30d53910276fbc86a8f0fcef57d183dbfd23ad | 295 | 248448 |
| E1 | Emitido | EnergyToken | 0x576fad229daeeaab2e6b79f745043400a393c3429e73453d9e428f854c300c50 | 296 | 248448 |
| E1 | Emitido | EnergyToken | 0x4cab41e15bb95ae2a7b4116bd533465abed5cf9c067502a0993ac4dfce4b5589 | 297 | 248448 |
| E1 | Emitido | EnergyToken | 0x2e3eee0cbd9da017b646c1b72fc32a966b43225c5208f4cd7720d7d8117aca25 | 298 | 248448 |
| E1 | Emitido | EnergyToken | 0x84206c6b80abb4e67337b318f34bb4d6417293bda25bc765d63217d13ad11814 | 299 | 248448 |
| E1 | Emitido | EnergyToken | 0xbbf9238579f310489c1cdc700a880a5365b9bec771fba41b46367f0eba4d91fc | 300 | 248448 |
| E1 | Emitido | EnergyToken | 0x72a025c9818c4313b0fa20d32ee2883c0fc3f03d6f4f107aa9d1f10c7a78ca30 | 301 | 248448 |
| E1 | Emitido | EnergyToken | 0x6925ade94682c48c29b31709b8b892b427004cd2fd5d70e2e4e01bf88942cee3 | 302 | 248448 |
| E1 | Emitido | EnergyToken | 0x38505010eefe0b75dadf29a96cda01ad9ecdadcb64a6fd72803d258147dd94b3 | 303 | 248448 |
| E1 | Emitido | EnergyToken | 0x4c5a9721768b3f57d06f8b30e82947aa9bcd29fd9b9a97114d8ede9b7572fee0 | 304 | 248448 |
| E1 | Emitido | EnergyToken | 0xcd36f234cb80d0b50a0142deae3fded9d18aee8e06d37f881b47506fe2ffab90 | 305 | 248448 |
| E1 | Emitido | EnergyToken | 0xdb2ed8d04bef28b64b415117f6db35df0818d25bf389c0d34cf627a432af6d12 | 306 | 248448 |
| E1 | Emitido | EnergyToken | 0xa9c8d33f6cca529739d024565799893ad3fe7a8368734e390a789210477f2410 | 307 | 248448 |
| E1 | Emitido | EnergyToken | 0x67c5b18c8294cdfa7257ec0d4aaa3a83c0765d5f936568abaa3893d94dbe65db | 308 | 248448 |
| E1 | Emitido | EnergyToken | 0x62c2599a8e8a83b4ff15cfb954659c515950b5f8cdd2c29352384442a38a9ed0 | 309 | 248448 |
| E1 | Emitido | EnergyToken | 0xcfb01377fd56c17258eae62e068b9a4bed3129104d0956d7ecc4a5a63d0ef5d3 | 310 | 248436 |
| E1 | Emitido | EnergyToken | 0xf3c625200f6186f1955382f1904fd5e3713a5f570038a10cd0e1fecfd781844d | 311 | 248436 |
| E1 | Emitido | EnergyToken | 0xf25d28aa503db139bc728f0c2c9e02a4ce968debab1d7037b97618924175215c | 312 | 248448 |
| E1 | Emitido | EnergyToken | 0xa08a35eb27a06685590ed51cc7374ca734154323d7452e4cd8abdb58e82cd2e2 | 313 | 248436 |
| E1 | Emitido | EnergyToken | 0xa374f3367edc89687fe40e753ddb1c7cf377150da494095bdeb4363d7e64fbf2 | 314 | 248448 |
| E1 | Emitido | EnergyToken | 0x9cad5d80bc4d04d00f78b079a0ded2e5db08a6a260fcbf2a376fbd6f10bf6880 | 315 | 248448 |
| E1 | Emitido | EnergyToken | 0x60db729786b7b9d54337a51061b03bc5f62a4a525d841a2cc6a6f6518659fd84 | 316 | 248448 |
| E1 | Emitido | EnergyToken | 0x867b89dc6414d19fcba30b66a54b601a299777c6d58f3238557c9c158df93c6e | 317 | 248436 |
| E1 | Emitido | EnergyToken | 0xefc6d114aab4f0105c251de90c829e5c29a58a8d5a3dd5a03986c6f55018b7a2 | 318 | 248448 |
| E1 | Emitido | EnergyToken | 0x4f2ff6dc34576e97197a84fb98679ae31981b61f6dc1f29ac0d1157b239c917b | 319 | 248448 |
| E1 | Emitido | EnergyToken | 0x687bbce4ecc02e8eb7d290d44b341eda4fb5368b1b960369c402f97cc5cb4501 | 320 | 248448 |
| E1 | Emitido | EnergyToken | 0x3adbec0ab0db3f745f2b48cd9e70e76f028346df339029a5ab8b171aaaf4ed65 | 321 | 248448 |
| E1 | Emitido | EnergyToken | 0x23d68710671c892bab9aa16c543fa3250591c85d0c3a8940ded04f37d07b16c6 | 322 | 248448 |
| E1 | Emitido | EnergyToken | 0x4b3649b17b110773777d4d54bb57e8e88e8fcde0f0ecd1788608301887a973a6 | 323 | 248448 |
| E1 | Emitido | EnergyToken | 0xbb88094f5662ae663260eaf2b0aa7d4d2f1c399c2e9cce28d21e917258069d57 | 324 | 248448 |
| E1 | Emitido | EnergyToken | 0x2831b0be6b727a13e2de6a135c28e1fb2569b7d57beec43d626a390647b74155 | 325 | 248448 |
| E1 | Emitido | EnergyToken | 0xacce3c1e864c8d45ed3dd4737d9d6fb85731838946d219a8630f8f457a076ab3 | 326 | 248448 |
| E1 | Emitido | EnergyToken | 0x745e4b5a67280997e761113f572bf9d3da0055b5872ca55fb437ac242f37c558 | 327 | 248448 |
| E1 | Emitido | EnergyToken | 0x3444a142661a5ebe6ead9016a0da24103821e99668664a7eb6da18f70047da2e | 328 | 248448 |
| E1 | Emitido | EnergyToken | 0xd6e5cf320eca1e2727801d1a0bacb67ed0efadd6c7a90872f4f98670fdc4cf61 | 329 | 248448 |
| E1 | Emitido | EnergyToken | 0xcc68e1b4c2bd90c5b76b0aba40c12a6ca929f2323cb99f0c954a4ad626ed27db | 330 | 248448 |
| E1 | Emitido | EnergyToken | 0xfe4ac7ac4a8d13549e4aee25da3693b1665ba3fe55d2742868f2bbb1a7f0623b | 331 | 248448 |
| E1 | Emitido | EnergyToken | 0xef538840bcfdff01a228d3dd9594d62fe6ed0f1227ed694ccbddb95e9ae5a784 | 332 | 248448 |
| E1 | Emitido | EnergyToken | 0x18300def285429d1fd1e475854c89db3a51091a21ba4213947a064464d441915 | 333 | 248448 |
| E1 | Emitido | EnergyToken | 0xf8e43711140fc304f293acfa4019df1b7f785dcb02bfa91765c6940133c677f0 | 334 | 248448 |
| E1 | Emitido | EnergyToken | 0x2afb44b057f94a62dc1794957efa76334a6dfbf9da22392339d083ad29c846ed | 335 | 248448 |
| E1 | Emitido | EnergyToken | 0xd543a0791745e4047b2d5e65636155576b1c3efe9cd51fbf4802673752fc8671 | 336 | 248448 |
| E1 | Emitido | EnergyToken | 0xed07891b09b059cfc0844b67b7bca51c7c419ddc860b46f5e129b00573bfb41b | 337 | 248436 |
| E1 | Emitido | EnergyToken | 0xd8dd2bfab394da787894eef1b528d93ad03f031322210022cdfb0cae0baef7f7 | 338 | 248436 |
| E1 | Emitido | EnergyToken | 0x02bb101bb8a5ef44d1a94a9b4c1066e576659f195eded0bd5f2c9291bdc835a7 | 339 | 248448 |
| E1 | Emitido | EnergyToken | 0x2b85a21d9b2ac9e0d030cbe60eb55ec71d2a9722d7852816264c21432053a4e5 | 340 | 248448 |
| E1 | Emitido | EnergyToken | 0xb9939cb31455f24918395d73a594e67f23b6e39221a8f99fe2f00bf7fd70dba4 | 341 | 248448 |
| E1 | Emitido | EnergyToken | 0x3c2d0d4e11d969fd27e5febac6ced211df415b25abcc4749a828cc10f5224cdc | 342 | 248448 |
| E1 | Emitido | EnergyToken | 0xea6a87270b1c85784d672c6bf98adceb21a50f3a846bd0ec80686de501378461 | 343 | 248448 |
| E1 | Emitido | EnergyToken | 0x203ecf83f2613bb3da31a7968c7122b1d65e844e6618e0077e2b865fb7b24bfa | 344 | 248448 |
| E1 | Emitido | EnergyToken | 0xb792ef42552cde1aaf8c91cf09119c2f725ed2534d070091b85c15e21210010c | 345 | 248436 |
| E1 | Emitido | EnergyToken | 0x5093275ff7277c74544609b5471970a91734b938b86d11c8c23b4a59ea1e86d1 | 346 | 248448 |
| E1 | Emitido | EnergyToken | 0xe2e8b04f09830e71ca6a3cc7455947860ccadc51899f9eb5dd3d16dd888fc111 | 347 | 248436 |
| E1 | Emitido | EnergyToken | 0x799de89ea63cfeb80582b48e84c979b338b10c6af3155079c66e5b361e8d16e5 | 348 | 248448 |
| E1 | Emitido | EnergyToken | 0x2627c26bbd3e6bcbd1aed1bfe9831a8993dd4e20f3d920a51e8e2a3f929bb8a3 | 349 | 248448 |
| E1 | Emitido | EnergyToken | 0x21297b14f3b5e910075087460c9eba59d8b1511bdef857021ff8a8d2a74e2700 | 350 | 248448 |
| E1 | Emitido | EnergyToken | 0x928b441e8a45d67a197716b91196925d955dc2b49737812131882694a20b6dfc | 351 | 248448 |
| E1 | Emitido | EnergyToken | 0x1708a91797a5da99458bcce0a2c26cc0650d89effb3d57ca2bfd1d23dda561be | 352 | 248448 |
| E1 | Emitido | EnergyToken | 0xe40d8b536d59dc686622fb5405aad0ec0694cb148cd93f91e28b641f5e22fbd2 | 353 | 248448 |
| E1 | Emitido | EnergyToken | 0x9b824cdbeb91dd6780b54cace2adc54d3d223a1b8ffe52fcbb154ec78ec00231 | 354 | 248436 |
| E1 | Emitido | EnergyToken | 0xd8fee543c8aa3cbf1c877c55d213975a36c528f26e740a0d86e0f9e28744f707 | 355 | 248448 |
| E1 | Emitido | EnergyToken | 0x3d5045ca72f6a51b18eb36913917fa8f4b81608c7a16a4f0e24f463c8bcf7b10 | 356 | 248448 |
| E1 | Emitido | EnergyToken | 0x23d882fd9cc5ba870cbbabe17180a6f5c516c8b59600b187d0a3814b4e5666da | 357 | 248448 |
| E1 | Emitido | EnergyToken | 0x63c51de291f11ee9f6e6af126143b21db0929ebae08060c414ad48c00783b84d | 358 | 248448 |
| E1 | Emitido | EnergyToken | 0xb57e28f5ce117c5f0940ed9993d6af621c90467aa4fce0a8194cb5f00e104a40 | 359 | 248448 |
| E1 | Emitido | EnergyToken | 0x0a7ed75c69d5f869653f1ea3756acc12074a6ebebdea91a51060d6fbd9d7de58 | 360 | 248448 |
| E1 | Emitido | EnergyToken | 0xca8c5b158f60ad44b9a33e4f201f0dbe7240144072f6877fdff8304d11a27911 | 361 | 248448 |
| E1 | Emitido | EnergyToken | 0x4b741d023f8b7dcb132ec3ac24fc6f070648679514c68f20f5d767c2ff1a3ef0 | 362 | 248436 |
| E1 | Emitido | EnergyToken | 0x3073fa4adb40e1f1e61cd01f511e78ae15e830c944217a963f7855ac13ed1db6 | 363 | 248448 |
| E1 | Emitido | EnergyToken | 0x2d8b3bd76214a3273fb8fc201f117923c322ec7f557e02aeef17146d829e6d91 | 364 | 248448 |
| E1 | Emitido | EnergyToken | 0x6fa2ca2336afd9b2490e50574c84945e1b7257036d9192f96b471da2d5f79ebf | 365 | 248448 |
| E1 | Emitido | EnergyToken | 0x0348ceb294e0b83d6c925ce892b001aea8e47b14d9f21f515810d5c7d0a28448 | 366 | 248448 |
| E1 | Emitido | EnergyToken | 0xe544ef15d647db828f7e2e96fd78640d50bf1aa10b1020cd82a4a368d5dd38f8 | 367 | 248448 |
| E1 | Emitido | EnergyToken | 0xac35d612391efd85005c6e67cd937cfd987e080a9a5fa333ee90fba60aefb8ba | 368 | 248448 |
| E1 | Emitido | EnergyToken | 0x8d8e28dba73d39e81edad36d7f603a2053e9d7f0a7d7356e47a12fc9d69694cf | 369 | 248436 |
| E1 | Emitido | EnergyToken | 0x8895a50c0958f5849a18f5e84048fa3e02048da6c5128d0f3c7f7439e44013ad | 370 | 248448 |
| E1 | Emitido | EnergyToken | 0x683ff6fda231cd7f181f408896facdc4e0e76a8d749a02bbdaadf9f1afffd230 | 371 | 248448 |
| E1 | Emitido | EnergyToken | 0x69502939d0931620259fdaf74b9eea832cc59f049c24ce01c6bdf209497c0fb5 | 372 | 248448 |
| E1 | Emitido | EnergyToken | 0x7b1d8ec4586116049a69494c16c6144d0e3967888efbbe16c5fdc62d1217fcce | 373 | 248436 |
| E1 | Emitido | EnergyToken | 0xd9a9b35d930c72b8ba7414a9429a471754afc24a34f2dfc43b7f5ea0d9a2a628 | 374 | 248448 |
| E1 | Emitido | EnergyToken | 0x9a289997c9ca2343817bf2d2e172aec43605e6d8091a0cf17bafe86262096473 | 375 | 248448 |
| E1 | Emitido | EnergyToken | 0x7dfe64e9da2da93d8d62d6c06ac19b1aa70fdb0292214ebf509aa3c1e8ea5864 | 376 | 248448 |
| E1 | Emitido | EnergyToken | 0x1d8f4400746bedf3de82b4661372154c888b41e373afb3c5b8adbbea4ac0a39b | 377 | 248448 |
| E1 | Emitido | EnergyToken | 0x7e5061d3c518ab04bbf23d93f09a25473a962bdbdf1a931b47e370ae91f2039e | 378 | 248436 |
| E1 | Emitido | EnergyToken | 0xa0bd92cc82324919a8b72522ac8e15b8f01bc409c2070674bb36f46d88e9a698 | 379 | 248436 |
| E1 | Emitido | EnergyToken | 0x4dcbb5a544cdecc241b84ab907e662247ef62e08a0177630e708b28b033bd722 | 380 | 248448 |
| E1 | Emitido | EnergyToken | 0x79d86f9d6b1da89f40f5099824e08d4cf6979eaeb6fd95e3c89873eed6c9473f | 381 | 248448 |
| E1 | Emitido | EnergyToken | 0xdde0a63e19f6a821712fb689e09236a6c267071849a3cf65f2291dfb5b5dde18 | 382 | 248448 |
| E1 | Emitido | EnergyToken | 0x05d1b135fa1d39330ec6b7dfe543227ea4baf49cd1105f58fea64f6a65cd858c | 383 | 248448 |
| E1 | Emitido | EnergyToken | 0x8ae97821968419c8b76cd988e416915dc886efdb1a6f895d684aff41538d36d3 | 384 | 248448 |
| E1 | Emitido | EnergyToken | 0x6fad2a1d0617465e8e6df4054835d6b23bde83de3727bba7184cc1f239b6bd00 | 385 | 248448 |
| E1 | Emitido | EnergyToken | 0x1c54e59dac9a7d191b8a118babd47774dab23d10889d1922ac9268c466d094f2 | 386 | 248448 |
| E1 | Emitido | EnergyToken | 0x9d8f9fffd07d7d3a38698bb279cd790fc62619819e068fd245281778c6497ba1 | 387 | 248448 |
| E1 | Emitido | EnergyToken | 0x35d50fefb697bd34e8314306d7eb7be7eac308e9502e1afeeff77ec4a4e1310c | 388 | 248436 |
| E1 | Emitido | EnergyToken | 0x471d27915d9dc3d28000da02d06993f1c769ca18ef2096d717be122914d4a334 | 389 | 248448 |
| E1 | Emitido | EnergyToken | 0x7a840a1622944c1fd9a8abd35c1964093915588ae802a54fefa95550de562af7 | 390 | 248448 |
| E1 | Emitido | EnergyToken | 0xc64d45338bd4f26cf6181602e5c3c5fe48c3446809d0813fbbbe5d5bb6ba34a8 | 391 | 248448 |
| E1 | Emitido | EnergyToken | 0x46b0546385270bda9da239f54670f4ba8e25d4d1968a67f36a7b11bc99c810e1 | 392 | 248448 |
| E1 | Emitido | EnergyToken | 0xa07ff8285aa6d3bb1119c37c0b81bbe359fd87a56176e93cc64f312bd5897dcf | 393 | 248448 |
| E1 | Emitido | EnergyToken | 0xcebb0ee3c3786ff9572aa988de02b4bd108b131b9f6588e0e5bd4d5dc991e25b | 394 | 248448 |
| E1 | Emitido | EnergyToken | 0x4d1122f1aa60c51c58c265b38916150732b376cce1dd0abb248efa6ce41035d8 | 395 | 248448 |
| E1 | Emitido | EnergyToken | 0xd14183a3386f7eef3d9d34d42e77612485325b877657f28927c08d4ec5c5af1f | 396 | 248448 |
| E1 | Emitido | EnergyToken | 0x6fa551cde8453381580b38cf531097ee91138ca51f0ef1c6ba7e50271d478df9 | 397 | 248448 |
| E1 | Emitido | EnergyToken | 0x971b0fe99329bc053a14e6b0333879cf1bcf52222363cabcb5e7f0fe76b75ecf | 398 | 248448 |
| E1 | Emitido | EnergyToken | 0x817ddb6e176bad1099793186b9f41888dc665f2f934e36dc55948c23d49695fa | 399 | 248448 |
| E1 | Emitido | EnergyToken | 0x95b3a99da5742fcaaafb3ba2fe57400241d092d6529aeeac38bf454c83104701 | 400 | 248436 |
| E1 | Emitido | EnergyToken | 0x9a3de12d7991513bac9d231b7a42e033aecc66cc1ae31fa997f0ab266fccc577 | 401 | 248436 |
| E1 | Emitido | EnergyToken | 0xb592364f047fb3987a34696e2fa6d17a919f6701a1a2d7aefb6702a2693dad06 | 402 | 248448 |
| E1 | Emitido | EnergyToken | 0x2e251f45d0fff963b5a7519a0c3c19e91944a6f768a467f353b4c8b021d507ba | 403 | 248448 |
| E1 | Emitido | EnergyToken | 0x142d2bcd1f6a765aa5e68233b2b4f88169fdb91ba1cefd42cce69040b148d9c4 | 404 | 248448 |
| E1 | Emitido | EnergyToken | 0xa138b6d56458cb62d235de1e17a020ffb60afe63ac12fab4d0c089da42b33de7 | 405 | 248448 |
| E1 | Emitido | EnergyToken | 0xd5db7b9db9d26b5c000336eb3488924f06e8574df9e5d95f35591cea54629450 | 406 | 248448 |
| E1 | Emitido | EnergyToken | 0x1b1cd94da02a81d8a73773715c4bd2976ef0349ee0bc5540185d0fe661d23532 | 407 | 248448 |
| E1 | Emitido | EnergyToken | 0xa9c5d52a45ff39cbfd6b91ef6c95cfd7798c43e6438abf4de931598f6834d240 | 408 | 248436 |
| E1 | Emitido | EnergyToken | 0xe69ff315ba2680bbd6ecba607b01ff1d56203b9f59db0405e43a78021d7f4975 | 409 | 248448 |
