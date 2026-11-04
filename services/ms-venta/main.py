"""Punto de entrada de ms_venta (proceso HTTP separado, patron del repo).

Expone:
  * `POST /ofertas`                 -> `MarketEscrow.publicar(vendedor, id, kwh)`; devuelve `ofertaId`.
  * `POST /ofertas/{id}/cancelar`   -> `MarketEscrow.cancelar(ofertaId)`.
  * `GET  /healthz`                 -> readiness (cadena alcanzable + direccion resuelta).

Firma custodial via `ChainClient` (la plataforma firma; el vendedor es un parametro) y espera
confirmacion on-chain <=30 s sin reintento (R5.3, R5.9, R5.10). La direccion de `MarketEscrow`
y el RPC se resuelven de `deployment.json` (o del entorno como respaldo).
"""
from __future__ import annotations

import json
import re
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import Settings
from venta import VentaError, VentaService

from runner_blockchain.chain.chain_client import build_chain_client
from runner_blockchain.chain.deployment import DeploymentError, load_deployment

# Rutas: /ofertas/{id}/cancelar con id entero.
_RE_CANCELAR = re.compile(r"^/ofertas/(\d+)/cancelar$")


def construir_chain_client(settings: Settings):
    """Construye el `ChainClient` resolviendo RPC y direccion de `MarketEscrow`.

    Prioriza `deployment.json` (RPC + direcciones de ambos contratos); si no existe o esta
    mal formado, cae a `RPC_URL` + `MARKET_ESCROW_ADDRESS` del entorno. Lanza si no hay
    forma de resolver la direccion, para no arrancar un servicio que no puede operar.
    """
    rpc_url = settings.rpc_url
    contratos: dict[str, str] = {}
    try:
        dep = load_deployment(settings.deployment_path or None)
        rpc_url = dep.rpc_url
        contratos = dict(dep.contratos)
    except DeploymentError:
        if not settings.market_escrow:
            raise
        contratos = {"MarketEscrow": settings.market_escrow}
    chain = build_chain_client(rpc_url, contratos=contratos)
    return chain


def _leer_json(handler: BaseHTTPRequestHandler) -> dict:
    """Lee y parsea el cuerpo JSON de la peticion; lanza ValueError si no es un objeto."""
    longitud = int(handler.headers.get("Content-Length", "0") or 0)
    crudo = handler.rfile.read(longitud) if longitud else b""
    if not crudo:
        return {}
    datos = json.loads(crudo)
    if not isinstance(datos, dict):
        raise ValueError("el cuerpo debe ser un objeto JSON")
    return datos


def make_app_server(port: int, service: VentaService, health_check) -> ThreadingHTTPServer:
    """Servidor HTTP con las rutas de dominio de ms_venta y el healthcheck."""

    class H(BaseHTTPRequestHandler):
        def _responder(self, code: int, cuerpo: dict) -> None:
            body = json.dumps(cuerpo).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] in ("/healthz", "/health", "/"):
                estado = health_check()
                self._responder(200 if estado.get("ok") else 503, estado)
                return
            self._responder(404, {"error": "no encontrado"})

        def do_POST(self):  # noqa: N802
            ruta = self.path.split("?")[0]
            try:
                m = _RE_CANCELAR.match(ruta)
                if m is not None:
                    self._cancelar(int(m.group(1)))
                    return
                if ruta == "/ofertas":
                    self._publicar()
                    return
                self._responder(404, {"error": "no encontrado"})
            except ValueError as exc:
                self._responder(400, {"error": f"cuerpo invalido: {exc}"})
            except VentaError as exc:
                self._responder(400, {"error": str(exc)})
            except Exception as exc:  # fallo tecnico (cadena/RPC)
                self._responder(502, {"error": f"error al operar con la cadena: {exc}"})

        def _publicar(self) -> None:
            datos = _leer_json(self)
            vendedor = datos.get("vendedor")
            resultado = service.publicar(vendedor, datos.get("id"), datos.get("kwh"))
            code = 201 if resultado.tx.confirmada else 502
            self._responder(code, resultado.as_dict())

        def _cancelar(self, oferta_id: int) -> None:
            resultado = service.cancelar(oferta_id)
            code = 200 if resultado.tx.confirmada else 502
            self._responder(code, resultado.as_dict())

        def log_message(self, *args):  # silencio
            return

    return ThreadingHTTPServer(("0.0.0.0", port), H)


def main() -> None:
    settings = Settings.from_env()
    chain = construir_chain_client(settings)
    service = VentaService(chain)

    def health() -> dict:
        try:
            alcanzable = bool(chain.w3.is_connected())
        except Exception:
            alcanzable = False
        tiene_escrow = "MarketEscrow" in getattr(chain, "_direcciones", {})
        return {"ok": alcanzable and tiene_escrow, "service": settings.service,
                "cadena": alcanzable, "marketEscrow": tiene_escrow}

    app = make_app_server(settings.health_port, service, health)
    stop = threading.Event()

    def on_term(signum, frame):
        stop.set()
        app.shutdown()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    app.serve_forever()


if __name__ == "__main__":
    main()
