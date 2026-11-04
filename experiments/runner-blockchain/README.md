# Runner de la experimentacion blockchain local (Voltera)

MVP de validacion experimental blockchain (punto 07, Entrega 4): ejecuta los tres
experimentos del cuaderno contra una cadena **local** Anvil, reutilizando los
contratos Foundry de `blockchain/` sin modificarlos.

- E1 — Integridad del Oracle
- E2 — Integridad del certificado off-chain
- E3 — Tokenizacion sin doble venta

El plan de implementacion, los requisitos y el diseno viven en
`.kiro/specs/experimentos-blockchain-local/` (`tasks.md`, `requirements.md`,
`design.md`). Este paquete sigue el estilo de `experiments/runner/`.

## Herramientas del entorno

Este MVP requiere las siguientes herramientas instaladas en la máquina (R1.7):

| Herramienta | Versión | Uso en el MVP |
|---|---|---|
| Foundry (`forge` / `anvil` / `cast`) | 1.9.0 | Arrancar la cadena local Anvil (chain-id 11155111, `:8545`) y desplegar/compilar los contratos de `blockchain/` con el binario nativo. |
| Node.js | 24 | Tooling del repositorio (incluye `npm`). |
| Python | 3.14 | Runner, microservicios y pruebas (Hypothesis/pytest) de este paquete. |

Comprobar las versiones instaladas:

```bash
forge --version   # forge 1.9.0
anvil --version   # anvil 1.9.0
cast --version    # cast 1.9.0
node --version    # v24.x
python3.14 --version  # Python 3.14.x
```

**Docker NO es requerido para este MVP.** Tampoco se necesitan `kind` ni
`kubectl`: la Cadena_Local se ejecuta directamente con el binario nativo de
Anvil (Foundry) y los microservicios y el runner corren como procesos Python
locales en la máquina.

## Uso

```bash
cd experiments/runner-blockchain
python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # pruebas locales

# cuando el CLI este implementado (tarea 12.x):
.venv/bin/python -m runner_blockchain e1|e2|e3|all [opciones]
```

Credenciales de Pinata (`PINATA_JWT`) y la llave de la plataforma
(`PLATAFORMA_PRIVATE_KEY`) se leen del entorno y nunca se guardan en el repo ni
aparecen en los reportes.
