"""Dashboard web en vivo para ejecutar y visualizar los experimentos (stdlib only).

Sirve una pagina HTML y expone una API minima:

* ``GET  /``                -> la pagina del dashboard.
* ``GET  /estado``          -> estado de la cadena/contratos (JSON).
* ``POST /run/<exp>``       -> lanza E1/E2/E3/all como subproceso; devuelve un runId.
* ``GET  /stream/<runId>``  -> Server-Sent Events con los hitos de progreso (tail del JSONL).
* ``GET  /reporte/<runId>`` -> el report.json final de esa corrida (cuando exista).

No agrega dependencias: usa `http.server` y el emisor `progreso` (JSON-lines). Cada
corrida escribe su progreso en ``/tmp/voltera-progreso-<runId>.jsonl`` y su reporte en
``experiments/reports-blockchain/``. El dashboard lanza el mismo flujo que `experimentos.sh`
(helpers inline que levantan los microservicios y corren el experimento).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest

# experiments/runner-blockchain/runner_blockchain/dashboard.py -> repo root
ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / "experiments" / "runner-blockchain"
VENV_PY = RUNNER_DIR / ".venv" / "bin" / "python"
REPORTS_DIR = ROOT / "experiments" / "reports-blockchain"
DEPLOYMENT = ROOT / "deployment.json"
RPC_URL = "http://127.0.0.1:8545"
PROG_DIR = Path("/tmp")

HTML_PATH = Path(__file__).resolve().parent / "dashboard.html"

# runId -> info de la corrida en curso/terminada
_corridas: dict[str, dict] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Estado de la cadena
# ---------------------------------------------------------------------------
def _rpc(metodo: str):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": metodo, "params": []}).encode()
    req = urlrequest.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=2) as r:
        return json.loads(r.read()).get("result")


def estado_cadena() -> dict:
    out = {"anvil": False, "bloque": None, "contratos": False, "pinata": False}
    try:
        bn = _rpc("eth_blockNumber")
        out["anvil"] = True
        out["bloque"] = int(bn, 16) if isinstance(bn, str) else bn
    except Exception:
        return out
    try:
        if DEPLOYMENT.is_file():
            dep = json.loads(DEPLOYMENT.read_text())
            addr = dep["contratos"]["MarketEscrow"]
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getCode",
                                  "params": [addr, "latest"]}).encode()
            req = urlrequest.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
            with urlrequest.urlopen(req, timeout=2) as r:
                code = json.loads(r.read()).get("result", "0x")
            out["contratos"] = isinstance(code, str) and len(code) > 2
    except Exception:
        pass
    out["pinata"] = bool(os.environ.get("PINATA_JWT")) or (ROOT / ".env").is_file()
    return out


# ---------------------------------------------------------------------------
# Lanzamiento de una corrida como subproceso
# ---------------------------------------------------------------------------
EXPERIMENTOS = {"e1", "e2", "e3", "all"}

# Script Python inline que corre el experimento pedido, levantando los microservicios y
# acotando la lectura de eventos al bloque actual (evita contaminacion entre corridas).
_RUNNER_SNIPPET = r'''
import os, sys, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from pathlib import Path
from runner_blockchain import progreso, cli, servicios as S
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain.experimentos import e1, e2, e3
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte

progreso.configurar(os.environ["VOLTERA_PROGRESO"])
exp = os.environ["VOLTERA_EXP"]
offers = int(os.environ.get("VOLTERA_OFFERS", "10"))
buys   = int(os.environ.get("VOLTERA_BUYS", "10"))
total  = int(os.environ.get("VOLTERA_TOTAL", "10"))
reports = Path(os.environ["VOLTERA_REPORTS"])

progreso.emitir("entorno", "cargando deployment.json y resolviendo contratos", exp="runner")
dep = load_deployment(Path(os.environ["VOLTERA_DEPLOYMENT"]))
lector = cli._lector_por_defecto(dep)
desde = lector.client.w3.eth.block_number + 1
progreso.emitir("entorno", f"entorno listo (bloque inicial {desde})", exp="runner",
                contratos=dict(dep.contratos))

def correr_e1():
    ms = S.Microservicios(S.construir_specs(deployment_path=dep.ruta, rpc_url=dep.rpc_url)); ms.iniciar()
    try:
        return e1.ejecutar_e1("RUN-E1", "http://127.0.0.1:8080", lector, from_block=desde)
    finally:
        ms.detener()

def correr_e3():
    ms = S.Microservicios(S.construir_specs(deployment_path=dep.ruta, rpc_url=dep.rpc_url)); ms.iniciar()
    try:
        return e3.ejecutar_e3("RUN-E3", lector,
                              venta=e3.HttpVentaClient("http://127.0.0.1:8083"),
                              compra=e3.HttpCompraClient("http://127.0.0.1:8084"),
                              repeticiones=offers, compras_por_oferta=buys, from_block=desde)
    finally:
        ms.detener()

def correr_e2():
    jwt = os.environ.get("PINATA_JWT") or None
    if jwt:
        backend = e2.construir_backend_pinata_local(dep, jwt=jwt, almacen_dir=ROOT_ALMACEN)
        res = e2.ejecutar(backend, run_id="RUN-E2", total=total)
    else:
        backend = e2.construir_backend_en_proceso(dep, almacen_dir=ROOT_ALMACEN)
        res = e2.ejecutar(backend, run_id="RUN-E2", total=total)
    return res

ROOT_ALMACEN = Path(os.environ["VOLTERA_DEPLOYMENT"]).parent / ".certificados-e2"

resultados = []
try:
    if exp in ("e1", "all"): resultados.append(correr_e1())
    if exp in ("e2", "all"): resultados.append(correr_e2())
    if exp in ("e3", "all"): resultados.append(correr_e3())
    rep = reporte_desde_deployment(f"RUN-{exp.upper()}", resultados, dep,
                                   params={"seleccion": exp})
    out = escribir_reporte(rep, reports)
    print("REPORT_DIR=" + str(out))
except Exception as ex:
    progreso.emitir("error", f"corrida abortada: {ex}", exp="runner")
    raise
'''


def lanzar(exp: str, *, offers: int = 10, buys: int = 10, total: int = 10) -> str:
    run_id = f"{exp}-{uuid.uuid4().hex[:8]}"
    prog = PROG_DIR / f"voltera-progreso-{run_id}.jsonl"
    prog.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "VOLTERA_PROGRESO": str(prog),
        "VOLTERA_EXP": exp,
        "VOLTERA_OFFERS": str(offers),
        "VOLTERA_BUYS": str(buys),
        "VOLTERA_TOTAL": str(total),
        "VOLTERA_DEPLOYMENT": str(DEPLOYMENT),
        "VOLTERA_REPORTS": str(REPORTS_DIR),
        "PLATAFORMA_PRIVATE_KEY": env.get(
            "PLATAFORMA_PRIVATE_KEY",
            "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"),
        "PATH": os.path.expanduser("~/.foundry/bin") + os.pathsep + env.get("PATH", ""),
    })
    log = PROG_DIR / f"voltera-run-{run_id}.log"
    proc = subprocess.Popen(
        [str(VENV_PY), "-c", _RUNNER_SNIPPET],
        cwd=str(RUNNER_DIR), env=env,
        stdout=log.open("w"), stderr=subprocess.STDOUT,
    )
    with _lock:
        _corridas[run_id] = {"exp": exp, "prog": prog, "log": log, "proc": proc,
                             "report_dir": None, "terminado": False}
    return run_id


def _buscar_report_dir(run_id: str) -> str | None:
    info = _corridas.get(run_id)
    if not info:
        return None
    try:
        txt = info["log"].read_text(encoding="utf-8")
    except OSError:
        return None
    for line in txt.splitlines():
        if line.startswith("REPORT_DIR="):
            return line.split("=", 1)[1].strip()
    return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, HTML_PATH.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif path == "/estado":
            self._send(200, json.dumps(estado_cadena()))
        elif path.startswith("/stream/"):
            self._stream(path.rsplit("/", 1)[1])
        elif path.startswith("/reporte/"):
            self._reporte(path.rsplit("/", 1)[1])
        else:
            self._send(404, json.dumps({"error": "no encontrado"}))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/run/"):
            exp = path.rsplit("/", 1)[1].lower()
            if exp not in EXPERIMENTOS:
                self._send(400, json.dumps({"error": f"experimento invalido: {exp}"}))
                return
            largo = int(self.headers.get("Content-Length", 0) or 0)
            cuerpo = {}
            if largo:
                try: cuerpo = json.loads(self.rfile.read(largo))
                except ValueError: cuerpo = {}
            run_id = lanzar(exp,
                            offers=int(cuerpo.get("offers", 10)),
                            buys=int(cuerpo.get("buys", 10)),
                            total=int(cuerpo.get("total", 10)))
            self._send(200, json.dumps({"runId": run_id}))
        else:
            self._send(404, json.dumps({"error": "no encontrado"}))

    def _stream(self, run_id):
        info = _corridas.get(run_id)
        if not info:
            self._send(404, json.dumps({"error": "corrida desconocida"}))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        prog = info["prog"]; proc = info["proc"]
        pos = 0
        try:
            while True:
                try:
                    txt = prog.read_text(encoding="utf-8")
                except OSError:
                    txt = ""
                if len(txt) > pos:
                    nuevo = txt[pos:]; pos = len(txt)
                    for line in nuevo.splitlines():
                        if line.strip():
                            self.wfile.write(f"data: {line}\n\n".encode())
                    self.wfile.flush()
                termino = proc.poll() is not None
                if termino:
                    # drena lo que quede y cierra
                    rd = _buscar_report_dir(run_id)
                    info["report_dir"] = rd; info["terminado"] = True
                    fin = {"fase": "fin", "msg": "proceso finalizado",
                           "exp": "runner", "data": {"reportDir": rd, "codigo": proc.returncode}}
                    self.wfile.write(f"data: {json.dumps(fin)}\n\n".encode())
                    self.wfile.flush()
                    break
                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _reporte(self, run_id):
        rd = _corridas.get(run_id, {}).get("report_dir") or _buscar_report_dir(run_id)
        if not rd:
            self._send(404, json.dumps({"error": "reporte aun no disponible"}))
            return
        rj = Path(rd) / "report.json"
        if not rj.is_file():
            self._send(404, json.dumps({"error": "report.json no encontrado"}))
            return
        self._send(200, rj.read_text(encoding="utf-8"))


def main():
    puerto = int(os.environ.get("VOLTERA_DASH_PORT", "8800"))
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    print(f"Dashboard Voltera en http://127.0.0.1:{puerto}  (Ctrl-C para parar)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
