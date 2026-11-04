"""Arranque de Anvil, despliegue de contratos y publicacion de `deployment.json` (R1).

Flujo del orquestador del Entorno_Experimental:

1. Arranca ``anvil --chain-id 11155111 --port 8545`` como proceso hijo y hace *polling*
   de ``eth_chainId`` / ``eth_blockNumber`` hasta que responde, con tope de 30 s (R1.1).
2. Si el puerto 8545 ya esta en uso o se agota el readiness: no despliega y registra un
   error con la causa (R1.2).
3. Despliega con el script Foundry existente
   ``forge script script/Desplegar.s.sol --rpc-url http://localhost:8545
   --private-key $PLATAFORMA_PRIVATE_KEY --broadcast`` (cwd ``blockchain/``). El script ya
   ejecuta ``configurarMercado`` dentro de ``run()`` (R1.3, R1.4).
4. Extrae las direcciones desplegadas de ``blockchain/broadcast/`` (con *fallback* a la
   salida del script) y escribe ``deployment.json`` con chainId, rpcUrl, plataforma,
   contratos, herramientas Foundry y marca temporal (R1.3).
5. Si un despliegue falla: detiene, deja los experimentos sin habilitar y registra el
   contrato afectado y el motivo (R1.6).

Usa el binario nativo de Foundry (forge/anvil/cast), sin Docker (R1.5).
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from urllib import error as urlerror
from urllib import request as urlrequest

from ..chain.chain_client import load_private_key

logger = logging.getLogger(__name__)

# experiments/runner-blockchain/runner_blockchain/orquestador/entorno.py -> repo root
ROOT = Path(__file__).resolve().parents[4]
BLOCKCHAIN_DIR = ROOT / "blockchain"
BROADCAST_DIR = BLOCKCHAIN_DIR / "broadcast"
DEPLOY_SCRIPT = "script/Desplegar.s.sol"

CHAIN_ID = 11155111
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8545
RPC_URL = f"http://localhost:{DEFAULT_PORT}"

# Tope duro de readiness exigido por R1.1 (y causa de abortar por timeout, R1.2).
READINESS_TIMEOUT_S = 30
READINESS_POLL_INTERVAL_S = 0.5
# Tope del subproceso de despliegue (forge); generoso respecto al readiness.
DEPLOY_TIMEOUT_S = 180

FOUNDRY_VERSION = "1.9.0"
CONTRATOS = ("EnergyToken", "MarketEscrow")

# "EnergyToken  : 0x..." / "MarketEscrow : 0x..." en la salida del script (console.log).
_LOG_ADDR = re.compile(r"(EnergyToken|MarketEscrow)\s*:?\s*(0x[0-9a-fA-F]{40})")


class EntornoError(RuntimeError):
    """Fallo del orquestador del entorno con la causa registrada (R1.2, R1.6)."""


@dataclass
class ResultadoEntorno:
    """Resultado de preparar el entorno: ruta de `deployment.json` y direcciones."""

    rpc_url: str
    chain_id: int
    plataforma: str
    contratos: dict[str, str]
    deployment_path: Path
    desplegado_en: str


# ---------------------------------------------------------------------------
# Readiness de Anvil
# ---------------------------------------------------------------------------
def puerto_ocupado(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """True si ya hay algo escuchando en `host:port` (detecta el puerto ocupado, R1.2)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def _rpc_call(rpc_url: str, method: str, timeout: float = 2.0) -> Any:
    """Llamada JSON-RPC minima (sin dependencias de web3) para el *polling* de readiness."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": []}).encode("utf-8")
    req = urlrequest.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (RPC local controlado)
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data and data["error"]:
        raise EntornoError(f"JSON-RPC {method} devolvio error: {data['error']}")
    return data.get("result")


def esperar_cadena(
    rpc_url: str = RPC_URL,
    *,
    timeout_s: int = READINESS_TIMEOUT_S,
    intervalo_s: float = READINESS_POLL_INTERVAL_S,
    proceso: subprocess.Popen[bytes] | None = None,
) -> int:
    """*Polling* de `eth_chainId`/`eth_blockNumber` hasta responder, con tope de 30 s (R1.1).

    Devuelve el chain-id leido. Si el proceso hijo muere antes de responder, aborta con la
    causa. Si se agota el tope, lanza `EntornoError` (que el llamador traduce a "no desplegar",
    R1.2).
    """
    limite = time.monotonic() + timeout_s
    ultima_causa = "sin respuesta"
    while time.monotonic() < limite:
        if proceso is not None and proceso.poll() is not None:
            raise EntornoError(f"el proceso de Anvil termino antes de responder (codigo {proceso.returncode})")
        try:
            chain_id_hex = _rpc_call(rpc_url, "eth_chainId")
            _rpc_call(rpc_url, "eth_blockNumber")
            return int(chain_id_hex, 16) if isinstance(chain_id_hex, str) else int(chain_id_hex)
        except (urlerror.URLError, OSError, ValueError, EntornoError) as exc:
            ultima_causa = str(exc)
            time.sleep(intervalo_s)
    raise EntornoError(
        f"tiempo de espera agotado: Anvil no respondio a la consulta JSON-RPC de estado en {timeout_s} s "
        f"(ultima causa: {ultima_causa})"
    )


def arrancar_anvil(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    chain_id: int = CHAIN_ID,
) -> subprocess.Popen[bytes]:
    """Arranca `anvil --chain-id <id> --port <port>` como proceso hijo (R1.1, R1.5)."""
    cmd = ["anvil", "--chain-id", str(chain_id), "--port", str(port), "--host", host]
    logger.info("arrancando Anvil: %s", " ".join(cmd))
    try:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        raise EntornoError(
            "no se encontro el binario `anvil`; instala Foundry (forge/anvil/cast 1.9.0) y verifica el PATH"
        ) from exc


def detener_anvil(proceso: subprocess.Popen[bytes] | None, *, timeout_s: float = 10.0) -> None:
    """Detiene el proceso de Anvil de forma ordenada (terminate, luego kill)."""
    if proceso is None or proceso.poll() is not None:
        return
    proceso.terminate()
    try:
        proceso.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=timeout_s)


# ---------------------------------------------------------------------------
# Despliegue de contratos
# ---------------------------------------------------------------------------
def _comando_despliegue(rpc_url: str, private_key: str) -> list[str]:
    return [
        "forge",
        "script",
        DEPLOY_SCRIPT,
        "--rpc-url",
        rpc_url,
        "--private-key",
        private_key,
        "--broadcast",
    ]


def desplegar_contratos(
    rpc_url: str = RPC_URL,
    *,
    private_key: str | None = None,
    chain_id: int = CHAIN_ID,
    timeout_s: int = DEPLOY_TIMEOUT_S,
) -> dict[str, str]:
    """Despliega con `forge script Desplegar.s.sol` (cwd `blockchain/`) y extrae direcciones.

    El script ya ejecuta `configurarMercado` dentro de `run()` (R1.4). Devuelve
    ``{"EnergyToken": "0x..", "MarketEscrow": "0x.."}``. Si el despliegue falla o faltan
    direcciones, lanza `EntornoError` indicando el contrato afectado y el motivo (R1.6).
    """
    llave = private_key or load_private_key()
    cmd = _comando_despliegue(rpc_url, llave)
    cmd_seguro = " ".join(c if c != llave else "***" for c in cmd)
    logger.info("desplegando contratos: %s (cwd=%s)", cmd_seguro, BLOCKCHAIN_DIR)
    try:
        proc = subprocess.run(  # noqa: S603 (argumentos controlados)
            cmd,
            cwd=str(BLOCKCHAIN_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EntornoError(
            "no se encontro el binario `forge`; instala Foundry (forge/anvil/cast 1.9.0) y verifica el PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EntornoError(f"el despliegue excedio el tope de {timeout_s} s") from exc

    if proc.returncode != 0:
        raise EntornoError(
            "fallo el despliegue de los contratos EnergyToken/MarketEscrow "
            f"(forge script codigo {proc.returncode}): {_cola(proc.stderr or proc.stdout)}"
        )

    direcciones = _extraer_direcciones(proc.stdout or "", rpc_url, chain_id)
    faltantes = [c for c in CONTRATOS if c not in direcciones]
    if faltantes:
        raise EntornoError(
            "despliegue sin direccion para: "
            + ", ".join(faltantes)
            + f"; no se pudo extraer de la salida ni de broadcast/. Salida: {_cola(proc.stdout)}"
        )
    return direcciones


def _extraer_direcciones(stdout: str, rpc_url: str, chain_id: int) -> dict[str, str]:
    """Extrae direcciones de `broadcast/` (preferido) con *fallback* a la salida del script."""
    desde_broadcast = _direcciones_desde_broadcast(chain_id)
    desde_log = _direcciones_desde_salida(stdout)
    # broadcast/ es la fuente canonica; la salida del script completa lo que falte.
    direcciones = dict(desde_log)
    direcciones.update(desde_broadcast)
    return direcciones


def _direcciones_desde_salida(stdout: str) -> dict[str, str]:
    """Lee las lineas `console.log` del script (`EnergyToken : 0x..`, `MarketEscrow : 0x..`)."""
    direcciones: dict[str, str] = {}
    for nombre, addr in _LOG_ADDR.findall(stdout or ""):
        direcciones[nombre] = addr
    return direcciones


def _direcciones_desde_broadcast(chain_id: int) -> dict[str, str]:
    """Lee `broadcast/Desplegar.s.sol/<chainId>/run-latest.json` y mapea nombre->direccion."""
    run_latest = BROADCAST_DIR / "Desplegar.s.sol" / str(chain_id) / "run-latest.json"
    if not run_latest.is_file():
        return {}
    try:
        data = json.loads(run_latest.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("no se pudo leer %s: %s", run_latest, exc)
        return {}
    direcciones: dict[str, str] = {}
    for tx in data.get("transactions", []):
        if tx.get("transactionType") != "CREATE":
            continue
        nombre = tx.get("contractName")
        addr = tx.get("contractAddress")
        if nombre in CONTRATOS and addr:
            direcciones[nombre] = addr
    return direcciones


def _cola(texto: str | None, n: int = 600) -> str:
    """Ultimos `n` caracteres de `texto` para registrar el motivo sin inundar el log."""
    if not texto:
        return "(sin salida)"
    texto = texto.strip()
    return texto if len(texto) <= n else "..." + texto[-n:]


# ---------------------------------------------------------------------------
# deployment.json
# ---------------------------------------------------------------------------
def escribir_deployment(
    destino: Path,
    *,
    plataforma: str,
    contratos: dict[str, str],
    chain_id: int = CHAIN_ID,
    rpc_url: str = RPC_URL,
    desplegado_en: str | None = None,
) -> str:
    """Escribe `deployment.json` (R1.3) y devuelve la marca temporal usada."""
    ts = desplegado_en or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    documento = {
        "chainId": chain_id,
        "rpcUrl": rpc_url,
        "plataforma": plataforma,
        "contratos": {
            "EnergyToken": contratos["EnergyToken"],
            "MarketEscrow": contratos["MarketEscrow"],
        },
        "herramientas": {"foundry": FOUNDRY_VERSION},
        "desplegadoEn": ts,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(documento, indent=2) + "\n", encoding="utf-8")
    logger.info("deployment.json escrito en %s", destino)
    return ts


# ---------------------------------------------------------------------------
# Orquestacion completa
# ---------------------------------------------------------------------------
def _plataforma_desde_llave(private_key: str | None) -> str:
    """Direccion de la cuenta custodial derivada de la llave (para `deployment.json`)."""
    from eth_account import Account

    llave = private_key or load_private_key()
    return Account.from_key(llave).address


def preparar_entorno(
    *,
    deployment_path: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    chain_id: int = CHAIN_ID,
    rpc_url: str = RPC_URL,
    private_key: str | None = None,
    readiness_timeout_s: int = READINESS_TIMEOUT_S,
    anvil: subprocess.Popen[bytes] | None = None,
    gestionar_anvil: bool = True,
) -> tuple[ResultadoEntorno, subprocess.Popen[bytes] | None]:
    """Prepara el entorno de punta a punta (R1): arranca Anvil, despliega y escribe deployment.

    Devuelve ``(ResultadoEntorno, proceso_anvil)``. Si el proceso de Anvil lo arranca esta
    funcion, el llamador es responsable de detenerlo con `detener_anvil`; si se agota el
    readiness o el puerto esta ocupado, no se despliega (R1.2); si el despliegue falla, se
    detiene Anvil (si lo gestionamos) y se propaga el motivo (R1.6).
    """
    if deployment_path is None:
        deployment_path = ROOT / "deployment.json"

    # R1.2: puerto ocupado -> no desplegar, registrar causa.
    if anvil is None and gestionar_anvil and puerto_ocupado(host, port):
        raise EntornoError(
            f"el puerto {port} ya esta en uso: no se arranca Anvil ni se despliegan contratos"
        )

    # La llave debe existir antes de arrancar nada (R5.7): custodia de la plataforma.
    if private_key is None:
        private_key = load_private_key()

    proceso = anvil
    arrancado_aqui = False
    try:
        if proceso is None and gestionar_anvil:
            proceso = arrancar_anvil(host=host, port=port, chain_id=chain_id)
            arrancado_aqui = True

        # R1.1 / R1.2: readiness con tope de 30 s; si falla, no se despliega.
        leido = esperar_cadena(rpc_url, timeout_s=readiness_timeout_s, proceso=proceso)
        if leido != chain_id:
            logger.warning("chain-id observado %s != esperado %s", leido, chain_id)

        # R1.3 / R1.4: despliegue (el script ejecuta configurarMercado).
        contratos = desplegar_contratos(rpc_url, private_key=private_key, chain_id=chain_id)

        plataforma = _plataforma_desde_llave(private_key)
        ts = escribir_deployment(
            deployment_path,
            plataforma=plataforma,
            contratos=contratos,
            chain_id=chain_id,
            rpc_url=rpc_url,
        )
        resultado = ResultadoEntorno(
            rpc_url=rpc_url,
            chain_id=chain_id,
            plataforma=plataforma,
            contratos=contratos,
            deployment_path=deployment_path,
            desplegado_en=ts,
        )
        return resultado, proceso
    except Exception:
        # R1.6: ante fallo, detener Anvil (si lo gestionamos) y dejar los experimentos sin habilitar.
        if arrancado_aqui:
            detener_anvil(proceso)
        raise
