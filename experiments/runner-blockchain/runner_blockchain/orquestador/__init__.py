"""Orquestador del Entorno_Experimental (R1).

Arranca la Cadena_Local Anvil como proceso hijo, espera a que responda por JSON-RPC
(con tope de 30 s), despliega los contratos `EnergyToken`/`MarketEscrow` con el script
Foundry existente `blockchain/script/Desplegar.s.sol` (que ya ejecuta `configurarMercado`),
extrae las direcciones desplegadas y escribe `deployment.json` para que el runner, los
microservicios y el Lector_Eventos resuelvan direcciones y RPC.

Manejo de errores (R1.2, R1.6): si el puerto 8545 esta ocupado o el readiness se agota,
no se despliega y se registra la causa; si el despliegue falla, se detiene, se dejan los
experimentos sin habilitar y se registra el contrato afectado y el motivo.
"""
