# Contratos de Voltera · etapa 3 (mercado P2P)

Dos contratos en Solidity, probados con Foundry. Foundry se corre por Docker, no hace falta instalarlo.

| Archivo | Qué es |
|---|---|
| `src/EnergyToken.sol` | Token ERC-1155 de kWh. Guarda el precio por id y la lectura de origen. |
| `src/MarketEscrow.sol` | Mercado: publicar, comprar, cancelar y anclar el CID del certificado. |
| `test/Mercado.t.sol` | 16 pruebas (incluye doble venta y certificado). |
| `script/Desplegar.s.sol` | Despliega ambos contratos y los conecta. |

## Comandos (desde esta carpeta)
```bash
npm install                                   # OpenZeppelin
git clone --depth 1 --branch v1.9.4 https://github.com/foundry-rs/forge-std.git lib/forge-std
F="docker run --rm -v $PWD:/app -w /app ghcr.io/foundry-rs/foundry:latest"
$F "forge test -vv"                           # pruebas
$F "forge script script/Desplegar.s.sol --rpc-url http://host.docker.internal:8545 --private-key \$PK --broadcast"
```
En Anvil local, `PK` es la cuenta 0 de Anvil (llave pública de prueba). En Sepolia sale de Secrets Manager.
