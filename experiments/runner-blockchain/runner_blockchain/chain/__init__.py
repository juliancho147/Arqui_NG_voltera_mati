"""Utilidades de acceso a la Cadena_Local (Anvil) y al despliegue de contratos.

Incluye `chain_client`, el cliente comun que resuelve el ABI de Foundry desde
`blockchain/out/`, construye los objetos `Contract` de web3.py, firma con la llave
custodial de la plataforma y expone helpers de envio/confirmacion y de reparto de
nonces para el envio concurrente de E3.
"""
