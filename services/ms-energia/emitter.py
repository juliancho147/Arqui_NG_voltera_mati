"""Logica de emision idempotente por lectura de ms_energia (R5.2, R5.9, R5.10).

A partir de una generacion validada, ms_energia llama
`EnergyToken.emitir(a, id, kwh, precio, lecturaId)` **exactamente una vez por `lecturaId`**.
La transaccion la firma la llave custodial de la plataforma (via el `chain_client` comun) y
se espera su confirmacion on-chain con tope de 30 s, sin reintento automatico.

Idempotencia por lectura
-------------------------
`EmisionService` mantiene un registro en memoria de los `lecturaId` ya procesados. La
primera generacion validada con un `lecturaId` dado dispara una unica llamada a `emitir`;
cualquier reentrega del mismo `lecturaId` devuelve el resultado ya registrado **sin** volver
a llamar a `emitir` (asi hay exactamente un `Emitido` on-chain por lectura). Un candado por
instancia serializa el "chequea-o-emite" para que dos entregas concurrentes del mismo
`lecturaId` no produzcan dos transacciones.

Manejo de error (R5.10)
-----------------------
Si la transaccion se revierte o no confirma dentro del tope de 30 s, se registra el error
con el identificador de la operacion afectada (`lecturaId`), **no se reintenta** de forma
automatica y la operacion off-chain queda **sin** marcar como completada
(`emitida == False`). Ese resultado terminal tambien se memoriza por `lecturaId`: una
reentrega no lanza una segunda transaccion por si sola.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from web3 import Web3


class ValidacionError(ValueError):
    """La generacion validada recibida no es procesable (campos ausentes/invalidos)."""


class ChainLike(Protocol):
    """Subconjunto del `chain_client` comun que necesita ms_energia."""

    plataforma: str

    @property
    def energy_token(self) -> Any: ...

    def siguiente_nonce(self) -> int: ...

    def enviar_y_esperar(self, tx: dict[str, Any], timeout_s: int | None = None) -> Any: ...


@dataclass(frozen=True)
class GeneracionValidada:
    """Datos de una generacion validada que originan una emision.

    * `a`: direccion seudonima del participante que recibe la energia.
    * `id`: fuente+epoca (uint256) ya resuelto; o derivado de `fuente`+`epoca`.
    * `kwh`: cantidad de kWh a emitir (> 0).
    * `precio`: precio por kWh calculado off-chain (> 0).
    * `lectura_id`: identificador de la lectura validada (clave de idempotencia).
    """

    a: str
    id: int
    kwh: int
    precio: int
    lectura_id: str

    @classmethod
    def desde_payload(cls, payload: dict[str, Any]) -> "GeneracionValidada":
        if not isinstance(payload, dict):
            raise ValidacionError("el cuerpo de la emision debe ser un objeto JSON")

        lectura_id = payload.get("lecturaId")
        if not isinstance(lectura_id, str) or not lectura_id.strip():
            raise ValidacionError("falta 'lecturaId' (identificador de la lectura validada)")
        lectura_id = lectura_id.strip()

        a = payload.get("a") or payload.get("participante")
        if not isinstance(a, str) or not a.strip():
            raise ValidacionError("falta 'a' (direccion del participante)")
        try:
            a = Web3.to_checksum_address(a.strip())
        except (ValueError, TypeError) as exc:
            raise ValidacionError(f"'a' no es una direccion valida: {a!r}") from exc

        id_ = _resolver_id(payload)
        kwh = _entero_positivo(payload.get("kwh"), "kwh")
        precio = _entero_positivo(payload.get("precio"), "precio")

        return cls(a=a, id=id_, kwh=kwh, precio=precio, lectura_id=lectura_id)


@dataclass
class ResultadoEmision:
    """Resultado terminal de procesar una generacion validada por `lecturaId`."""

    lectura_id: str
    emitida: bool
    estado: str                      # confirmada | revertida | timeout
    transaction_hash: str | None = None
    gas_used: int | None = None
    block_number: int | None = None
    error: str | None = None
    duplicada: bool = False          # True si vino de una reentrega (no se reemitio)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lecturaId": self.lectura_id,
            "emitida": self.emitida,
            "estado": self.estado,
            "transactionHash": self.transaction_hash,
            "gasUsed": self.gas_used,
            "blockNumber": self.block_number,
            "error": self.error,
            "duplicada": self.duplicada,
        }


@dataclass
class EmisionService:
    """Servicio de emision idempotente por `lecturaId` sobre `EnergyToken.emitir`."""

    chain: ChainLike
    confirm_timeout_s: int = 30
    _vistos: dict[str, ResultadoEmision] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def ya_emitida(self, lectura_id: str) -> bool:
        with self._lock:
            return lectura_id in self._vistos

    def emitir(self, gen: GeneracionValidada) -> ResultadoEmision:
        """Procesa una generacion validada: emite una sola vez por `lecturaId`.

        Reentregas del mismo `lecturaId` devuelven el resultado ya registrado marcado como
        `duplicada=True`, sin lanzar una segunda transaccion.
        """
        # Candado: solo UNA entrega por lecturaId pasa a construir/enviar la tx.
        with self._lock:
            previo = self._vistos.get(gen.lectura_id)
            if previo is not None:
                return _como_duplicada(previo)
            # Reserva el lecturaId antes de soltar el candado para que entregas concurrentes
            # vean "en curso" y no disparen una segunda emision. Se completa abajo.
            en_curso = ResultadoEmision(
                lectura_id=gen.lectura_id,
                emitida=False,
                estado="en_curso",
            )
            self._vistos[gen.lectura_id] = en_curso

        resultado = self._emitir_on_chain(gen)

        with self._lock:
            self._vistos[gen.lectura_id] = resultado
        return resultado

    def _emitir_on_chain(self, gen: GeneracionValidada) -> ResultadoEmision:
        tx = self._construir_tx(gen)
        res = self.chain.enviar_y_esperar(tx, timeout_s=self.confirm_timeout_s)
        confirmada = bool(getattr(res, "confirmada", False))
        estado = getattr(getattr(res, "estado", None), "value", None) or str(getattr(res, "estado", ""))
        error = None
        if not confirmada:
            # R5.10: registra el error con el identificador de la operacion afectada; no reintenta.
            error = f"emision {estado} para lecturaId={gen.lectura_id}"
        return ResultadoEmision(
            lectura_id=gen.lectura_id,
            emitida=confirmada,
            estado=estado,
            transaction_hash=getattr(res, "transactionHash", None),
            gas_used=getattr(res, "gasUsed", None),
            block_number=getattr(res, "blockNumber", None),
            error=error,
        )

    def _construir_tx(self, gen: GeneracionValidada) -> dict[str, Any]:
        """Construye la transaccion `emitir(a, id, kwh, precio, lecturaId)` firmable.

        `lecturaId` viaja como `bytes32`: si es hex de 32 bytes se usa tal cual; en otro caso
        se deriva de forma determinista con keccak256 de su UTF-8.
        """
        lectura_bytes32 = _a_bytes32(gen.lectura_id)
        funcion = self.chain.energy_token.functions.emitir(
            gen.a, gen.id, gen.kwh, gen.precio, lectura_bytes32
        )
        return funcion.build_transaction(
            {
                "from": self.chain.plataforma,
                "nonce": self.chain.siguiente_nonce(),
            }
        )


def _como_duplicada(previo: ResultadoEmision) -> ResultadoEmision:
    return ResultadoEmision(
        lectura_id=previo.lectura_id,
        emitida=previo.emitida,
        estado=previo.estado,
        transaction_hash=previo.transaction_hash,
        gas_used=previo.gas_used,
        block_number=previo.block_number,
        error=previo.error,
        duplicada=True,
    )


def _resolver_id(payload: dict[str, Any]) -> int:
    """Resuelve el `id` (uint256): explicito en 'id', o derivado de 'fuente'+'epoca'."""
    if payload.get("id") is not None:
        return _entero_no_negativo(payload.get("id"), "id")
    fuente = payload.get("fuente")
    epoca = payload.get("epoca")
    if isinstance(fuente, str) and fuente.strip() and epoca is not None:
        epoca_int = _entero_no_negativo(epoca, "epoca")
        fuente_bytes32 = _a_bytes32(fuente.strip())
        return int.from_bytes(Web3.solidity_keccak(["bytes32", "uint64"], [fuente_bytes32, epoca_int]), "big")
    raise ValidacionError("falta 'id' (o el par 'fuente'+'epoca' para derivarlo)")


def _a_bytes32(valor: str) -> bytes:
    """Normaliza un identificador de texto a `bytes32`.

    Hex de exactamente 32 bytes (`0x` + 64 hex) se usa literal; cualquier otra cadena se
    resume con keccak256 de su codificacion UTF-8 (determinista).
    """
    s = valor.strip()
    if s.startswith("0x") and len(s) == 66:
        try:
            return bytes.fromhex(s[2:])
        except ValueError:
            pass
    return Web3.keccak(text=s)


def _entero_positivo(valor: Any, campo: str) -> int:
    n = _entero_no_negativo(valor, campo)
    if n <= 0:
        raise ValidacionError(f"'{campo}' debe ser mayor que 0")
    return n


def _entero_no_negativo(valor: Any, campo: str) -> int:
    if isinstance(valor, bool):
        raise ValidacionError(f"'{campo}' debe ser un entero")
    try:
        n = int(valor)
    except (TypeError, ValueError) as exc:
        raise ValidacionError(f"'{campo}' debe ser un entero: {valor!r}") from exc
    if n < 0:
        raise ValidacionError(f"'{campo}' no puede ser negativo")
    return n
