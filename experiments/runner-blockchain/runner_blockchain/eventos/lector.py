"""Lector_Eventos: recoleccion de evidencia on-chain de la corrida (R6).

El `Lector_Eventos` lee los eventos que emiten los contratos durante una corrida y los
entrega al Runner_Experimentos como evidencia reproducible:

* `Emitido`  -> EnergyToken  (R6.1)
* `Compra`   -> MarketEscrow (R6.1)
* `Anclado`  -> MarketEscrow (R6.1)

Para cada evento observado se construye un `EventoOnChain` que lleva el `runId` de la
corrida, el `transactionHash`, el `blockNumber` y (cuando aplica) el `gasUsed` leido del
recibo de la transaccion (R6.2). Al terminar la corrida, `leer_eventos` devuelve la lista
completa de eventos observados para que el runner la incorpore al Reporte_Resultados (R6.3).

La lectura usa `eth_getLogs` (via `ContractEvent.get_logs` de web3.py) sobre las direcciones
registradas en `deployment.json`, resueltas a traves del `ChainClient`. No hay bus de
dominio, ni checkpoints, ni deduplicacion entre reinicios: cada corrida lee el rango de
bloques indicado y entrega lo observado tal cual (alcance del MVP).

Disponibilidad (R6.4): si la Cadena_Local no responde dentro de 30 s a la consulta de
eventos (timeout de red, error de conexion o agotamiento del tope global), se registra el
error de indisponibilidad y se lanza `LectorEventosError`, sin entregar una lista parcial
como si fuera completa.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from web3.exceptions import Web3Exception

try:  # requests subyace al HTTPProvider; sus errores de red indican indisponibilidad (R6.4).
    from requests.exceptions import RequestException
except Exception:  # pragma: no cover - requests siempre esta por web3, pero no dependemos de ello.
    RequestException = ()  # type: ignore[assignment]

from ..chain.chain_client import ChainClient
from .. import progreso

logger = logging.getLogger(__name__)

# Evento -> contrato que lo emite (R6.1). El orden fija el de recoleccion.
TIPOS_EVENTO: tuple[tuple[str, str], ...] = (
    ("Emitido", "EnergyToken"),
    ("Compra", "MarketEscrow"),
    ("Anclado", "MarketEscrow"),
)

# Tope duro de disponibilidad de la cadena para la consulta de eventos (R6.4).
READ_TIMEOUT_S = 30


class LectorEventosError(RuntimeError):
    """La cadena no respondio a la consulta de eventos (indisponibilidad, R6.4)."""


@dataclass(frozen=True)
class EventoOnChain:
    """Un evento on-chain observado, trazado a la corrida (R6.2).

    * `run_id`: identificador de la corrida a la que pertenece el evento.
    * `tipo`: `Emitido` | `Compra` | `Anclado`.
    * `contrato`: contrato emisor (EnergyToken | MarketEscrow).
    * `args`: campos decodificados del evento (p. ej. `id`, `kwh`, `ofertaId`...).
    * `transaction_hash` / `block_number`: ubicacion on-chain del evento (R6.2).
    * `log_index`: indice del log dentro del bloque (orden estable, no para dedup).
    * `gas_used`: gas del recibo de la tx cuando se resuelve; None si no aplica/disponible.
    """

    run_id: str
    tipo: str
    contrato: str
    args: dict[str, Any]
    transaction_hash: str
    block_number: int
    log_index: int | None = None
    gas_used: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Representacion serializable para el Reporte_Resultados (R7.3)."""
        return {
            "runId": self.run_id,
            "tipo": self.tipo,
            "contrato": self.contrato,
            "args": dict(self.args),
            "transactionHash": self.transaction_hash,
            "blockNumber": self.block_number,
            "logIndex": self.log_index,
            "gasUsed": self.gas_used,
        }


