"""Dobles de prueba del `chain_client` para ejercitar ms_energia sin Anvil."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EstadoTx(str, Enum):
    CONFIRMADA = "confirmada"
    REVERTIDA = "revertida"
    TIMEOUT = "timeout"


@dataclass
class ResultadoTx:
    estado: EstadoTx
    transactionHash: str
    gasUsed: int | None = None
    blockNumber: int | None = None

    @property
    def confirmada(self) -> bool:
        return self.estado is EstadoTx.CONFIRMADA


class _FakeFunction:
    def __init__(self, nombre: str, args: tuple):
        self.nombre = nombre
        self.args = args

    def build_transaction(self, overrides: dict[str, Any]) -> dict[str, Any]:
        return {"funcion": self.nombre, "args": self.args, **overrides}


class _FakeFunctions:
    def __init__(self, registro: list):
        self._registro = registro

    def emitir(self, a, id, kwh, precio, lectura_id):  # noqa: A002
        self._registro.append((a, id, kwh, precio, lectura_id))
        return _FakeFunction("emitir", (a, id, kwh, precio, lectura_id))


class _FakeContract:
    def __init__(self, registro: list):
        self.functions = _FakeFunctions(registro)


@dataclass
class FakeChain:
    """Chain client falso: registra cada `emitir` construido y cada tx enviada.

    `resultado` controla el estado devuelto por `enviar_y_esperar`. Con `delay` se puede
    simular trabajo para ejercitar la concurrencia. Thread-safe.
    """

    plataforma: str = "0x0000000000000000000000000000000000000001"
    resultado: ResultadoTx = field(
        default_factory=lambda: ResultadoTx(EstadoTx.CONFIRMADA, "0xhash", gasUsed=21000, blockNumber=1)
    )
    delay: float = 0.0
    emitir_calls: list = field(default_factory=list)
    enviadas: list = field(default_factory=list)
    _nonce: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def energy_token(self):
        return _FakeContract(self.emitir_calls)

    def siguiente_nonce(self) -> int:
        with self._lock:
            n = self._nonce
            self._nonce += 1
            return n

    def enviar_y_esperar(self, tx: dict[str, Any], timeout_s: int | None = None) -> ResultadoTx:
        if self.delay:
            import time

            time.sleep(self.delay)
        with self._lock:
            self.enviadas.append((tx, timeout_s))
        return self.resultado
