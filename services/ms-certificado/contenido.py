"""Almacen de contenido direccionable local (fallback de Pinata) para ms_certificado.

Este modulo implementa el fallback local exigido por R3.3: cuando no hay internet ni
credenciales de Pinata, el certificado PDF se guarda en un almacen de contenido
direccionable que calcula el **CIDv1** del contenido con el mismo algoritmo que IPFS, de
modo que el CID siga siendo *determinado por el contenido* (Property 5) y la verificacion
por contenido sea equivalente a la de Pinata.

Formato del CID (identico al CIDv1 por defecto de IPFS para un bloque "raw"):

    CIDv1 = multibase_base32( <version=0x01> <codec=raw=0x55> <multihash> )
    multihash = <fn=sha2-256=0x12> <len=0x20=32> <digest sha-256 de 32 bytes>

El resultado se codifica en multibase base32 (RFC 4648, minusculas, sin relleno) con el
prefijo de multibase `b`. Por ejemplo, el contenido vacio produce:

    bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku

que coincide con `ipfs add --cid-version=1 --raw-leaves` sobre un archivo vacio.

El almacen guarda cada blob indexado por su CID y permite recuperarlo despues. El indice
es el CID, por lo que guardar dos veces el mismo contenido es idempotente y recuperar por
un CID inexistente senaliza "no encontrado" (insumo para el veredicto ERROR de R3.11/R3.12).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# --- Constantes del formato CIDv1 (raw + sha2-256), alineadas con IPFS -------------------
_CID_VERSION_1 = 0x01          # CIDv1
_CODEC_RAW = 0x55              # multicodec "raw" (bloque de bytes sin estructura)
_MULTIHASH_SHA2_256 = 0x12     # multihash: funcion sha2-256
_SHA2_256_LEN = 0x20           # multihash: longitud del digest (32 bytes)
_MULTIBASE_BASE32_PREFIX = "b"  # prefijo multibase para base32 (RFC 4648, minusculas)

# Alfabeto base32 de RFC 4648 en minusculas, tal como lo usa multibase ('b').
_BASE32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def _b32_lower_nopad(data: bytes) -> str:
    """Codifica `data` en base32 (RFC 4648) en minusculas y SIN relleno.

    multibase usa base32 sin el relleno `=` de la codificacion estandar; se implementa
    directamente sobre el alfabeto para no depender de recortes de `base64.b32encode`.
    """
    bits = 0
    nbits = 0
    salida: list[str] = []
    for byte in data:
        bits = (bits << 8) | byte
        nbits += 8
        while nbits >= 5:
            nbits -= 5
            salida.append(_BASE32_ALPHABET[(bits >> nbits) & 0x1F])
    if nbits:
        # Quedan <5 bits: se rellenan con ceros a la derecha para formar el ultimo simbolo.
        salida.append(_BASE32_ALPHABET[(bits << (5 - nbits)) & 0x1F])
    return "".join(salida)


def multihash_sha2_256(contenido: bytes) -> bytes:
    """Devuelve el multihash sha2-256 de `contenido`: `0x12 0x20 <digest de 32 bytes>`."""
    digest = hashlib.sha256(contenido).digest()
    return bytes((_MULTIHASH_SHA2_256, _SHA2_256_LEN)) + digest


def calcular_cid(contenido: bytes) -> str:
    """Calcula el CIDv1 (codec raw, multihash sha2-256, base32) de `contenido`.

    Equivale al CID que IPFS/Pinata asignarian al mismo contenido como bloque raw, por lo
    que el CID queda *determinado por el contenido*: mismo contenido -> mismo CID, y
    contenidos distintos -> CIDs distintos (salvo colision criptografica de sha-256).
    """
    if not isinstance(contenido, (bytes, bytearray)):
        raise TypeError("el contenido debe ser bytes")
    cid_bytes = bytes((_CID_VERSION_1, _CODEC_RAW)) + multihash_sha2_256(bytes(contenido))
    return _MULTIBASE_BASE32_PREFIX + _b32_lower_nopad(cid_bytes)


class ContenidoNoEncontrado(KeyError):
    """Se solicito recuperar un contenido por un CID que no esta en el almacen."""


class AlmacenContenido:
    """Almacen de contenido direccionable en memoria, indexado por el CIDv1 del contenido.

    Es el fallback local de Pinata (R3.3): guarda blobs y los recupera por su CID. Guardar
    es idempotente porque el indice es el propio contenido. Recuperar por un CID ausente
    lanza `ContenidoNoEncontrado`, insumo del veredicto ERROR de la verificacion.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def guardar(self, contenido: bytes) -> str:
        """Guarda `contenido` indexado por su CID y devuelve ese CID.

        Idempotente: guardar el mismo contenido mas de una vez no lo duplica y devuelve
        siempre el mismo CID.
        """
        cid = calcular_cid(contenido)
        self._blobs[cid] = bytes(contenido)
        return cid

    def recuperar(self, cid: str) -> bytes:
        """Recupera el contenido indexado por `cid`.

        Lanza `ContenidoNoEncontrado` si el CID no esta en el almacen (equivale a "contenido
        no recuperable" en la verificacion: nunca debe interpretarse como INTEGRO).
        """
        try:
            return self._blobs[cid]
        except KeyError as exc:
            raise ContenidoNoEncontrado(cid) from exc

    def existe(self, cid: str) -> bool:
        """Indica si hay contenido guardado bajo `cid`."""
        return cid in self._blobs

    def __contains__(self, cid: object) -> bool:
        return isinstance(cid, str) and cid in self._blobs

    def __len__(self) -> int:
        return len(self._blobs)


class AlmacenContenidoDisco(AlmacenContenido):
    """Variante del almacen que persiste cada blob en disco como `<dir>/<cid>`.

    Util cuando la corrida necesita que el contenido sobreviva al proceso. El indice sigue
    siendo el CID (nombre de archivo), asi que mantiene la equivalencia por contenido con
    Pinata y la idempotencia del guardado.
    """

    def __init__(self, directorio: str | Path) -> None:
        super().__init__()
        self._dir = Path(directorio)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _ruta(self, cid: str) -> Path:
        return self._dir / cid

    def guardar(self, contenido: bytes) -> str:
        cid = calcular_cid(contenido)
        self._ruta(cid).write_bytes(bytes(contenido))
        self._blobs[cid] = bytes(contenido)
        return cid

    def recuperar(self, cid: str) -> bytes:
        if cid in self._blobs:
            return self._blobs[cid]
        ruta = self._ruta(cid)
        if ruta.is_file():
            datos = ruta.read_bytes()
            self._blobs[cid] = datos
            return datos
        raise ContenidoNoEncontrado(cid)

    def existe(self, cid: str) -> bool:
        return cid in self._blobs or self._ruta(cid).is_file()

    def __contains__(self, cid: object) -> bool:
        return isinstance(cid, str) and self.existe(cid)
