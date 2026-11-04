"""Servidor HTTP de dominio de ms_energia: `POST /emisiones` + `GET /healthz`.

Extiende el patron `http.server` de la stdlib que el repo ya usa en `health.py` a un
endpoint de dominio, sin introducir un bus: la generacion validada llega como una peticion
HTTP (transporte sincrono elegido en el diseno) y la respuesta reporta el resultado de la
emision por `lecturaId`.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from emitter import EmisionService, GeneracionValidada, ValidacionError

MAX_BODY = 1 << 20  # 1 MiB: una generacion validada es un objeto JSON pequeno


def make_server(
    port: int,
    service: EmisionService,
    check: Callable[[], dict],
    *,
    emisiones_path: str = "/emisiones",
    health_path: str = "/healthz",
) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] not in (health_path, "/health", "/"):
                self._send(404, {"error": "no encontrado"})
                return
            status = check()
            self._send(200 if status.get("ok") else 503, status)

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != emisiones_path:
                self._send(404, {"error": "no encontrado"})
                return
            payload = self._leer_json()
            if payload is None:
                return  # _leer_json ya respondio con el error
            try:
                gen = GeneracionValidada.desde_payload(payload)
            except ValidacionError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                resultado = service.emitir(gen)
            except Exception as exc:  # error inesperado de cadena/cliente
                self._send(502, {"error": f"fallo al emitir: {exc}", "lecturaId": gen.lectura_id})
                return
            # Emitida o reentrega idempotente => 200; fallo terminal on-chain (revertida/timeout) => 502.
            code = 200 if (resultado.emitida or resultado.duplicada) else 502
            self._send(code, resultado.as_dict())

        def _leer_json(self):
            try:
                largo = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                self._send(400, {"error": "Content-Length invalido"})
                return None
            if largo <= 0:
                self._send(400, {"error": "cuerpo vacio"})
                return None
            if largo > MAX_BODY:
                self._send(413, {"error": "cuerpo demasiado grande"})
                return None
            crudo = self.rfile.read(largo)
            try:
                return json.loads(crudo.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"error": "cuerpo JSON invalido"})
                return None

        def _send(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silencio
            return

    return ThreadingHTTPServer(("0.0.0.0", port), H)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name="ms-energia", daemon=True)
    t.start()
    return t
