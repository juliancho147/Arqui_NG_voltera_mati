"""Cliente de Pinata (IPFS en la nube) para ms_certificado (R3.3, R3.4, R5.5).

Integracion REAL con Pinata usando solo la biblioteca estandar (`urllib`), sin anadir
dependencias al servicio:

* Subir: ``POST https://api.pinata.cloud/pinning/pinFileToIPFS`` con el PDF como cuerpo
  multipart y autenticacion por JWT en ``Authorization: Bearer``. La respuesta trae
  ``IpfsHash`` (= CID) que se devuelve al llamador (R5.5).
* Recuperar: ``GET {gateway}/ipfs/{cid}`` para traer el contenido por su CID (R3.5).

Puntos clave de diseno:

* **Credenciales solo del entorno (R3.4):** el JWT llega por parametro desde `config`
  (leido de ``PINATA_JWT``). Este modulo nunca lo registra ni lo incluye en mensajes de
  error; los errores describen la causa ("sin credenciales", "timeout", codigo HTTP) sin
  volcar el token.
* **Fallos senalizados, no fatales (R3.3):** cualquier problema de red/credenciales/HTTP
  se traduce en `PinataNoDisponible`, para que `ms_certificado` caiga al almacen local sin
  romper el flujo.
* **Determinismo del CID:** Pinata calcula el CID por contenido igual que el fallback
  local (CIDv1 raw sha2-256), de modo que ambos caminos son equivalentes (Property 5).
"""
from __future__ import annotations

import json
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest

from config import PINATA_PIN_FILE_URL

# Tope de red alineado con el resto del MVP (no se reintenta; se cae al fallback).
_TIMEOUT_S = 30


class PinataNoDisponible(RuntimeError):
    """Pinata no se pudo usar (sin credenciales, sin red, timeout o error HTTP).

    El mensaje describe la causa SIN exponer el JWT ni ninguna credencial (R3.4). Es la
    senal para que ms_certificado use el almacen local de contenido direccionable.
    """


def _multipart_pdf(contenido: bytes, nombre_archivo: str) -> tuple[bytes, str]:
    """Arma un cuerpo multipart/form-data con el PDF bajo el campo `file` de Pinata."""
    boundary = f"----voltera{uuid.uuid4().hex}"
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{nombre_archivo}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")
    cuerpo = pre + bytes(contenido) + post
    return cuerpo, boundary


def subir_pdf(contenido: bytes, *, jwt: str, nombre_archivo: str = "certificado.pdf") -> str:
    """Sube `contenido` a Pinata via `pinFileToIPFS` y devuelve el CID (`IpfsHash`).

    Lanza `PinataNoDisponible` si falta el JWT o si la subida falla por red/HTTP, para que
    el llamador caiga al almacen local. El JWT nunca aparece en los mensajes de error.
    """
    if not jwt:
        raise PinataNoDisponible("sin credenciales de Pinata (PINATA_JWT ausente)")

    cuerpo, boundary = _multipart_pdf(contenido, nombre_archivo)
    peticion = urlrequest.Request(PINATA_PIN_FILE_URL, data=cuerpo, method="POST")
    peticion.add_header("Authorization", f"Bearer {jwt}")
    peticion.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urlrequest.urlopen(peticion, timeout=_TIMEOUT_S) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        raise PinataNoDisponible(f"Pinata respondio HTTP {exc.code} al subir el certificado") from None
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise PinataNoDisponible(f"no se pudo contactar Pinata al subir: {exc.__class__.__name__}") from None
    except ValueError as exc:
        raise PinataNoDisponible("respuesta de Pinata ilegible al subir el certificado") from None

    cid = datos.get("IpfsHash")
    if not isinstance(cid, str) or not cid:
        raise PinataNoDisponible("Pinata no devolvio un CID (IpfsHash) valido")
    return cid


def recuperar(cid: str, *, gateway: str) -> bytes:
    """Recupera por `cid` el contenido desde el gateway de Pinata/IPFS.

    Lanza `PinataNoDisponible` si no se puede recuperar (red, timeout, HTTP, CID ausente en
    el gateway). El llamador puede entonces intentar el almacen local; si tampoco esta, la
    verificacion debe terminar en ERROR (nunca INTEGRO) (R3.11, R3.12).
    """
    url = f"{gateway.rstrip('/')}/{cid}"
    peticion = urlrequest.Request(url, method="GET")
    try:
        with urlrequest.urlopen(peticion, timeout=_TIMEOUT_S) as resp:
            return resp.read()
    except urlerror.HTTPError as exc:
        raise PinataNoDisponible(f"el gateway respondio HTTP {exc.code} para el CID solicitado") from None
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise PinataNoDisponible(
            f"no se pudo recuperar el contenido del gateway: {exc.__class__.__name__}"
        ) from None