class LectorEventos:
    """Lee los eventos de la corrida con `eth_getLogs` y los traza al `runId` (R6).

    El lector no persiste estado entre corridas ni deduplica: en cada llamada a
    `leer_eventos` consulta el rango de bloques pedido y entrega lo observado. El runner
    decide el rango (p. ej. desde el bloque previo al inicio del experimento hasta `latest`).
    """

    def __init__(
        self,
        client: ChainClient,
        *,
        tipos: tuple[tuple[str, str], ...] = TIPOS_EVENTO,
        read_timeout_s: int = READ_TIMEOUT_S,
    ) -> None:
        self.client = client
        self.tipos = tipos
        self.read_timeout_s = read_timeout_s
        # Cache de gasUsed por tx_hash dentro de una corrida: varios logs comparten tx.
        self._gas_cache: dict[str, int | None] = {}

    # ---- lectura -------------------------------------------------------------
    def leer_eventos(
        self,
        run_id: str,
        *,
        from_block: int | str = 0,
        to_block: int | str = "latest",
        incluir_gas: bool = True,
    ) -> list[EventoOnChain]:
        """Lee `Emitido`/`Compra`/`Anclado` de la corrida y los devuelve trazados al runId.

        Consulta cada tipo con `eth_getLogs` sobre la direccion del contrato emisor
        (resuelta por el `ChainClient` desde `deployment.json`). Asocia cada evento al
        `run_id` y registra `transactionHash`, `blockNumber` y, si `incluir_gas`, el
        `gasUsed` del recibo de la tx (R6.2). Devuelve la lista completa observada, ordenada
        por `(blockNumber, logIndex)` (R6.3).

        Lanza `LectorEventosError` si la cadena no responde dentro de `read_timeout_s`
        (indisponibilidad, R6.4).
        """
        deadline = time.monotonic() + self.read_timeout_s
        self._gas_cache.clear()
        eventos: list[EventoOnChain] = []

        for nombre, contrato in self.tipos:
            if time.monotonic() >= deadline:
                self._indisponibilidad(
                    f"se agoto el tope de {self.read_timeout_s} s consultando eventos de la corrida {run_id}"
                )
            logs = self._get_logs(nombre, contrato, from_block, to_block, run_id)
            for log in logs:
                eventos.append(
                    self._a_evento(
                        run_id=run_id,
                        tipo=nombre,
                        contrato=contrato,
                        log=log,
                        incluir_gas=incluir_gas,
                        deadline=deadline,
                    )
                )

        eventos.sort(key=lambda e: (e.block_number, e.log_index if e.log_index is not None else 0))
        logger.info("Lector_Eventos: %d eventos observados en la corrida %s", len(eventos), run_id)
        try:
            _tipos: dict[str, int] = {}
            for _e in eventos:
                _tipos[_e.tipo] = _tipos.get(_e.tipo, 0) + 1
            progreso.emitir("eventos", f"Lector_Eventos: {len(eventos)} eventos on-chain observados",
                            exp="runner", total=len(eventos), porTipo=_tipos)
        except Exception:
            pass
        return eventos

    # ---- helpers internos ----------------------------------------------------
    def _get_logs(
        self,
        nombre: str,
        contrato: str,
        from_block: int | str,
        to_block: int | str,
        run_id: str,
    ) -> list[Any]:
        """`eth_getLogs` del evento `nombre` del contrato `contrato` (R6.1).

        Traduce timeouts/errores de red y errores de web3 a `LectorEventosError` (R6.4).
        """
        evento = getattr(self.client.contract(contrato).events, nombre)
        try:
            return list(evento.get_logs(from_block=from_block, to_block=to_block))
        except RequestException as exc:  # timeout / conexion rechazada -> indisponibilidad
            self._indisponibilidad(
                f"la Cadena_Local no respondio a la consulta de {nombre} ({contrato}) "
                f"para la corrida {run_id}: {exc}"
            )
        except Web3Exception as exc:
            self._indisponibilidad(
                f"error de la Cadena_Local al consultar {nombre} ({contrato}) "
                f"para la corrida {run_id}: {exc}"
            )
        except OSError as exc:
            self._indisponibilidad(
                f"error de red al consultar {nombre} ({contrato}) para la corrida {run_id}: {exc}"
            )
        return []  # pragma: no cover - _indisponibilidad siempre lanza

    def _a_evento(
        self,
        *,
        run_id: str,
        tipo: str,
        contrato: str,
        log: Any,
        incluir_gas: bool,
        deadline: float,
    ) -> EventoOnChain:
        """Convierte un `EventData` decodificado de web3.py en un `EventoOnChain` trazado."""
        tx_hash = _hex(_get(log, "transactionHash"))
        block_number = _opt_int(_get(log, "blockNumber"))
        log_index = _opt_int(_get(log, "logIndex"))
        args = _args_a_dict(_get(log, "args"))

        gas_used: int | None = None
        if incluir_gas:
            gas_used = self._gas_de_tx(tx_hash, deadline, run_id)

        return EventoOnChain(
            run_id=run_id,
            tipo=tipo,
            contrato=contrato,
            args=args,
            transaction_hash=tx_hash,
            block_number=block_number if block_number is not None else -1,
            log_index=log_index,
            gas_used=gas_used,
        )

    def _gas_de_tx(self, tx_hash: str, deadline: float, run_id: str) -> int | None:
        """`gasUsed` del recibo de `tx_hash` (R6.2), cacheado por tx dentro de la corrida."""
        if tx_hash in self._gas_cache:
            return self._gas_cache[tx_hash]
        if time.monotonic() >= deadline:
            self._indisponibilidad(
                f"se agoto el tope de {self.read_timeout_s} s leyendo el recibo de {tx_hash} "
                f"en la corrida {run_id}"
            )
        try:
            recibo = self.client.w3.eth.get_transaction_receipt(tx_hash)
            gas = _opt_int(_get(recibo, "gasUsed"))
        except RequestException as exc:
            self._indisponibilidad(
                f"la Cadena_Local no respondio al leer el recibo de {tx_hash} "
                f"en la corrida {run_id}: {exc}"
            )
        except (Web3Exception, OSError) as exc:
            # El recibo es evidencia auxiliar (gas); si no se puede leer por un motivo no
            # relacionado con indisponibilidad de red, se deja gasUsed=None sin abortar.
            logger.warning("no se pudo leer gasUsed del recibo %s (%s): %s", tx_hash, run_id, exc)
            gas = None
        self._gas_cache[tx_hash] = gas
        return gas

    def _indisponibilidad(self, mensaje: str) -> None:
        """Registra el error de indisponibilidad de la cadena y lo lanza (R6.4)."""
        logger.error("Lector_Eventos: indisponibilidad de la Cadena_Local: %s", mensaje)
        raise LectorEventosError(mensaje)


