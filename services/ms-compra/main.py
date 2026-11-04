"""ms_compra: microservicio de compra de ofertas del mercado (R5.4, R5.9, R5.10).

Responsabilidad real que valida E3: ejecutar la compra de una oferta llamando a
`MarketEscrow.comprar(ofertaId, comprador)` con firma custodial (la plataforma firma; el
comprador viaja como **parametro**, no como `msg.sender`) y esperar la confirmacion
on-chain <=30 s sin reintento. El resultado es exito o reversion, acompanado del hash de
la transaccion (R5.4).

Modos de disparo:

  * `comprar(ofertaId, comprador)`            -> una compra individual (`POST /compras`).
  * `comprar_concurrente(ofertaId, compradores)` -> envio en **paralelo** de N compras
    sobre la misma oferta con `concurrent.futures` y **nonces explicitos** repartidos por
    el `chain_client` (una sola lectura de `eth_getTransactionCount`, reparto
    `nonce, nonce+1, ...`). Es el modo que usa E3: para una oferta Activa, exactamente una
    compra confirma y las demas revierten con `OfertaNoDisponible` (lo garantiza el escrow,
    no este servicio).

La atomicidad "una sola venta por oferta" vive en el contrato; este servicio solo dispara
las transacciones y reporta el desenlace (confirmada/revertida/timeout + hash). No
reintenta ante reversion ni timeout (R5.10): registra el error con el identificador de la
operacion y deja la compra sin marcar como completada.

Transporte HTTP (stdlib `http.server`, patron del repo):
  * `GET  /healthz`  -> readiness.
  * `POST /compras`  -> `{ofertaId, comprador}` => una compra; responde el desenlace + hash.
  * `POST /compras/concurrentes` -> `{ofertaId, compradores:[...]}` => disparo concurrente;
    responde la lista de desenlaces y un resumen (confirmadas/revertidas/timeouts).
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from config import Config
from health import health_payload

logger = logging.getLogger("ms_compra")


# ---- Puerto del cliente de cadena (lo que ms_compra necesita del chain_client) ----------
class ChainClientLike(Protocol):
    """Subconjunto de `ChainClient` del que depende ms_compra.

    Se declara como Protocol para poder inyectar un cliente real
    (`runner_blockchain.chain.chain_client.ChainClient`) o un doble de prueba sin acoplar
    el servicio a la red.
    """

    plataforma: str

    @property
    def market_escrow(self) -> Any:  # web3 Contract
        ...

    def repartir_nonces(self, cantidad: int, base: int | None = None) -> list[int]:
        ...

    def enviar_tx(self, tx: dict[str, Any]) -> str:
        ...

    def esperar_recibo(self, tx_hash: str, timeout_s: int | None = None) -> Any:  # ResultadoTx
        ...


@dataclass(frozen=True)
class ResultadoCompra:
    """Desenlace de una compra disparada por ms_compra.

    `exito` es True solo si la transaccion se confirmo (estado CONFIRMADA). Reversion y
    timeout son `exito=False` con el `estado` correspondiente; en ambos casos se conserva
    el `transactionHash` cuando existe para la evidencia de E3.
    """

    ofertaId: int
    comprador: str
    exito: bool
    estado: str
    transactionHash: str | None
    gasUsed: int | None = None
    blockNumber: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ofertaId": self.ofertaId,
            "comprador": self.comprador,
            "exito": self.exito,
            "estado": self.estado,
            "transactionHash": self.transactionHash,
            "gasUsed": self.gasUsed,
            "blockNumber": self.blockNumber,
            "error": self.error,
        }


class CompraService:
    """Logica de dominio de ms_compra: dispara `comprar` y reporta el desenlace.

    No conoce HTTP; recibe un `ChainClientLike` ya configurado con la direccion de
    MarketEscrow (p. ej. via `set_direcciones` desde `deployment.json`). El handler HTTP lo
    envuelve.
    """

    def __init__(self, chain: ChainClientLike) -> None:
        self._chain = chain

    # ---- construccion de la transaccion comprar(ofertaId, comprador) --------------------
    def _construir_tx(self, oferta_id: int, comprador: str, nonce: int | None) -> dict[str, Any]:
        """Construye la tx de `MarketEscrow.comprar(ofertaId, comprador)` lista para firmar.

        El `nonce` se pasa explicito en el modo concurrente para evitar colisiones (todas
        las compras las firma la misma cuenta custodial y comparten el espacio de nonce).
        En el modo individual puede ir None y lo resuelve web3/el cliente.
        """
        params: dict[str, Any] = {"from": self._chain.plataforma}
        if nonce is not None:
            params["nonce"] = nonce
        fn = self._chain.market_escrow.functions.comprar(int(oferta_id), comprador)
        return fn.build_transaction(params)

    def _disparar(self, oferta_id: int, comprador: str, nonce: int | None) -> ResultadoCompra:
        """Firma, envia y espera el recibo de una compra; nunca reintenta (R5.10)."""
        try:
            tx = self._construir_tx(oferta_id, comprador, nonce)
            tx_hash = self._chain.enviar_tx(tx)
        except Exception as exc:  # error de construccion/envio: la compra no queda hecha
            logger.error("compra ofertaId=%s comprador=%s fallo al enviar: %s", oferta_id, comprador, exc)
            return ResultadoCompra(
                ofertaId=int(oferta_id),
                comprador=comprador,
                exito=False,
                estado="error_envio",
                transactionHash=None,
                error=str(exc),
            )
        recibo = self._chain.esperar_recibo(tx_hash)
        resultado = ResultadoCompra(
            ofertaId=int(oferta_id),
            comprador=comprador,
            exito=bool(getattr(recibo, "confirmada", False)),
            estado=_estado_str(recibo),
            transactionHash=getattr(recibo, "transactionHash", tx_hash),
            gasUsed=getattr(recibo, "gasUsed", None),
            blockNumber=getattr(recibo, "blockNumber", None),
        )
        if not resultado.exito:
            # Reversion/timeout: registrar con el identificador de la operacion, sin reintentar.
            logger.warning(
                "compra ofertaId=%s comprador=%s no completada (estado=%s tx=%s)",
                oferta_id,
                comprador,
                resultado.estado,
                resultado.transactionHash,
            )
        return resultado

    def comprar(self, oferta_id: int, comprador: str) -> ResultadoCompra:
        """Ejecuta una compra individual de `oferta_id` para `comprador` (R5.4).

        Devuelve el desenlace con el hash de tx: exito si confirmo, reversion/timeout en
        caso contrario. No reintenta.
        """
        return self._disparar(oferta_id, comprador, nonce=None)

    def comprar_concurrente(
        self, oferta_id: int, compradores: list[str], *, max_workers: int | None = None
    ) -> list[ResultadoCompra]:
        """Dispara en paralelo N compras sobre la **misma** oferta (modo E3, R4.1/R4.2).

        Reparte nonces explicitos (`nonce, nonce+1, ...`) con una sola lectura de
        `eth_getTransactionCount` via `chain_client.repartir_nonces`, porque todas las
        transacciones las firma la misma cuenta custodial. Envia con `concurrent.futures`.
        El escrow garantiza que exactamente una confirme y el resto revierta con
        `OfertaNoDisponible`; este servicio solo reporta cada desenlace, en el mismo orden
        que `compradores`.
        """
        cantidad = len(compradores)
        if cantidad == 0:
            return []
        nonces = self._chain.repartir_nonces(cantidad)
        trabajadores = cantidad if max_workers is None else max(1, max_workers)
        resultados: list[ResultadoCompra | None] = [None] * cantidad
        with ThreadPoolExecutor(max_workers=trabajadores) as pool:
            futuros = {
                pool.submit(self._disparar, oferta_id, compradores[i], nonces[i]): i
                for i in range(cantidad)
            }
            for futuro in futuros:
                indice = futuros[futuro]
                resultados[indice] = futuro.result()
        return [r for r in resultados if r is not None]


def _estado_str(recibo: Any) -> str:
    """Normaliza el estado del recibo (`ResultadoTx.estado`) a cadena."""
    estado = getattr(recibo, "estado", None)
    if estado is None:
        return "desconocido"
    return getattr(estado, "value", str(estado))


# ---- Transporte HTTP (stdlib http.server) -----------------------------------------------
def make_handler(service: CompraService) -> type[BaseHTTPRequestHandler]:
    """Crea la clase handler HTTP ligada a una instancia de `CompraService`."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "ms_compra/1.0"

        def log_message(self, *args: Any) -> None:  # silencia el log por request del stdlib
            return

        # -- utilidades de respuesta --
        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            cuerpo = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _read_json(self) -> Any:
            largo = int(self.headers.get("Content-Length", 0) or 0)
            if largo <= 0:
                return {}
            crudo = self.rfile.read(largo)
            return json.loads(crudo.decode("utf-8"))

        # -- rutas --
        def do_GET(self) -> None:  # noqa: N802 (stdlib exige este nombre)
            if self.path.rstrip("/") == "/healthz":
                self._send_json(200, health_payload())
                return
            self._send_json(404, {"error": "no encontrado", "path": self.path})

        def do_POST(self) -> None:  # noqa: N802
            ruta = self.path.rstrip("/") or "/"
            try:
                cuerpo = self._read_json()
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": f"JSON invalido: {exc}"})
                return

            if ruta == "/compras":
                self._handle_compra(cuerpo)
            elif ruta == "/compras/concurrentes":
                self._handle_compra_concurrente(cuerpo)
            else:
                self._send_json(404, {"error": "no encontrado", "path": self.path})

        def _handle_compra(self, cuerpo: Any) -> None:
            if not isinstance(cuerpo, dict) or "ofertaId" not in cuerpo or "comprador" not in cuerpo:
                self._send_json(400, {"error": "se requieren 'ofertaId' y 'comprador'"})
                return
            try:
                oferta_id = int(cuerpo["ofertaId"])
            except (TypeError, ValueError):
                self._send_json(400, {"error": "'ofertaId' debe ser entero"})
                return
            comprador = cuerpo["comprador"]
            if not isinstance(comprador, str) or not comprador.strip():
                self._send_json(400, {"error": "'comprador' debe ser una direccion no vacia"})
                return
            resultado = service.comprar(oferta_id, comprador.strip())
            # 200 confirmada; 409 reversion/timeout (la compra no se completo, sin reintento).
            codigo = 200 if resultado.exito else 409
            self._send_json(codigo, resultado.as_dict())

        def _handle_compra_concurrente(self, cuerpo: Any) -> None:
            if not isinstance(cuerpo, dict) or "ofertaId" not in cuerpo or "compradores" not in cuerpo:
                self._send_json(400, {"error": "se requieren 'ofertaId' y 'compradores'"})
                return
            try:
                oferta_id = int(cuerpo["ofertaId"])
            except (TypeError, ValueError):
                self._send_json(400, {"error": "'ofertaId' debe ser entero"})
                return
            compradores = cuerpo["compradores"]
            if not isinstance(compradores, list) or not all(
                isinstance(c, str) and c.strip() for c in compradores
            ):
                self._send_json(400, {"error": "'compradores' debe ser una lista de direcciones no vacias"})
                return
            resultados = service.comprar_concurrente(oferta_id, [c.strip() for c in compradores])
            confirmadas = sum(1 for r in resultados if r.exito)
            self._send_json(
                200,
                {
                    "ofertaId": oferta_id,
                    "resumen": {
                        "total": len(resultados),
                        "confirmadas": confirmadas,
                        "revertidas": sum(1 for r in resultados if r.estado == "revertida"),
                        "timeouts": sum(1 for r in resultados if r.estado == "timeout"),
                    },
                    "resultados": [r.as_dict() for r in resultados],
                },
            )

    return Handler


def build_service(config: Config) -> CompraService:
    """Construye el `CompraService` real a partir de la config y `deployment.json`.

    Resuelve el RPC y la direccion de MarketEscrow desde `deployment.json` (o `RPC_URL` del
    entorno), crea el `ChainClient` custodial y lo inyecta. Se importa el paquete comun de
    forma perezosa para que los tests puedan construir el servicio con un cliente de prueba
    sin requerir web3 ni la cadena.
    """
    from runner_blockchain.chain.chain_client import ChainClient
    from runner_blockchain.chain.deployment import load_deployment

    deployment = load_deployment(config.deployment_path)
    rpc_url = config.rpc_url or deployment.rpc_url
    chain = ChainClient(rpc_url, contratos={"MarketEscrow": deployment.market_escrow})
    return CompraService(chain)


def run(config: Config | None = None) -> None:
    """Arranca el servidor HTTP de ms_compra (bloqueante)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = config or Config.from_env()
    service = build_service(cfg)
    handler = make_handler(service)
    servidor = ThreadingHTTPServer((cfg.host, cfg.port), handler)
    logger.info("ms_compra escuchando en http://%s:%d", cfg.host, cfg.port)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    run()
