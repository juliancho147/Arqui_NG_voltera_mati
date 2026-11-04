"""Servidor HTTP de ms_certificado (patron `main.py` del repo, stdlib `http.server`).

Endpoints (R3, R5.5, R5.6, R5.11):

* ``GET  /healthz``        -> estado del servicio (sin credenciales).
* ``POST /certificados``   -> ``{ofertaId, datosCompra}``: genera el PDF, lo sube a Pinata
                              (fallback local) y, solo si el guardado tuvo exito, ancla el
                              CID con ``MarketEscrow.anclar``.
* ``POST /verificaciones`` -> ``{ofertaId}``: lee el CID anclado, recupera el contenido y
                              recalcula el identificador por contenido devolviendo el
                              veredicto INTEGRO / ALTERADO / ERROR.

El cliente de cadena se construye de forma perezosa (al primer endpoint que lo necesita),
para que el servicio pueda arrancar y responder `/healthz` aunque `deployment.json` o la
llave custodial aun no esten disponibles (readiness del orquestador).
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from config import Config, cargar_config
from health import estado_salud

logger = logging.getLogger("ms_certificado")


class _Estado:
    """Estado compartido del servidor: config y servicio de certificados (perezoso)."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._servicio: Any = None

    def servicio(self) -> Any:
        """Devuelve el `CertificadoService`, construyendolo (y su cadena) al primer uso."""
        if self._servicio is None:
            # Importes diferidos: solo se necesitan cuando hay un endpoint de dominio y
            # permiten servir /healthz sin un despliegue/llave presentes.
            from certificado_service import CertificadoService
            from chain import construir_chain_client

            chain = construir_chain_client(self.config.rpc_url, self.config.deployment_path)
            self._servicio = CertificadoService(self.config, chain)
        return self._servicio


class Handler(BaseHTTPRequestHandler):
    """Enrutador HTTP del servicio."""

    estado: _Estado  # inyectado por `crear_servidor`

    def log_message(self, formato: str, *args: Any) -> None:  # noqa: A003 - firma de la stdlib
        logger.info("%s - %s", self.address_string(), formato % args)

    # ---- helpers de respuesta ------------------------------------------------
    def _responder(self, codigo: int, cuerpo: dict[str, Any]) -> None:
        datos = json.dumps(cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _leer_json(self) -> dict[str, Any]:
        longitud = int(self.headers.get("Content-Length") or 0)
        if longitud <= 0:
            return {}
        crudo = self.rfile.read(longitud)
        return json.loads(crudo.decode("utf-8"))

    # ---- rutas ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - firma de la stdlib
        if self.path == "/healthz":
            self._responder(200, estado_salud(self.estado.config))
            return
        self._responder(404, {"error": "no encontrado"})

    def do_POST(self) -> None:  # noqa: N802 - firma de la stdlib
        if self.path == "/certificados":
            self._manejar_certificados()
        elif self.path == "/verificaciones":
            self._manejar_verificaciones()
        else:
            self._responder(404, {"error": "no encontrado"})

    def _manejar_certificados(self) -> None:
        try:
            cuerpo = self._leer_json()
        except ValueError:
            self._responder(400, {"error": "JSON invalido"})
            return
        oferta_id = cuerpo.get("ofertaId")
        datos_compra = cuerpo.get("datosCompra")
        if oferta_id is None or not isinstance(datos_compra, dict):
            self._responder(400, {"error": "se requieren 'ofertaId' y 'datosCompra'"})
            return
        try:
            from certificado_service import CertificadoError

            resultado = self.estado.servicio().emitir_certificado(int(oferta_id), datos_compra)
        except CertificadoError as exc:
            # El guardado fallo: no se ancla y se registra la compra afectada (R5.11).
            self._responder(502, {"error": str(exc), "anclado": False})
            return
        except Exception as exc:  # noqa: BLE001 - se traduce a 500 sin filtrar credenciales
            logger.exception("fallo al emitir certificado")
            self._responder(500, {"error": exc.__class__.__name__})
            return
        self._responder(201, resultado.as_dict())

    def _manejar_verificaciones(self) -> None:
        try:
            cuerpo = self._leer_json()
        except ValueError:
            self._responder(400, {"error": "JSON invalido"})
            return
        oferta_id = cuerpo.get("ofertaId")
        if oferta_id is None:
            self._responder(400, {"error": "se requiere 'ofertaId'"})
            return
        try:
            resultado = self.estado.servicio().verificar_certificado(int(oferta_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("fallo al verificar certificado")
            self._responder(500, {"error": exc.__class__.__name__})
            return
        self._responder(200, resultado.as_dict())


def crear_servidor(config: Config | None = None) -> ThreadingHTTPServer:
    """Crea el servidor HTTP del servicio ligado al puerto de la configuracion."""
    cfg = config if config is not None else cargar_config()
    estado = _Estado(cfg)

    class _Handler(Handler):
        pass

    _Handler.estado = estado
    return ThreadingHTTPServer(("0.0.0.0", cfg.port), _Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    servidor = crear_servidor()
    puerto = servidor.server_address[1]
    logger.info("ms_certificado escuchando en el puerto %s", puerto)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