# ---------------------------------------------------------------------------
# Normalizacion de valores decodificados por web3.py
# ---------------------------------------------------------------------------
def _get(obj: Any, clave: str) -> Any:
    """Lee `clave` de un `EventData`/`AttributeDict` o de un dict plano."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(clave)
    return getattr(obj, clave, None)


def _args_a_dict(args: Any) -> dict[str, Any]:
    """Convierte los `args` decodificados en un dict serializable (bytes/HexBytes -> hex)."""
    if args is None:
        return {}
    bruto = dict(args) if not isinstance(args, dict) else args
    return {str(k): _normalizar_valor(v) for k, v in bruto.items()}


def _normalizar_valor(value: Any) -> Any:
    """Normaliza un valor de arg a algo JSON-serializable (bytes -> hex, resto intacto)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    hexfn = getattr(value, "hex", None)  # HexBytes
    if callable(hexfn) and not isinstance(value, str):
        h = hexfn()
        return h if isinstance(h, str) and h.startswith("0x") else f"0x{h}"
    if isinstance(value, (list, tuple)):
        return [_normalizar_valor(v) for v in value]
    return value


def _hex(value: Any) -> str:
    """Normaliza un hash (bytes/HexBytes/str) a cadena hex con prefijo `0x`."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    hexfn = getattr(value, "hex", None)
    if callable(hexfn):
        h = hexfn()
        return h if h.startswith("0x") else f"0x{h}"
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    return str(value)


def _opt_int(value: Any) -> int | None:
    """Convierte a int si es posible; None si el valor es None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
