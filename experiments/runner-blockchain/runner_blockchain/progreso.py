"""Emisor de hitos de progreso de una corrida, para el dashboard en vivo.

El runner escribe hitos estructurados (JSON-lines) en un archivo que el dashboard
sigue (tail) y retransmite por Server-Sent Events. El acoplamiento es minimo y
opcional: si no hay archivo de progreso configurado (variable de entorno
``VOLTERA_PROGRESO`` o `configurar()`), `emitir()` no hace nada, de modo que los
experimentos y las pruebas no se ven afectados cuando no hay dashboard.

Cada hito es un objeto JSON en una linea con, al menos:
  * ``ts``    marca temporal epoch (float),
  * ``fase``  identificador de la fase (``entorno`` | ``servicios`` | ``inyeccion``
              | ``eventos`` | ``veredicto`` | ``info`` | ``error``),
  * ``msg``   texto legible,
  * ``exp``   experimento al que pertenece (``E1``|``E2``|``E3``|``runner``), opcional,
  * ``data``  datos adicionales serializables (contadores, veredicto, etc.), opcional.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_ENV_VAR = "VOLTERA_PROGRESO"
_lock = threading.Lock()
_ruta: Path | None = None


def configurar(ruta: str | Path | None) -> None:
    """Fija el archivo de progreso de la corrida (o lo desactiva con None)."""
    global _ruta
    with _lock:
        _ruta = Path(ruta) if ruta else None
        if _ruta is not None:
            _ruta.parent.mkdir(parents=True, exist_ok=True)


def _ruta_activa() -> Path | None:
    if _ruta is not None:
        return _ruta
    env = os.environ.get(_ENV_VAR)
    return Path(env) if env else None


def emitir(fase: str, msg: str, *, exp: str | None = None, **data: Any) -> None:
    """Escribe un hito de progreso (no falla nunca; si no hay ruta, es no-op)."""
    destino = _ruta_activa()
    if destino is None:
        return
    evento = {"ts": time.time(), "fase": fase, "msg": msg}
    if exp is not None:
        evento["exp"] = exp
    if data:
        evento["data"] = data
    try:
        with _lock:
            with destino.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # El progreso es accesorio: nunca debe romper la corrida.
        pass


def fin(veredicto: str, *, report_dir: str | None = None, **data: Any) -> None:
    """Marca el fin de la corrida con el veredicto final y la ruta del reporte."""
    emitir("veredicto", f"corrida terminada: {veredicto}", exp="runner",
           veredicto=veredicto, reportDir=report_dir, **data)
