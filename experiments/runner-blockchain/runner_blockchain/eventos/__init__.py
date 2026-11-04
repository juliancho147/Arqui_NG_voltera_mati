"""Recoleccion de evidencia de eventos on-chain de la corrida (R6).

Expone el `Lector_Eventos` (`lector.py`), que lee los eventos `Emitido` (EnergyToken) y
`Compra` / `Anclado` (MarketEscrow) con `eth_getLogs` sobre las direcciones de
`deployment.json`, los asocia al `runId` y los entrega al Runner_Experimentos como la
lista de evidencia on-chain de la corrida. Sin bus de dominio, sin checkpoints y sin
deduplicacion entre reinicios.
"""

from .lector import (
    EventoOnChain,
    LectorEventos,
    LectorEventosError,
    TIPOS_EVENTO,
)

__all__ = [
    "EventoOnChain",
    "LectorEventos",
    "LectorEventosError",
    "TIPOS_EVENTO",
]
