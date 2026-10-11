"""Inyeccion de fallos del Exp. 2: FORCE_FAIL=true o FAIL_RATE (0..1). Compatible con los placeholders."""
from __future__ import annotations

import os
import random


class InjectedFault(RuntimeError):
    """Fallo tecnico inyectado (se reintenta por Step Functions / SQS)."""


def _service_name(label: str) -> str:
    """ms-<servicio> a partir del nombre de la Lambda (voltera-exp2-ms-tarifas -> ms-tarifas); si no, la etiqueta."""
    fn = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")
    return fn[fn.index("ms-"):] if "ms-" in fn else (label or "desconocido")


def _signal(label: str) -> None:
    """Metrica FallaInyectada (dim service): permite ver en Grafana CUANDO un servicio esta fallando por inyeccion."""
    try:
        from .observability import emit_metric
        emit_metric(_service_name(label), "FallaInyectada")
    except Exception:  # la senal nunca debe ocultar ni alterar el fallo inyectado
        pass


def maybe_fail(rng: random.Random | None = None, label: str = "") -> None:
    suffix = f" [{label}]" if label else ""
    if os.environ.get("FORCE_FAIL", "false").strip().lower() == "true":
        _signal(label)
        raise InjectedFault(f"fallo inyectado (FORCE_FAIL){suffix}")
    try:
        rate = float(os.environ.get("FAIL_RATE", "0") or 0)
    except ValueError:
        rate = 0.0
    if rate > 0 and (rng or random).random() < rate:
        _signal(label)
        raise InjectedFault(f"fallo inyectado (FAIL_RATE){suffix}")
