"""Endpoint HTTP de salud de ms_venta (stdlib `http.server`, patron del repo).

El orquestador confirma readiness con `GET /healthz` antes de inyectar casos. `check()` lo
provee el servicio (p. ej. "cadena alcanzable y direccion de MarketEscrow resuelta"); un
dict con `ok=true` responde 200 y en caso contrario 503.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def make_server(port: int, check: Callable[[], dict], path: str = "/healthz") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] not in (path, "/health", "/"):
                self.send_response(404)
                self.end_headers()
                return
            status = check()
            code = 200 if status.get("ok") else 503
            body = json.dumps(status).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silencio
            return

    return ThreadingHTTPServer(("0.0.0.0", port), H)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    t.start()
    return t
