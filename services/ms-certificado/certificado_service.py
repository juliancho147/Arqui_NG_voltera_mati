"""Logica de dominio de ms_certificado: emision, anclaje y verificacion (R3, R5.5, R5.6, R5.11).

Reune las piezas del servicio y mantiene nitida la frontera on-chain / off-chain:

Emision (`emitir_certificado`, R3.2, R5.5, R5.6, R5.11):
  1. Genera el PDF determinista de la compra (modulo `pdf`).
  2. Lo guarda: intenta Pinata (`pinFileToIPFS`) y, si no hay credenciales/red, cae al
     almacen local de contenido direccionable (fallback R3.3). Ambos caminos producen el
     mismo CID (CIDv1 raw sha2-256), por lo que el CID queda determinado por el contenido.
  3. **Solo si el guardado tuvo exito** llama `MarketEscrow.anclar(ofertaId, cid)` (R5.5,
     R5.6). Si el guardado falla, NO ancla y registra la compra afectada (R5.11).

Verificacion (`verificar_certificado`, R3.5, R3.7, R3.11, R3.12):
  1. Lee el CID anclado on-chain con el getter `certificado(ofertaId)`.
  2. Recupera el contenido por CID (Pinata gateway o fallback local).
  3. Recalcula el identificador por contenido (`calcular_cid`) y lo compara con el CID
     anclado -> veredicto INTEGRO / ALTERADO.
  4. Si no hay CID anclado o el contenido no se puede recuperar -> veredicto ERROR. Nunca
     INTEGRO ni falso positivo (R3.11, R3.12).

Las credenciales (JWT de Pinata, llave de la plataforma) nunca se incluyen en las
respuestas ni en los registros (R3.4): los resultados solo exponen CID, veredicto y causa.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pinata
from config import Config
from contenido import AlmacenContenidoDisco, ContenidoNoEncontrado, calcular_cid
from pdf import generar_pdf

logger = logging.getLogger("ms_certificado")


class Veredicto(str, Enum):
    """Resultado de verificar un certificado contra su CID anclado (R3.5, R3.7)."""

    INTEGRO = "INTEGRO"
    ALTERADO = "ALTERADO"
    ERROR = "ERROR"


class CertificadoError(RuntimeError):
    """Error de dominio al emitir un certificado (guardado fallido, anclaje revertido)."""


@dataclass
class ResultadoEmision:
    """Resultado de emitir y anclar (o no) un certificado."""

    oferta_id: int
    cid: str
    almacenamiento: str  # "pinata" | "local"
    anclado: bool
    tx_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ofertaId": self.oferta_id,
            "cid": self.cid,
            "almacenamiento": self.almacenamiento,
            "anclado": self.anclado,
            "txHash": self.tx_hash,
        }


@dataclass
class ResultadoVerificacion:
    """Resultado de verificar un certificado por contenido contra el CID anclado."""

    oferta_id: int
    veredicto: Veredicto
    cid_anclado: str | None = None
    cid_recalculado: str | None = None
    origen: str | None = None  # "pinata" | "local" | None
    motivo: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ofertaId": self.oferta_id,
            "veredicto": self.veredicto.value,
            "cidAnclado": self.cid_anclado,
            "cidRecalculado": self.cid_recalculado,
            "origen": self.origen,
            "motivo": self.motivo,
        }


class CertificadoService:
    """Servicio de certificados: genera PDF, guarda (Pinata/fallback), ancla y verifica.

    El cliente de cadena (`chain`) es un `ChainClient` del runner blockchain; se inyecta
    para poder probar la logica con un doble. El almacen local es el fallback de Pinata.
    """

    def __init__(self, config: Config, chain: Any, almacen: AlmacenContenidoDisco | None = None) -> None:
        self._config = config
        self._chain = chain
        self._almacen = almacen if almacen is not None else AlmacenContenidoDisco(config.almacen_dir)
        # Registro de compras cuyo guardado fallo y que, por tanto, no se anclaron (R5.11).
        self.compras_sin_anclar: list[dict[str, Any]] = []

    # ---- guardado (Pinata con fallback local) --------------------------------
    def _guardar(self, contenido: bytes) -> tuple[str, str]:
        """Guarda el contenido y devuelve `(cid, almacenamiento)`.

        Intenta Pinata si hay credenciales; ante cualquier fallo cae al almacen local
        (R3.3). El CID es el mismo en ambos caminos porque esta determinado por el contenido.
        Siempre deja una copia local, para que la verificacion pueda recuperar el contenido
        aun si el gateway no responde luego.
        """
        cid_local = self._almacen.guardar(contenido)
        if self._config.pinata_habilitado:
            try:
                cid_pinata = pinata.subir_pdf(contenido, jwt=self._config.pinata_jwt)
            except pinata.PinataNoDisponible as exc:
                logger.warning("Pinata no disponible, usando fallback local: %s", exc)
            else:
                if cid_pinata != cid_local:
                    # No deberia ocurrir (mismo algoritmo de CID); se prefiere el de Pinata
                    # como fuente de verdad del guardado remoto, pero se registra la anomalia.
                    logger.warning("CID de Pinata difiere del local; se usa el de Pinata")
                return cid_pinata, "pinata"
        return cid_local, "local"

    # ---- emision -------------------------------------------------------------
    def emitir_certificado(self, oferta_id: int, datos_compra: dict[str, Any]) -> ResultadoEmision:
        """Genera el PDF, lo guarda y, solo si el guardado tuvo exito, lo ancla on-chain.

        Si el guardado falla por completo, no se ancla y la compra se registra como afectada
        (R5.11), lanzando `CertificadoError`.
        """
        pdf_bytes = generar_pdf(oferta_id, datos_compra)
        try:
            cid, almacenamiento = self._guardar(pdf_bytes)
        except Exception as exc:  # pragma: no cover - el fallback local no deberia fallar
            self.compras_sin_anclar.append({"ofertaId": oferta_id, "motivo": str(exc)})
            logger.error("guardado del certificado fallo para oferta %s; no se ancla", oferta_id)
            raise CertificadoError(f"no se pudo guardar el certificado de la oferta {oferta_id}") from exc

        # Solo tras guardar con exito se ancla el CID on-chain (R5.5, R5.6).
        tx_hash = self._anclar(oferta_id, cid)
        return ResultadoEmision(
            oferta_id=oferta_id,
            cid=cid,
            almacenamiento=almacenamiento,
            anclado=tx_hash is not None,
            tx_hash=tx_hash,
        )

    def _anclar(self, oferta_id: int, cid: str) -> str | None:
        """Llama `MarketEscrow.anclar(ofertaId, cid)` y espera confirmacion (<=30 s, sin reintento).

        Devuelve el hash de la tx si confirmo; si se revierte o no confirma, registra la
        compra afectada (R5.11) y devuelve None (no reintenta, R5.10).
        """
        escrow = self._chain.market_escrow
        tx = escrow.functions.anclar(int(oferta_id), cid).build_transaction(
            {
                "from": self._chain.plataforma,
                "nonce": self._chain.siguiente_nonce(),
            }
        )
        resultado = self._chain.enviar_y_esperar(tx)
        if resultado.confirmada:
            return resultado.transactionHash
        self.compras_sin_anclar.append(
            {"ofertaId": oferta_id, "cid": cid, "motivo": f"anclaje {resultado.estado.value}"}
        )
        logger.error("anclaje de la oferta %s no confirmo (%s)", oferta_id, resultado.estado.value)
        return None

    # ---- verificacion --------------------------------------------------------
    def _leer_cid_anclado(self, oferta_id: int) -> str:
        """Lee el CID anclado on-chain con el getter `certificado(ofertaId)`."""
        return self._chain.market_escrow.functions.certificado(int(oferta_id)).call()

    def _recuperar(self, cid: str) -> tuple[bytes, str]:
        """Recupera el contenido por `cid`: intenta Pinata gateway y cae al almacen local.

        Lanza `ContenidoNoEncontrado` si ninguno lo tiene (insumo del veredicto ERROR).
        """
        if self._config.pinata_habilitado:
            try:
                datos = pinata.recuperar(cid, gateway=self._config.pinata_gateway)
                return datos, "pinata"
            except pinata.PinataNoDisponible as exc:
                logger.warning("recuperacion por gateway fallo, probando fallback local: %s", exc)
        try:
            return self._almacen.recuperar(cid), "local"
        except ContenidoNoEncontrado:
            raise

    def verificar_certificado(self, oferta_id: int) -> ResultadoVerificacion:
        """Verifica por contenido el certificado de `oferta_id` contra su CID anclado.

        INTEGRO sii el CID recalculado del contenido recuperado coincide con el CID anclado.
        ERROR si no hay CID anclado o el contenido no se puede recuperar: nunca INTEGRO ni
        falso positivo (R3.11, R3.12).
        """
        try:
            cid_anclado = self._leer_cid_anclado(oferta_id)
        except Exception as exc:
            return ResultadoVerificacion(
                oferta_id=oferta_id,
                veredicto=Veredicto.ERROR,
                motivo=f"no se pudo leer el CID anclado: {exc.__class__.__name__}",
            )

        if not cid_anclado:
            return ResultadoVerificacion(
                oferta_id=oferta_id,
                veredicto=Veredicto.ERROR,
                motivo="no hay certificado anclado para la oferta",
            )

        try:
            contenido, origen = self._recuperar(cid_anclado)
        except ContenidoNoEncontrado:
            return ResultadoVerificacion(
                oferta_id=oferta_id,
                veredicto=Veredicto.ERROR,
                cid_anclado=cid_anclado,
                motivo="contenido no recuperable para el CID anclado",
            )
        except Exception as exc:
            return ResultadoVerificacion(
                oferta_id=oferta_id,
                veredicto=Veredicto.ERROR,
                cid_anclado=cid_anclado,
                motivo=f"error al recuperar el contenido: {exc.__class__.__name__}",
            )

        cid_recalculado = calcular_cid(contenido)
        veredicto = Veredicto.INTEGRO if cid_recalculado == cid_anclado else Veredicto.ALTERADO
        return ResultadoVerificacion(
            oferta_id=oferta_id,
            veredicto=veredicto,
            cid_anclado=cid_anclado,
            cid_recalculado=cid_recalculado,
            origen=origen,
        )
