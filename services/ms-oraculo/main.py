"""Punto de entrada de ms_oraculo: servicio HTTP con `POST /lecturas` y `GET /healthz` (R5.1).

Flujo (R2.3, R2.4, R5.1):
- `POST /lecturas` recibe una lectura, la valida de forma real y determinista (`oraculo.evaluar`).
- Si es invalida: responde 200 con `{aceptada:false, motivo, categoria}` y NO emite (R2.3).
- Si es valida: la registra (para detectar duplicados), publica `GeneracionValidada` mediante
  una llamada HTTP a `ms_energia` (`POST /emisiones`) y responde 200 con `{aceptada:true}` (R2.4).
- Un cuerpo mal formado (contrato invalido) responde 400; no es un rechazo de negocio.

El transporte entre microservicios es HTTP sincrono (ver Design): `GeneracionValidada` se modela
como la peticion HTTP a `ms_energia`, correlacionada por `lecturaId`. Si la publicacion falla, la
lectura no se marca como emitida: se responde 502 para que el llamador/runner lo registre.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from config import Settings
from oraculo import (
    Lectura,
    LecturaInvalidaError,
    RegistroDuplicados,
    Veredicto,
    evaluar,
)
from stubs import ClimaStub, MedidorStub


class PublicacionError(RuntimeError):
    """Fallo al publicar `GeneracionValidada` en ms_energia (HTTP)."""


def publicar_generacion_validada_http(settings: Settings) -> Callable[[Lectura], dict[str, Any]]:
    """Crea el publicador HTTP de `GeneracionValidada` hacia `ms_energia` (`POST /emisiones`).

    Devuelve una funcion que, dada una lectura aceptada, hace `POST {MS_ENERGIA_URL}/emisiones`
    con el payload de la generacion validada (incluye `lecturaId` para idempotencia en ms_energia,
    R5.2) y espera confirmacion hasta `emision_timeout_seconds`. Lanza `PublicacionError` si la
    emision no se confirma, para que la lectura no se marque como emitida (R5.10).
    """
    url = f"{settings.ms_energia_url}/emisiones"

    def _publicar(lectura: Lectura) -> dict[str, Any]:
        cuerpo = json.dumps(
            {
                "lecturaId": lectura.lectura_id,
                "participante": lectura.participante,
                "id": _token_id(lectura),
                "kwh": lectura.kwh,
                "precio": lectura.precio,
            }
        ).encode()
        req = urllib.request.Request(
            url, data=cuerpo, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.emision_timeout_seconds) as resp:
                raw = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PublicacionError(f"no se pudo publicar GeneracionValidada en {url}: {exc}") from exc
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    return _publicar


def _token_id(lectura: Lectura) -> int:
    """Id de token determinista a partir de (fuente, epoca), coherente con EnergyToken (fuente+epoca)."""
    return abs(hash((lectura.fuente, lectura.epoca))) % (2**64)


class Oraculo:
    """Orquesta validacion + publicacion con el estado de duplicados de la corrida.

    Es seguro para hilos (el servidor HTTP es multihilo): un lock protege la lectura de los
    conjuntos de duplicados y su actualizacion tras aceptar, de modo que el veredicto por
    `lecturaId` sea consistente aun con peticiones concurrentes.
    """

    def __init__(
        self,
        settings: Settings,
        publicar: Callable[[Lectura], dict[str, Any]],
        medidor: MedidorStub | None = None,
        clima: ClimaStub | None = None,
    ) -> None:
        self.settings = settings
        self._publicar = publicar
        self.medidor = medidor or MedidorStub()
        self.clima = clima or ClimaStub()
        self.registro = RegistroDuplicados()
        self._lock = threading.Lock()
        self.aceptadas = 0
        self.rechazadas = 0

    def procesar(self, payload: dict[str, Any]) -> Veredicto:
        """Valida la lectura y, si es aceptada, publica `GeneracionValidada` (R2.3, R2.4).

        Lanza `LecturaInvalidaError` si el contrato del payload es invalido (-> 400) y
        `PublicacionError` si la emision no se confirma (-> 502). El registro de duplicados se
        actualiza solo cuando la lectura se acepta y se emite correctamente.
        """
        lectura = Lectura.from_payload(payload)
        with self._lock:
            veredicto = evaluar(
                lectura,
                self.medidor,
                self.clima,
                tolerancia_relativa=self.settings.tolerancia_relativa,
                vistas_lectura=self.registro.lecturas,
                vistas_epoca=self.registro.epocas,
            )
            if not veredicto.aceptada:
                self.rechazadas += 1
                return veredicto
            # Publicar ANTES de registrar: si la emision falla, no marcamos la lectura (R5.10).
            self._publicar(lectura)
            self.registro.registrar(lectura)
            self.aceptadas += 1
            return veredicto


def make_app_server(port: int, oraculo: Oraculo, health_check: Callable[[], dict]) -> ThreadingHTTPServer:
    """Servidor HTTP de dominio: `POST /lecturas` y `GET /healthz` (patron `http.server` del repo)."""

    class H(BaseHTTPRequestHandler):
        def _send_json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] in ("/healthz", "/health", "/"):
                status = health_check()
                self._send_json(200 if status.get("ok") else 503, status)
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != "/lecturas":
                self._send_json(404, {"error": "not_found"})
                return
            try:
                largo = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                largo = 0
            raw = self.rfile.read(largo) if largo else b""
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                self._send_json(400, {"error": "json_invalido"})
                return
            try:
                veredicto = oraculo.procesar(payload)
            except LecturaInvalidaError as exc:
                self._send_json(400, {"error": "contrato_invalido", "detalle": str(exc)})
                return
            except PublicacionError as exc:
                # La lectura era valida pero la emision no se confirmo: no se marca como emitida.
                self._send_json(502, {"error": "emision_fallida", "detalle": str(exc)})
                return
            self._send_json(200, veredicto.to_response())

        def log_message(self, *args):  # silencio
            return

    return ThreadingHTTPServer(("0.0.0.0", port), H)


def main() -> None:
    settings = Settings.from_env()
    oraculo = Oraculo(settings, publicar_generacion_validada_http(settings))

    def check() -> dict:
        return {"ok": True, "service": settings.service, "aceptadas": oraculo.aceptadas, "rechazadas": oraculo.rechazadas}

    # El servidor de dominio atiende tanto `POST /lecturas` como `GET /healthz`.
    server = make_app_server(settings.health_port, oraculo, check)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
